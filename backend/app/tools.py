"""三角色 SOP 的核心工具:write_prd / approve_prd / write_design / write_code。

设计要点:
- 基于 create_agent + 多 tool + system prompt 约束调用顺序,复用
  `create_agent(middleware=[CopilotKitMiddleware()])` 模式。
- HITL 用独立的 `approve_prd` tool 内调 `copilotkit_interrupt`。这样 `write_prd`
  返回后 state.prd 已写入(前端能读 state.prd 渲染 PRDCard),紧接着 `approve_prd`
  触发 interrupt 等用户批准,对齐"PM 产 PRD 后 interrupt"的契约。
- write_code 让 LLM 产 markdown 文件围栏(##FILE: <path> + 围栏),后端解析成
  `files: [{path, content, language}]`,每文件独立对象(不把所有代码塞进一个 JSON string)。

工具调用顺序(由 SOP_SYSTEM_PROMPT 强约束):
    Emma(PM) write_prd(requirement)  → 写 state.prd
              approve_prd()           → HITL interrupt,等用户批准
    Bob(架构) write_design()          → 读 state.prd,写 state.design
    Alex(工程)write_code()            → 读 state.design,写 state.files

HITL 机制(已核实 ag-ui-langgraph 0.0.42 源码):
- tool 内调 copilotkit_interrupt → LangGraph 暂停,interrupt 暴露在 state.tasks[*].interrupts
- ag-ui-langgraph 检测到后发 OnInterrupt CustomEvent(value=interrupt.value)
- 前端 resolve(payload) → 走 forwarded_props.command.resume → interrupt() 返回 payload
"""

from __future__ import annotations

import re
from typing import Annotated, List

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from copilotkit.langgraph import copilotkit_interrupt

from .llm import build_model
from .schema import DesignSchema, PRDSchema


# ────────────────────────────────────────────────────────────────
# markdown 文件围栏解析(不把代码塞 JSON string)
# LLM 按 "##FILE: <path>\n```<lang>\n<content>\n```" 格式产出,后端解析成 files。
# 比结构化 JSON tool call 省转义开销、不易截断,容错更好。
# ────────────────────────────────────────────────────────────────

# ##FILE: <path> 行(允许前后空白;路径可带反引号)
_FILE_HEADER_RE = re.compile(r"##FILE:\s*(.+?)\s*$")
# 独立围栏行:行首 3+ 反引号,可选语言标签(如 ```tsx / ```)。
# 按 CommonMark 规则用开头反引号数匹配闭合(闭合行反引号数 >= 开头、且无语言标签)。
_FENCE_RE = re.compile(r"^(`{3,})\s*([\w+-]*)\s*$")

_LANG_BY_EXT = {
    "tsx": "tsx", "ts": "typescript", "jsx": "jsx", "js": "javascript",
    "css": "css", "html": "html", "json": "json", "md": "markdown",
}


def _guess_language(path: str) -> str:
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return _LANG_BY_EXT.get(ext, "text")


def _match_fence(line: str) -> tuple[int, str] | None:
    """独立围栏行 → (反引号数, 语言);非围栏行 → None。"""
    m = _FENCE_RE.match(line.strip())
    if not m:
        return None
    return len(m.group(1)), m.group(2)


def parse_files_markdown(md: str) -> List[dict]:
    """把 LLM 产的 markdown 文件围栏解析成 [{path, content, language}, ...]。

    按行扫描(不靠正则非贪婪),正确处理嵌套围栏:原正则
    ``(.*?)``` `` 非贪婪到第一个 ```,代码内容里只要出现 ```(模板字符串、嵌套
    markdown 代码块)就被截断。现按 markdown 围栏语义:
      - 遇 ``##FILE:`` 行 → 紧跟一个独立 ``` 起始围栏 → 到下一个**独立** ``` 行闭合。
      - 内容里行内出现的 ```(如反引号模板字符串)不是独占一行的 ``` 不会误闭合;
        嵌套 markdown 代码块时按 CommonMark 用更长的外层围栏(如 4 个反引号)即可正确包裹。
    """
    files: List[dict] = []
    seen_paths: set = set()
    lines = md.splitlines()
    i, n = 0, len(lines)
    while i < n:
        header = _FILE_HEADER_RE.match(lines[i].lstrip())
        if not header:
            i += 1
            continue
        path = header.group(1).strip().strip("`").strip()
        i += 1
        # 紧接着必须是起始围栏行(独立 ``` 或 ```lang)
        open_fence = _match_fence(lines[i]) if i < n else None
        if open_fence is None:
            continue  # 没有起始围栏,放弃此块(外层 while 从当前行继续)
        open_len, lang = open_fence
        i += 1
        content_lines: List[str] = []
        while i < n:
            # 未闭合就撞到下一个 ##FILE: 头:本块视为异常,停在此让外层解析下一个
            if _FILE_HEADER_RE.match(lines[i].lstrip()):
                break
            fm = _match_fence(lines[i])
            if fm and fm[0] >= open_len and not fm[1]:
                i += 1  # 跳过闭合围栏
                break
            content_lines.append(lines[i])
            i += 1
        content = "\n".join(content_lines).strip("\n")
        if not path or not content or path in seen_paths:
            continue
        seen_paths.add(path)
        files.append({
            "path": path,
            "content": content,
            "language": lang or _guess_language(path),
        })
    return files


