"""Validator:把 state.files + 模板拼成完整 Vite 项目,起 Node 子进程跑真 build。

构建策略:
- 真 npm install + vite build,带 node_modules 预装缓存。首次 npm install ~19s
  (本机 ~/.npm 有缓存;纯净环境 30-60s),复用 node_modules 后 vite build 仅 ~0.5s,
  所以 Validator 每次 build ≈ 1-2s,demo 友好。
- 缓存策略:模板目录 `templates/react-supabase-starter/node_modules` 预装一次
  (preheat,幂等),Validator 每次 build 用临时目录(mkdtemp),把配置文件 copy
  过去、`node_modules` 用 symlink 指向预装目录(0 cost 复用),src/ 写 state.files。
  build 完清理临时目录,模板不被污染。

## 为什么 Validator 是 create_agent 的 tool,不是独立 graph 节点?

曾考虑把 Validator 作为 create_agent 外层 StateGraph 的兄弟节点(subgraph 内的
interrupt 能冒泡到顶层)。但 create_agent 作为 subgraph 时,它在 interrupt(approve_prd
HITL)暂停期间,内部写入的 state.prd **不反映到顶层 state.values**(subgraph 节点未完成,
state 更新未 merge)。ag-ui-langgraph 的 STATE_SNAPSHOT 用 `graph.aget_state(config)`
(不带 subgraphs=True)取顶层 state,所以前端拿到 state.prd 为空 → PRDCard 空 → 破坏
HITL 契约。

把 Validator 作为 create_agent 的一个 tool 则保持顶层 create_agent 拓扑(state 直接
顶层可见),回喂靠 ReAct 的 ToolMessage:validate_build 失败 → ToolMessage 带 vite 错误
→ LLM(Alex)看到后重新调 write_code → 再调 validate_build,直到通过或达 MAX_BUILD_ITERS(3)。
iter<3 由 tool 内计数 + agent system prompt 共同保证。
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Annotated, Any

from langchain_core.messages import ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from .config import settings

# 模板目录(backend/templates/react-supabase-starter)
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "react-supabase-starter"

# 后端 Vite 构建产物(dist/)的静态托管根目录。
# Validator build 成功后把 workspace/dist 复制到 STATIC_PREVIEWS_DIR/{session_id}/dist/,
# main.py 用 StaticFiles 把它挂在 /preview/{session_id}/dist/ 下,前端 iframe 直接加载,
# **不依赖 CodeSandbox CDN**(Sandpack in-browser bundler 在受限网络全不可达 → 一直编译中/白屏)。
STATIC_PREVIEWS_DIR = Path(__file__).resolve().parent.parent / "static" / "previews"

# Validator 写临时 build 目录时,从模板 copy 的"项目骨架"文件(不含 node_modules / src)。
# 这些是 Alex 不会产的项目级配置;src/* 由 state.files 提供。
_TEMPLATE_FILES = (
    "package.json",
    "vite.config.ts",
    "index.html",
    "tsconfig.json",
    "postcss.config.cjs",
    "tailwind.config.cjs",
)

# 回喂次数上限(iter<3)。build 第 1/2/3 次;第 3 次仍失败 → 放弃(告诉 agent 停)。
MAX_BUILD_ITERS = 3

# 单次 build 子进程超时(秒),取 60s。
# 理由:预热已装时 vite build ~0.5s;SSE 默认超时一般 60s,build 子进程不应超过它,
# 否则用户侧 SSE 先断、后端还在傻跑。60s 足够覆盖首装/慢机 + tsc -b 的余量。
_BUILD_TIMEOUT = 60

# 输出截断:build 失败日志可能很长(含 sourcemap 堆栈),截到末尾 _MAX_OUTPUT 字符。
_MAX_OUTPUT = 4000


# ────────────────────────────────────────────────────────────────
# 预热:npm install(幂等,模板目录预装 node_modules,Validator 复用)
# ────────────────────────────────────────────────────────────────

def _has_node() -> bool:
    """本机是否装了 node + npm(后端镜像要求装 Node)。"""
    return shutil.which("node") is not None and shutil.which("npm") is not None


def preheat() -> None:
    """确保模板目录已 `npm install`。首次 ~19s,之后 node_modules 已存在则 no-op。

    由 validate_build 首次执行时调用(也可 `python -m app.validator` 手动预热)。
    """
    if not _has_node():
        return  # 没装 Node:跳过,后面 run_build 会优雅返回失败信息
    node_modules = TEMPLATE_DIR / "node_modules"
    if node_modules.exists():
        return
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    env = _clean_proxy_env()
    env["NO_COLOR"] = "1"
    subprocess.run(
        ["npm", "install", "--no-audit", "--no-fund", "--loglevel=error"],
        cwd=TEMPLATE_DIR,
        env=env,
        check=False,  # 失败不抛,让 run_build 报具体错
        timeout=300,
        capture_output=True,
        text=True,
    )


def _clean_proxy_env() -> dict[str, str]:
    """清失效代理 env(本机可能有失效 HTTP/SOCKS 代理)。"""
    env = {k: v for k, v in os.environ.items() if k.lower() not in {
        "http_proxy", "https_proxy", "all_proxy",
    }}
    return env


# ────────────────────────────────────────────────────────────────
# 核心构建逻辑(纯函数,可单独测试)
# ────────────────────────────────────────────────────────────────

def _write_workspace(files: list[dict], workspace: Path) -> None:
    """把"模板配置 + symlink node_modules + state.files"组装到 workspace。

    - copy 模板的 6 个项目骨架文件
    - symlink node_modules → 模板预装目录(复用,0 cost)
    - state.files 逐文件按 path 落盘(覆盖模板 src 占位)
    - 兜底:state.files 没给 src/index.css 时,补模板的(tailwind 指令)
    """
    for name in _TEMPLATE_FILES:
        shutil.copy2(TEMPLATE_DIR / name, workspace / name)

    # symlink node_modules(关键提速:复用模板预装,Validator 不重装)
    nm_link = workspace / "node_modules"
    if not nm_link.exists():
        try:
            nm_link.symlink_to(TEMPLATE_DIR / "node_modules")
        except (OSError, NotImplementedError):
            # 某些 FS/权限不支持 symlink:退化直接 copy(慢但能跑)
            shutil.copytree(TEMPLATE_DIR / "node_modules", nm_link, symlinks=True)

    # 写 state.files(Alex 产的 src/*)
    for f in files:
        path = f.get("path", "")
        content = f.get("content", "")
        if not path:
            continue
        safe = Path(workspace, path)
        try:
            # 防路径穿越:path 应是 src/xxx 相对路径,不能跳出 workspace
            safe.resolve().relative_to(workspace.resolve())
        except ValueError:
            continue
        safe.parent.mkdir(parents=True, exist_ok=True)
        safe.write_text(content, encoding="utf-8")

    # 保证 src/index.css 含 tailwind 三指令,且放在最前(tailwind 要求指令在前以控
    # 制注入顺序)。Alex 若没产 index.css → 落模板的;若产了但**缺 @tailwind 指令**(自己
    # 写了纯 CSS 把模板 tailwind 指令覆盖丢了)→ 前置拼上模板三行,保留 Alex 的自定义样式。
    # 否则 tailwind 不生成 base/utilities,组件里的 className 失效(虽不致 build 失败,但样式崩)。
    idx_css = workspace / "src" / "index.css"
    tailwind_src = (TEMPLATE_DIR / "src" / "index.css").read_text(encoding="utf-8")
    if not idx_css.exists():
        idx_css.parent.mkdir(parents=True, exist_ok=True)
        idx_css.write_text(tailwind_src, encoding="utf-8")
    else:
        alex_css = idx_css.read_text(encoding="utf-8")
        if "@tailwind" not in alex_css:
            idx_css.write_text(tailwind_src.rstrip() + "\n\n" + alex_css, encoding="utf-8")


def run_build(files: list[dict], session_id: str = "") -> tuple[bool, str]:
    """跑真 `vite build`,返回 (passed, output)。

    output 是 stdout + stderr 合并(失败时含 vite 的报错堆栈,用于回喂 Alex)。
    Node/npm 未装时返回 (False, "Node/npm 未安装…") 而非抛异常(让 graph 优雅降级)。

    build 成功后把 dist/ 持久化到 STATIC_PREVIEWS_DIR/{session_id}/dist/,
    供 main.py StaticFiles serve /preview/{session_id}/dist/(前端 iframe 不依赖 CDN)。
    """
    if not _has_node():
        return False, "本机/镜像未安装 Node.js 或 npm,Validator 无法执行真 build。请装 Node。"

    if not (TEMPLATE_DIR / "node_modules").exists():
        preheat()
    if not (TEMPLATE_DIR / "node_modules").exists():
        return False, "模板 node_modules 预装失败(npm install 未完成),检查网络/权限后重试,或手动 `python -m app.validator` 预热。"

    workspace = Path(tempfile.mkdtemp(prefix="atoms-build-"))
    try:
        _write_workspace(files, workspace)
        env = _clean_proxy_env()
        env["NO_COLOR"] = "1"
        env["CI"] = "1"  # CI=1 让 vite 输出更规整
        # npm run build = vite build(读 workspace/package.json 的 scripts.build)
        proc = subprocess.run(
            ["npm", "run", "build"],
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            timeout=_BUILD_TIMEOUT,
        )
        output = (proc.stdout + ("\n" + proc.stderr if proc.stderr else "")).strip()
        passed = proc.returncode == 0

        # build 成功 → 持久化 dist/ 到 STATIC_PREVIEWS_DIR(前端 iframe 预览,不依赖 CDN)
        if passed and session_id and re.match(r"^[a-zA-Z0-9_-]+$", session_id):
            _persist_build(workspace, session_id)

        return passed, output
    except subprocess.TimeoutExpired:
        return False, f"vite build 超时(>{_BUILD_TIMEOUT}s),可能依赖安装卡住或代码有死循环导入。"
    except Exception as exc:  # noqa: BLE001
        return False, f"Validator 内部异常:{type(exc).__name__}: {exc}"
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def _persist_build(workspace: Path, session_id: str) -> None:
    """把 workspace/dist/ 复制到 STATIC_PREVIEWS_DIR/{session_id}/dist/(build 成功后调)。

    覆盖语义:同一 session 重新 build → 新 dist/ 覆盖旧的。
    """
    src_dist = workspace / "dist"
    if not src_dist.exists():
        return
    dest = STATIC_PREVIEWS_DIR / session_id / "dist"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src_dist, dest)


# ────────────────────────────────────────────────────────────────
# 非标准 .from(...) 反向检测(部署前缀注入漏改的预警信号)
# ────────────────────────────────────────────────────────────────
# 背景:deploy.py:inject_table_prefix 的正则只覆盖 `.from('habits')` 这种"纯单/双引号
# 字面量"形态。LLM 若产出其他合法写法(模板字符串、变量、拼接),正则漏改 → 部署的应用
# 查 un-prefixed 表 → PostgREST 400(查无此表)。
# 这里在 validate_build 里反向扫一遍 Alex 的 .tsx/.ts:发现非字面量 .from(...) 调用就挂
# 一条 warning(ToolMessage 内容),不阻塞 build —— 让后端日志有信号可查。
# 第一道防线在 tools.py:_CODE_INSTRUCTION(prompt 硬约束),本检测是第二道防线。

# 匹配任意 `<recv>.from(<arg>)` 调用。pre 抓接收者(如 supabase / Array),arg 抓参数(到第一个 `)`)。
_FROM_CALL_RE = re.compile(r'(?P<pre>[\w$\.\]\)]*)\.from\(\s*(?P<arg>[^)\n]*?)\s*\)')

# 纯单/双引号字面量参数(正则 \w+ 可提取表名)→ inject_table_prefix 能改写,OK。
_PURE_LITERAL_FROM_ARG_RE = re.compile(r'''^(['"])[A-Za-z_][\w.-]*\1$''')

# 明确非 supabase 的 .from(...) 调用接收者末段(避免 Array.from / Buffer.from / TypedArray.from 等误报)。
_NON_SUPABASE_FROM_RECV = {
    "array", "buffer",
    "uint8array", "int8array", "uint16array", "int16array",
    "uint32array", "int32array", "float32array", "float64array",
    "biguint64array", "bigint64array",
    "set", "map", "blob", "observable", "iterable", "range",
    "data", "event",  # EventTarget/DataTransfer 也有 .from,极少在业务代码出现
}


def scan_non_literal_from_calls(files: list[dict]) -> list[str]:
    """扫描 src/*.{ts,tsx} 里 supabase 的 `.from(...)` 调用,挑出**非纯字面量**的写法。

    只看内容含 "supabase" 的文件(避免 Array.from / Buffer.from 等无关 .from 误报)。
    返回可读的违规位置列表(形如 'src/components/Dashboard.tsx:42 `.from(T)`'),空 = 无违规。

    被判违规的形态(均为 inject_table_prefix 正则漏改的写法):
      - 模板字符串:`.from(`habits`)`、``.from(`habits${x}`)``
      - 变量:    `.from(T)`
      - 拼接:    `.from('habits' + suffix)`
      - 带空格等:其他非 `(['"])\\w+\\1` 形态
    """
    offenders: list[str] = []
    for f in files:
        path = (f.get("path") or "").replace("\\", "/")
        if not (path.endswith(".ts") or path.endswith(".tsx")):
            continue
        content = f.get("content")
        if not isinstance(content, str) or "supabase" not in content:
            continue  # 不引用 supabase 的文件,其 .from(...) 不可能是表查询
        for m in _FROM_CALL_RE.finditer(content):
            arg = (m.group("arg") or "").strip()
            if not arg:
                continue  # .from() 空参 → 非表查询,跳过
            # 接收者末段(如 supabase / Array)→ 跳过明确非 supabase 的 .from
            recv_last = re.split(r"[.\]\)]", m.group("pre") or "")[-1].strip().lower()
            if recv_last in _NON_SUPABASE_FROM_RECV:
                continue
            # 纯单/双引号字面量 → inject_table_prefix 能改写,OK
            if _PURE_LITERAL_FROM_ARG_RE.match(arg):
                continue
            line = content.count("\n", 0, m.start()) + 1
            snippet = m.group(0).strip()
            offenders.append(f"{path}:{line} `{snippet}`")
    return offenders


def _format_from_warning(offenders: list[str]) -> str:
    """把违规列表渲染成 ToolMessage 用的 warning 文本(无违规 → 空串)。"""
    if not offenders:
        return ""
    head = offenders[:5]
    locations = "; ".join(head)
    extra = f"(及另外 {len(offenders) - len(head)} 处)" if len(offenders) > len(head) else ""
    return (
        "⚠️ [前缀注入风险] 检测到非标准 `.from(...)` 调用,部署时表名前缀注入可能漏改"
        "(应用查 un-prefixed 表 → PostgREST 400)。"
        f"位置:{locations}{extra}。"
        "建议改为单引号静态字面量,如 `.from('habits')`(禁用模板字符串/变量/拼接)。"
    )


# ────────────────────────────────────────────────────────────────
# 种子数据 id 非法 uuid 反向检测(种子未写库 / id 非 uuid 的预警信号)
# ────────────────────────────────────────────────────────────────
# 背景:tools.py:_CODE_INSTRUCTION 已约束"种子 id 必须是合法 uuid、且 upsert 进库"。
# 但 LLM 仍可能写出 `id: "d1"` 这种短字符串种子(只在前端渲染、不写库),用户对种子项
# 写入时拿假 id 去 insert uuid 外键 → PostgREST 22P02/400(与表名前缀问题同类但不同根:
# 这里前缀注入是对的,坏在种子 id 非法 / 种子没写库)。
# 本检测扫业务文件里 `id: "非uuid字面量"` 作预警信号,挂非阻塞 warning(不阻塞 build)。
# 第一道防线在 tools.py:_CODE_INSTRUCTION,本检测是第二道防线。

# 业务对象字面量里的 id 属性:`id: 'xxx'` / `id: "xxx"`(单/双引号,反向引用保证首尾一致)。
_SEED_ID_RE = re.compile(r'''\bid\s*:\s*(?P<q>['"])(?P<val>[^'"]+)(?P=q)''')

# 合法 uuid(8-4-4-4-12 hex),Postgres uuid 类型只校验格式不校验版本位。
_UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)


def scan_non_uuid_seed_ids(files: list[dict]) -> list[str]:
    """扫描 src/*.{ts,tsx} 业务文件里 `id: "非uuid字面量"` 作种子 id 非法预警。

    只看内容含 "supabase" 的文件(与 scan_non_literal_from_calls 同过滤,避免普通前端 state 误报)。
    返回可读的违规位置列表(形如 'src/components/HabitList.tsx:12 `id:"d1"` (值 "d1" 非 uuid)'),
    空 = 无违规。

    被判违规:对象字面量里 `id:` 后跟非 uuid 字符串字面量(如 "d1"、"1"、"habit_1")。
    合法 uuid 字面量(如 "11111111-1111-1111-1111-111111111111")不报。
    """
    offenders: list[str] = []
    for f in files:
        path = (f.get("path") or "").replace("\\", "/")
        if not (path.endswith(".ts") or path.endswith(".tsx")):
            continue
        content = f.get("content")
        if not isinstance(content, str) or "supabase" not in content:
            continue
        for m in _SEED_ID_RE.finditer(content):
            val = m.group("val")
            if _UUID_RE.match(val):
                continue  # 合法 uuid → 不报
            line = content.count("\n", 0, m.start()) + 1
            offenders.append(f'{path}:{line} `{m.group(0).strip()}` (值 "{val}" 非 uuid)')
    return offenders


def _format_seed_id_warning(offenders: list[str]) -> str:
    """把种子 id 违规列表渲染成 ToolMessage warning(无违规 → 空串)。"""
    if not offenders:
        return ""
    head = offenders[:5]
    locations = "; ".join(head)
    extra = f"(及另外 {len(offenders) - len(head)} 处)" if len(offenders) > len(head) else ""
    return (
        "⚠️ [种子数据风险] 检测到业务对象里用非 uuid 字符串作 id(如 id:\"d1\")。"
        "库主键是 uuid,种子若不写库或 id 非 uuid,用户对种子项打卡/写入会触发 PostgREST 400(22P02)。"
        f"位置:{locations}{extra}。"
        "改法:种子 id 用固定 uuid v4 字面量,且首次加载 `.upsert(种子,{onConflict:'id'})` 写进 Supabase,"
        "渲染与写操作一律用查询返回的对象。"
    )


# ────────────────────────────────────────────────────────────────
# validate_build tool(create_agent 第 5 个 tool;回喂靠 ReAct ToolMessage)
# ────────────────────────────────────────────────────────────────

@tool
def validate_build(
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Alex(工程师)写完代码后,调用本工具对生成的代码跑**真实的 vite build** 校验。

    系统会把 state.files + 项目模板拼成完整 Vite 项目,起 Node 子进程 npm run build。
    - 成功 → state.build_status="passed",流程结束,用户看到可运行的应用。
    - 失败 → state.build_status="failed" + build_errors(日志),本工具的返回消息会带
      vite 的真实错误,你(Alex)必须据此重新调用 write_code 修复(最多 3 次)。

    何时调用:write_code 返回后,立即调用本工具(不要先口头总结)。
    """
    files = state.get("files") or []
    if not files:
        return Command(update={"messages": [ToolMessage(
            content="没有可校验的代码(state.files 为空)。请先调用 write_code 生成代码,再调 validate_build。",
            tool_call_id=tool_call_id,
        )]})

    # Node/npm 缺失是环境/运维问题,不是代码问题。必须在这里提前拦截并明告
    # LLM"不要改代码"。否则落到下面 run_build 的失败分支,build_status=failed + 回喂消息
    # 会让 Alex 误以为是代码 bug,白白消耗 iter 配额反复 write_code(代码本可能完全正确)。
    # 这里不写 build_status(留 None,表示"未真正校验"而非"校验失败"),不增 iter_count。
    if not _has_node():
        return Command(update={"messages": [ToolMessage(
            content=(
                "⚠️ 当前后端运行环境未安装 Node.js / npm,Validator 无法执行真实的 vite build。\n"
                "这不是代码问题 —— state.files 本身可能完全正确,**请不要修改代码、不要重试 write_code**。\n"
                "请直接告诉用户:后端环境的 Node 尚未就绪,属于运维/部署问题,待运维补装 Node 后会自动恢复构建校验。"
            ),
            tool_call_id=tool_call_id,
        )]})

    iter_count = int(state.get("iter_count") or 0) + 1

    # 超过上限:不再 build,告诉 agent 停下(避免无限回喂)
    if iter_count > MAX_BUILD_ITERS:
        return Command(update={
            "iter_count": iter_count - 1,
            "messages": [ToolMessage(
                content=(
                    f"已达 Validator 重试上限({MAX_BUILD_ITERS} 次),停止重新生成。"
                    "请向用户总结剩余 build 错误(build_errors 已记录),由用户决定下一步。"
                ),
                tool_call_id=tool_call_id,
            )],
        })

    # 用 thread_id 作 session_id,让前端 iframe 能预览后端 build 产物(不依赖 CDN)
    session_id = str(state.get("thread_id") or "").replace("-", "")[:16] or "default"
    passed, output = run_build(files, session_id=session_id)
    # 挂一条非阻塞 warning(若有非标准 .from(...) 调用),pass/fail 两种结果都带,
    # 让后端日志/agent 都能看到部署前缀注入的漏改信号。
    from_warning = _format_from_warning(scan_non_literal_from_calls(files))
    seed_warning = _format_seed_id_warning(scan_non_uuid_seed_ids(files))
    # 两条防线挂的 warning 合并(pass/fail 都带,让 agent/日志看到前缀注入 + 种子 id 风险)
    warnings_extra = "\n\n".join(w for w in (from_warning, seed_warning) if w)

    if passed:
        # build 成功 → 写 preview_url(后端 Vite 构建产物 iframe 预览,不依赖 CDN)
        preview_url = f"http://localhost:8000/preview/{session_id}/dist/index.html"
        msg = f"✅ vite build 通过(第 {iter_count} 次校验)。生成的 React 应用可正常运行,流程结束。"
        if warnings_extra:
            msg = f"{msg}\n\n{warnings_extra}"
        return Command(update={
            "build_status": "passed",
            "build_errors": None,
            "iter_count": iter_count,
            "preview_url": preview_url,
            "messages": [ToolMessage(
                content=msg,
                tool_call_id=tool_call_id,
            )],
        })

    tail = output if len(output) <= _MAX_OUTPUT else "…(已截断)…" + output[-_MAX_OUTPUT:]
    fail_msg = (
        f"❌ vite build 失败(第 {iter_count}/{MAX_BUILD_ITERS} 次)。\n\n"
        f"构建输出:\n```\n{tail}\n```\n\n"
        "请根据上面的错误重新调用 `write_code` 修复(只改有问题的文件,保留其余)。"
        "常见原因:import 了不存在的模块、JSX 语法错、变量/组件未定义。"
    )
    if warnings_extra:
        fail_msg = f"{fail_msg}\n\n{warnings_extra}"
    return Command(update={
        "build_status": "failed",
        "build_errors": output,
        "iter_count": iter_count,
        "messages": [ToolMessage(
            content=fail_msg,
            tool_call_id=tool_call_id,
        )],
    })


# `python -m app.validator`:手动预热模板 node_modules(demo 前跑一次,避免首请求等 19s)
if __name__ == "__main__":
    print(f"预热模板 node_modules:{TEMPLATE_DIR}")
    if not _has_node():
        raise SystemExit("未检测到 node/npm,请先安装 Node.js。")
    preheat()
    if (TEMPLATE_DIR / "node_modules").exists():
        print("✅ node_modules 就绪。")
        # 顺带自检:模板单独 build 能否跑通
        ok, out = run_build([
            {"path": "src/main.tsx", "content": (TEMPLATE_DIR / "src" / "main.tsx").read_text(encoding="utf-8")},
            {"path": "src/App.tsx", "content": (TEMPLATE_DIR / "src" / "App.tsx").read_text(encoding="utf-8")},
        ])
        print(f"自检 vite build:{'✅ passed' if ok else '❌ failed'}")
        if not ok:
            print(out[:1200])
    else:
        print("❌ npm install 失败,见上文输出。")