# ────────────────────────────────────────────────────────────────
# 各产物 structured output 的指令(跟 agent 的 SOP system prompt 是两回事)
# ────────────────────────────────────────────────────────────────

_PRD_INSTRUCTION = """你是一位资深产品经理。请根据给定的产品需求,产出一份结构化 PRD。

要求:
- title:产品名,中文,简洁有力,不超过 20 字。
- summary:一段话概述,2-3 句,讲清楚"为谁、解决什么问题、核心怎么做"。
- features:3-6 项核心功能,每项一句话,动词开头,具体可执行。**只产用户明确要求的功能**:用户没提登录/支付/评论等,就一律不要写进 features,不主动补功能。
- acceptanceChecks:4-6 项验收标准,每项可独立勾选验证。要覆盖核心 CRUD 与展示(如"首页首次加载能看到 3-5 条示例数据""点击新增能创建成功并立即出现在列表""统计卡片显示正确的总数和完成率""表单能校验非法输入")。**仅当 PRD 明确含登录功能时**才写登录相关验收项(如"能用邮箱注册并登录")。

风格:务实、不堆词、不编造需求范围外的功能。"""

_DESIGN_INSTRUCTION = """你是一位资深架构师 Bob。请根据给定的 PRD,产出技术设计文档。

要求:
- product_type:三选一,"web_app" / "landing" / "tool"。
- supabase_tables:数据模型表清单。每张表:
  - name:小写复数(如 users / habits / checkins)。
  - fields:字段列表。主键统一用 id(uuid, pk=true)。关联用外键(fk="表名.字段名",如 "users.id")。**外键默认可空**:只有"应用必须先选/建关联实体才能记录"的强关联(如多租户 user_id)才必填;像"记一笔食物/打卡"这种轻量记录,关联字段(如 recipe_id)要可空,否则用户一记就缺外键 → PostgREST 400。
  - 业务表都带 created_at(timestamptz)。**仅当 PRD 含登录/多租户需求时**才加 user_id(uuid, fk="users.id");无登录需求时不加。
- pages:页面/路由清单。**仅当 PRD 含登录功能时**才列 "/login"(及可选 "/register");不含登录时只列业务页面(如 ["/", "/habits"]),不要默认塞 "/login"。

界面结构(决定后续代码生成的丰富度,务必写清):
- 主界面要拆成多个组件:**顶部导航栏 + 统计卡片区(总数 / 完成率 / 今日进度等聚合指标)+ 主列表 + 录入表单**,不要设计成"只有一个添加按钮"的单薄页面。
- 统计指标根据业务表字段设计(如习惯追踪:习惯总数、今日完成数、完成率、连续打卡天数)。

只覆盖 PRD 提到的功能,不编造多余表。表数量 2-5 张为宜。"""

_CODE_INSTRUCTION = """你是一位资深前端工程师 Alex。请根据给定的设计文档,生成一个精致、有视觉冲击力、开箱即丰盈的 React + Vite + Tailwind + Supabase 应用源码(严禁冷启动空列表)。

**输出格式(严格遵守,只输出文件块,不要任何解释、前后文)**:

每个文件一个块,格式如下(##FILE: 行 + 围栏):

##FILE: src/App.tsx
```tsx
<完整文件内容>
```

##FILE: src/lib/supabase.ts
```typescript
<完整文件内容>
```

文件清单(6-8 个核心 src 文件,按需选择;不要超 8 个):

**始终产出**:
1. src/lib/supabase.ts — Supabase client(`createClient`,**必须 `export const supabase`**)。URL/key 用占位 `https://YOUR-PROJECT.supabase.co` + 字符串 `"YOUR_SUPABASE_ANON_KEY"`。**部署时系统会覆盖为真实配置**(注入 backend/.env 的 SUPABASE_URL + anon key),所以这里只要保证 `export const supabase = createClient(...)` 这一行结构正确即可。
2. src/App.tsx — 根组件(其内部逻辑见下方条件化说明)。
3. src/main.tsx — React 入口(可 `import './index.css'`,index.css 由项目模板提供)。

**条件产出(仅当 design.supabase_tables 出现 user_id 字段、或 PRD/design 明确含登录/auth 时才产;否则一律不产)**:
- src/components/Auth.tsx — 邮箱注册/登录(magic link 或邮箱密码)。用 `import { supabase } from '@/lib/supabase'` 引用 client。
- 此时 src/App.tsx 根据 session 状态切 Auth / 主界面(session 为空 → 显示 Auth;有 session → 显示主界面)。
- **若需求不含登录**:不要产 Auth.tsx;src/App.tsx 直接渲染主界面,**不要写任何 session / supabase.auth 判断**,不要 import Auth。

**业务组件(始终产出,按职责拆分,给足页面空间)**:
- src/components/Dashboard.tsx — 主界面容器:编排"导航栏 + 统计卡片区 + 主列表 + 录入表单"。
- src/components/<业务>List.tsx(如 HabitList.tsx)—— 对 design.supabase_tables 的主业务表做 CRUD,以卡片/行项展示。
- src/components/Stats.tsx — 统计卡片区:展示总数 / 完成率 / 今日进度等聚合指标(由列表数据本地计算)。
- src/components/Add<X>Form.tsx — 录入表单(弹窗或内联),用于新增业务记录。

**页面丰富度(关键,严禁做成单薄页面)**:
- 主界面必须含 **顶部导航栏(产品名 + 可选用户信息)+ 统计卡片区(2-4 张卡片)+ 主列表(卡片或行项,带图标和状态)+ 录入表单**,而不是只有一个"添加"按钮。
- **严禁冷启动空列表,且种子必须与库一致(关键 —— 否则用户一写就 400)**:主业务表组件里 hardcode 3-5 条 demo 数据作种子(如习惯追踪:["晨跑 5 公里","阅读 30 分钟","冥想 10 分钟","早睡 23 点前","写日报"];待办:["完成周报","回复邮件","准备周会"])。两条硬约束:
  1. **种子 id 必须是合法 uuid 字面量**:每个种子写死一个**固定** uuid v4(如 `"11111111-1111-1111-1111-111111111111"`、`"22222222-2222-2222-2222-222222222222"`、`"33333333-3333-3333-3333-333333333333"` …,固定是为了 upsert 幂等;不要用 `crypto.randomUUID()` 这种每次变的)。**严禁**用 `"d1"` / `"1"` / 短字符串等非 uuid 作 id —— 库主键是 uuid,非 uuid 写入会被 PostgREST 拒(400 / 22P02 invalid input syntax for type uuid)。
  2. **种子必须写进 Supabase,不能只在前端渲染**:首次加载先查库;**库为空时用 `.upsert(种子数组, { onConflict: 'id' })` 写进对应表,再用查询返回的结果渲染**(仅当查询本身网络失败时,才临时用内存种子渲染只读视图)。否则用户对种子项做写操作(如打卡 insert)时,前端拿内存假 id 去插 uuid 外键 → 必 22P02/400。带 user_id 的表,种子 upsert 要附当前登录用户 id(未登录则不 seed,登录后再 seed)。
- **一切写操作(insert/update/delete)用到的外键 id 必须取自 Supabase 查询返回的对象,严禁直接用前端内存兜底数组里的 id**(同因:内存 id 可能是非法 uuid / 库里根本不存在)。
- **严禁冷启动空列表(只读兜底,仅在网络失败时用)**:`upsert 种子 → 查库渲染` 是主路径;只有当 Supabase 查询本身抛错(网络/配额)时,才回落到内存种子做**只读展示**,并在 UI 提示"离线演示数据,登录/联网后可操作"。

**视觉设计(Tailwind 精致)**:
- 用渐变、阴影(shadow-lg/xl)、圆角卡片(rounded-2xl)、hover 效果(hover:shadow-xl hover:-translate-y-1 transition)营造质感。
- 标题大字号加粗(text-3xl/4xl font-bold),可用渐变文字(bg-clip-text text-transparent bg-gradient-to-r)。
- 按钮有 hover/active 态(hover:scale-105 active:scale-95 transition)。
- 空态给友好提示(emoji + 引导文案),不要裸露 "No data"。
- 图标用 emoji 或内联 SVG,**不要引图标库**(如 lucide-react / react-icons)。

硬约束:
- **只产 src/* 源码**。不要 package.json / vite.config / tsconfig / index.html / postcss / tailwind.config / index.css —— 这些由项目模板固定提供(Validator 与前端 Sandpack 共用同一套模板)。
- 业务逻辑贴合 design.supabase_tables 的表名/字段名。
- **Supabase 表名必须是单引号静态字面量**:所有 `supabase.from(...)` 调用一律写成 `.from('表名')` 形态(单/双引号 + 纯字面量,如 `.from('habits')`、`.from('checkins')`)。**严禁**用模板字符串(如 ``.from(`habits`)``)、变量(如 `const T='habits'; .from(T)`)、字符串拼接(如 `.from('habits' + suffix)`)、模板插值(如 ``.from(`habits${x}`)``)。理由:部署时后端用正则把 `.from('habits')` 改写成带多租户前缀的 `.from('app_xxx_habits')`,非字面量写法正则匹配不到 → 漏改 → 部署的应用查不到前缀表 → PostgREST 400(查无此表)。
- **代码必须能通过真实 vite build**:import 路径真实存在、JSX 语法正确、所有引用的变量/组件都有定义、默认导出与 import 对齐。系统会跑真实的 `vite build` 校验,失败会被要求重写。
- 单文件控制在 120 行内,精炼、可直接写盘,不堆样板注释。
- 围栏语言标注:tsx / typescript / css。
- 每个 ##FILE: 块必须紧跟一个围栏;路径用相对路径(src/xxx),不要带项目名前缀。"""


# ────────────────────────────────────────────────────────────────
# 1. write_prd(Emma / PM)
# ────────────────────────────────────────────────────────────────

@tool
def write_prd(
    requirement: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Emma(产品经理):根据产品需求产出结构化 PRD,写入共享状态。

    Args:
        requirement: 用户的产品需求(一句话概括即可)。
    """
    llm = build_model()
    structured_llm = llm.with_structured_output(PRDSchema)

    prd: PRDSchema = structured_llm.invoke(
        [
            SystemMessage(content=_PRD_INSTRUCTION),
            HumanMessage(content=requirement),
        ]
    )

    return Command(
        update={
            "requirement": requirement,
            "prd": prd.model_dump(),
            "messages": [
                ToolMessage(
                    content=f"PRD 已生成:《{prd.title}》。核心功能 {len(prd.features)} 项,验收标准 {len(prd.acceptanceChecks)} 项。接下来请求用户批准。",
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


# ────────────────────────────────────────────────────────────────
# 2. approve_prd(HITL 中断点)
# ────────────────────────────────────────────────────────────────

@tool
def approve_prd(
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """请求用户批准 PRD(HITL)。

    调用后 graph 暂停,等用户在前端点"批准"。用户批准后(resume),才继续
    进入 Architect(Bob)/ Engineer(Alex)阶段。批准前,设计/代码工具不会执行。
    """
    # copilotkit_interrupt 内部调 LangGraph 原生 interrupt():
    #   - graph 暂停,ag-ui-langgraph 发 OnInterrupt CustomEvent
    #   - 前端 resolve(payload) 后,payload 成为 interrupt() 的返回值
    # action="approve_prd" 让前端 useInterrupt 能按 type 路由渲染批准 UI。
    _answer, response = copilotkit_interrupt(
        message="PRD 已生成,请批准后进入设计与编码阶段。",
        action="approve_prd",
    )

    # HITL 默认**未批准**:缺 approved 字段(空 payload / None / 字符串)一律
    # 视为未批准,防止无鉴权环境下任何人 POST resume={} 绕过批准。
    # 批准仅认前端显式 resolve({"approved": True}) 或 resolve(True)。
    if isinstance(response, dict):
        approved = response.get("approved") is True
    elif isinstance(response, bool):
        approved = response
    else:
        approved = False

    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=(
                        "用户已批准 PRD。接下来由 Bob(架构师)产出技术设计。"
                        if approved
                        else "用户未批准 PRD。请停下,等用户给出修改方向。"
                    ),
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


# ────────────────────────────────────────────────────────────────
# 3. write_design(Bob / Architect)
# ────────────────────────────────────────────────────────────────

@tool
def write_design(
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Bob(架构师):读取已批准的 PRD,产出技术设计(含 Supabase 表结构),写入共享状态。"""
    prd = state.get("prd") if state else None
    if not prd:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content="无法产出设计:state.prd 为空(PM 还没产 PRD 或未获批准)。请先完成 PRD。",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )

    prd_brief = (
        f"产品名:{prd.get('title', '')}\n"
        f"概述:{prd.get('summary', '')}\n"
        f"核心功能:\n- " + "\n- ".join(prd.get("features", []))
    )

    llm = build_model()
    structured_llm = llm.with_structured_output(DesignSchema)
    design: DesignSchema = structured_llm.invoke(
        [
            SystemMessage(content=_DESIGN_INSTRUCTION),
            HumanMessage(content=prd_brief),
        ]
    )

    tables_summary = ", ".join(t.name for t in design.supabase_tables)
    return Command(
        update={
            "design": design.model_dump(),
            "messages": [
                ToolMessage(
                    content=f"设计已完成:product_type={design.product_type},数据表 [{tables_summary}],页面 {len(design.pages)} 个。接下来由 Alex(工程师)生成代码。",
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


# ────────────────────────────────────────────────────────────────
# 4. write_code(Alex / Engineer)
# ────────────────────────────────────────────────────────────────

@tool
def write_code(
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Alex(工程师):读取设计文档,生成 React+Vite+Tailwind+Supabase 源文件,写入共享状态。

    不用结构化 JSON tool call(多文件易被 max_tokens 截断),改为让 LLM 产
    markdown 文件围栏(##FILE: <path> + 围栏),后端 parse_files_markdown 解析成 files。
    """
    design = state.get("design") if state else None
    prd = state.get("prd") if state else None
    if not design:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content="无法生成代码:state.design 为空(Bob 还没产出设计)。请先完成设计。",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )

    design_brief = (
        f"产品:{prd.get('title', '') if prd else ''}\n"
        f"product_type: {design.get('product_type', '')}\n"
        f"数据表:\n"
        + "\n".join(
            f"- {t['name']}({', '.join(f['name']+':'+f['type'] for f in t.get('fields', []))})"
            for t in design.get("supabase_tables", [])
        )
        + f"\n页面:{design.get('pages', [])}"
    )

    llm = build_model()
    # 普通 invoke(非 structured output),让 LLM 产 markdown 文件围栏
    resp = llm.invoke(
        [
            SystemMessage(content=_CODE_INSTRUCTION),
            HumanMessage(content=design_brief),
        ]
    )
    raw = resp.content if isinstance(resp.content, str) else str(resp.content)
    files = parse_files_markdown(raw)

    if not files:
        # 解析失败:把原始输出兜底塞成一个文件,同时提示 agent
        return Command(
            update={
                "files": [
                    {
                        "path": "src/_raw_output.txt",
                        "content": raw,
                        "language": "text",
                        "status": "error",
                    }
                ],
                "messages": [
                    ToolMessage(
                        content="代码生成格式异常(没解析到 ##FILE: 块),请重新调用 write_code,严格按 ##FILE: <path> + 围栏 格式输出。",
                        tool_call_id=tool_call_id,
                    )
                ],
            }
        )

    files_with_status = [{**f, "status": "done"} for f in files]
    return Command(
        update={
            "files": files_with_status,
            "active_file": files[-1]["path"],
            "messages": [
                ToolMessage(
                    content=f"代码已生成:{len(files_with_status)} 个文件({', '.join(f['path'] for f in files_with_status[:5])}{'…' if len(files_with_status) > 5 else ''})。全部写入 state.files。",
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )
