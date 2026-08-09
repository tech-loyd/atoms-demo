"""deploy_app tool:把 state.files + 项目模板部署到 Vercel,返回真 vercel.app URL。

## 核心流程
1. 读 state.files(Alex 产的 src/*)+ 项目模板(templates/react-supabase-starter/)
2. 动态建表:读 state.design.supabase_tables(Architect Bob 产)→ 生成 CREATE TABLE
   IF NOT EXISTS SQL(主键/外键/created_at/RLS auth.uid()=user_id)→ 调 Supabase Management API
   `/v1/projects/{ref}/database/query` 建表。非阻塞:失败/缺凭证 → 仅在 ToolMessage 提示,
   不影响 Vercel 部署(已部署的应用 CRUD 会因表不存在而失败,但站点本身可访问)。
3. 注入 Supabase 配置:覆盖 src/lib/supabase.ts,写真实 SUPABASE_URL + SUPABASE_ANON_KEY
   (只公开 anon key,绝不注入 service_role / access_token)
4. POST /v13/deployments(inlined files 模式,免 git):files=[{file, data}] + projectSettings
5. 轮询 GET /v13/deployments/{id}:readyState QUEUED→INITIALIZING→BUILDING→READY/ERROR
6. 写 state.deployment_url + state.deploy_status(building/ready/failed)

## Supabase 动态建表
- 端点:`POST https://api.supabase.com/v1/projects/{ref}/database/query`(官方 Management API,
  Beta,https://supabase.com/docs/reference/api/v1-run-a-query),body `{query, read_only:false}`。
- 认证:`Authorization: Bearer <PAT>`(Personal Access Token,sbp_...)。**不是 service_role key**
  —— service_role JWT 走该端点返回 401 "JWT failed verification"(Management API 的 audience
  是 api.supabase.com,与项目 PostgREST audience 不同)。所以本仓库用 `SUPABASE_ACCESS_TOKEN`(PAT)。
- SQL 由 `generate_create_table_sql(supabase_tables)` 纯函数生成:CREATE TABLE IF NOT EXISTS
  (幂等)+ 主键(uuid → default gen_random_uuid())+ 外键(users.id → auth.users(id) on delete
  cascade)+ created_at(not null default now())+ RLS(有 user_id 的表加 4 条 auth.uid()=user_id 策略)。
- 所有标识符(表名/字段名/类型/fk)走白名单正则校验,防 SQL 注入(DDL 走特权 PAT)。

## Vercel API 关键事实(据 https://vercel.com/docs/rest-api/deployments/create-a-new-deployment)
- POST https://api.vercel.com/v13/deployments
  Headers:
    Authorization: Bearer <VERCEL_TOKEN>
    Content-Type: application/json
  Body:
    name:            项目名(小写字母/数字/短横线,全局唯一)
    files:           [{file: "相对路径", data: "文件内容字符串"}]   ← inlined 模式(免 git/SHA)
    projectSettings: {framework, buildCommand, installCommand, outputDirectory}  ← 首次部署必填
    target:          "production" | null(preview)
  Response: {id, url, readyState, ...}
    url:        "xxx.vercel.app"(不带 https://,需前缀)
    readyState: 初始 BUILDING / QUEUED

- GET https://api.vercel.com/v13/deployments/{id}
  Response: {id, url, readyState, ready, status, ...}
    readyState 终态:READY(✅)/ ERROR(❌)/ CANCELED(❌)

## 凭证安全
- VERCEL_TOKEN / SUPABASE_ACCESS_TOKEN / SUPABASE_SERVICE_ROLE_KEY 三者极敏感:
  只从环境读,绝不 log / 打印 / 写进 ToolMessage / state / 注入生成应用。
- HTTP 错误体可能含敏感信息:错误消息只保留 status code + 截断 body(200 字符)。
- 生成应用只注入 anon key(supabase.ts),service_role / access_token 永不出现在 src/*。

## 网络兜底
本机可能有失效代理。用 `ProxyHandler({})` 构造 opener,绕过 HTTP_PROXY/HTTPS_PROXY
环境变量,直连 api.vercel.com / api.supabase.com。Supabase 走 Cloudflare,必须带真实 User-Agent
(默认 Python-urllib 会被 Cloudflare 1010 拦截)。测试时也要 `env -u ...PROXY`。
"""
from __future__ import annotations

import json
import os
import re
import secrets
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Annotated, Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from .config import settings

# 模板目录(与 validator.py 同源:templates/react-supabase-starter)
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "react-supabase-starter"

# 部署时从模板 copy 的"项目骨架"文件(与 validator._TEMPLATE_FILES 同源,外加 src/index.css)。
# 这些是 Alex 不会产的项目级配置;src/* 由 state.files 提供(supabase.ts 由本工具注入)。
_TEMPLATE_FILES = (
    "package.json",
    "vite.config.ts",
    "index.html",
    "tsconfig.json",
    "postcss.config.cjs",
    "tailwind.config.cjs",
)

VERCEL_API = "https://api.vercel.com"

# Supabase Management API(动态建表用;与 Vercel 一样 stdlib urllib + ProxyHandler({}) 绕本机失效代理)
SUPABASE_MGMT_API = "https://api.supabase.com"

# 轮询参数(Vercel Hobby 套餐 Vite 构建 ~30-60s)。
# _POLL_TIMEOUT 取 90s:90s 足够覆盖典型构建,又能把 SSE 静默期
# 压短到 < 中间代理(Railway/nginx)常见的 idle timeout,降低长连接被掐断的概率
# (留余量过大会导致期间 SSE 整段无事件,代理 idle timeout 触发后断流)。
_POLL_INTERVAL = 3.0
_POLL_TIMEOUT = 90.0

# 单次 HTTP 请求超时(POST 创建 / GET 轮询 / Supabase DDL 分别用)
_HTTP_TIMEOUT_CREATE = 30
_HTTP_TIMEOUT_POLL = 15
_HTTP_TIMEOUT_DDL = 30

# Cloudflare 拦截默认 Python-urllib UA(Supabase 返 1010),所有出站请求统一带这个 UA。
# Vercel 不在意 UA,但带上无害;Supabase 必须带。
_USER_AGENT = "atoms-deploy/1.0 (backend; +curl/8 compat)"

# 项目名前缀(加 6 位 hex 保证全局唯一,避免撞 Vercel 账号下其他人的同名项目)
_PROJECT_PREFIX = "atoms-app"

# 多租户表名前缀:每 app 的业务表都带 app_id 前缀,不同 app 用独立表
# (`{app_id}_habits` / `{app_id}_checkins`),永不冲突。
# 若共用无前缀表,多次部署不同 app 会落到同一张表 → 第二次 CREATE IF NOT EXISTS 跳过,
# 表结构停留在第一次,新 app 不同字段 query → PostgREST 400(列不存在)。
#
# app_id 取 project_name 末段 hex(`atoms-app-34f04b` → `34f04b`),并加 `app_` 前缀:
# - **字母开头**(a-):即使 hex 以数字开头(如 `34f04b`)也符合 Postgres 标识符规则
#   (无引号标识符必须字母/下划线开头),且通过 _IDENT_RE 校验,无需放宽白名单。
# - 短(10 字符):表名 `app_34f04b_habits` 仍清晰,RLS policy 名远低于 63 字符上限。
_APP_ID_PREFIX = "app_"
# app_id 总长(_APP_ID_PREFIX + 6 hex);校验用,防 LLM/调用方传过长前缀撑爆 Postgres 标识符。
_APP_ID_MAXLEN = len(_APP_ID_PREFIX) + 6


def _app_id_from_project_name(project_name: str) -> str:
    """从 Vercel project_name(如 'atoms-app-34f04b')抽多租户前缀 → 'app_34f04b'。

    取末段(`atoms-app-{6hex}` 末段就是 hex),只保留 [a-f0-9],补足 6 位,加 `app_` 前缀。
    - 自定义 project_name(非 atoms-app-{hex} 形态)→ 末段非纯 hex → 用 0 补足,仍唯一性足够
      (同一部署周期 project_name 唯一,前缀碰撞概率极低;且 Vercel 项目名本身全局唯一)。
    - 始终字母开头(a)→ Postgres 标识符合规 + _IDENT_RE 通过。
    """
    last = (project_name or "").rsplit("-", 1)[-1].lower()
    hex_part = re.sub(r"[^a-f0-9]", "", last)[:6]
    if len(hex_part) < 6:
        hex_part = (hex_part + "000000")[:6]
    return _APP_ID_PREFIX + hex_part


# ────────────────────────────────────────────────────────────────
# Supabase 配置注入
# ────────────────────────────────────────────────────────────────

# 部署应用用的 Supabase client 模板(用真实 SUPABASE_URL + SUPABASE_ANON_KEY 渲染)。
# 不论 Alex 写了什么占位,本工具部署时完全覆盖为标准模板(LLM 占位形式不可控,正则替换
# 不稳健;完全覆盖保证配置正确)。前提是 Alex 其他代码用
# `import { supabase } from '@/lib/supabase'`(_CODE_INSTRUCTION 已强约束)。
# 用 {lbracket}/{rbracket} 占位避免 .format 把 createClient 的 { } 当字段。
_SUPABASE_TS_TEMPLATE = """\
// Supabase client —— 由 atoms 后端 deploy_app 注入真实配置(公开 anon key,无 service_role)。
// 占位文件在部署时被本模板覆盖,确保应用真登录/CRUD 指向真后端。
import {{ createClient }} from '@supabase/supabase-js'

export const supabase = createClient(
  '{url}',
  '{key}'
)
"""


def _render_supabase_ts(url: str, anon_key: str) -> str:
    """渲染标准 supabase.ts 内容(URL/anon key 字面量直接拼接)。

    anon key 是 JWT(base64url 字符集 A-Za-z0-9_-),不含单引号 → 单引号字符串安全。
    URL 同理(https://xxx.supabase.co)。
    """
    return _SUPABASE_TS_TEMPLATE.format(url=url, key=anon_key)


def inject_supabase_config(
    files: list[dict], url: str, anon_key: str
) -> list[dict]:
    """覆盖/补 src/lib/supabase.ts,写入真实 SUPABASE_URL + SUPABASE_ANON_KEY。

    - 找到 src/lib/supabase.ts(或任何 *lib/supabase.ts)→ 覆盖内容
    - 找不到 → 追加一个

    返回新的 files list(浅拷贝,不污染入参)。
    """
    rendered = _render_supabase_ts(url, anon_key)
    out: list[dict] = []
    replaced = False
    for f in files:
        path = (f.get("path") or "").replace("\\", "/").lstrip("./")
        if path == "src/lib/supabase.ts" or path.endswith("lib/supabase.ts"):
            out.append({**f, "path": "src/lib/supabase.ts", "content": rendered, "language": "typescript"})
            replaced = True
        else:
            out.append(dict(f))
    if not replaced:
        out.append({
            "path": "src/lib/supabase.ts",
            "content": rendered,
            "language": "typescript",
        })
    return out


def inject_table_prefix(
    files: list[dict], tables: list[dict], app_id: str
) -> list[dict]:
    """把应用代码里的 `.from('table_name')` 替换为 `.from('{app_id}_table_name')`。

    多租户隔离:应用代码访问的前缀表必须和 deploy_app 建的前缀表一致,
    否则 PostgREST 400(查无此表 / 列不匹配)。本函数覆盖式注入(与 inject_supabase_config 同理:
    不论 Alex 写了什么 from,部署时按 design.supabase_tables 的表名精确改写)。

    设计要点:
    - **只替换 design.supabase_tables 里列出的表名**(白名单),绝不误改其他字符串(如 'users'、
      注释里的 habits、变量名 habit_list)。表名按长度降序匹配,避免 'checkin' 误吃 'checkins' 的子串。
    - 正则 `\\.from\\((['"])(?:t1|t2)\\1\\)` —— 引号捕获 + 反向引用,保证首尾引号一致(单/双都行)。
    - app_id 经 _check_app_id 校验(字母开头 + 短),注入应用代码安全。
    - 跳过 src/lib/supabase.ts(刚 inject_supabase_config 注入的标准 client,无业务 .from)。

    files: state.files(Alex 产的 src/*)。
    tables: design.supabase_tables([{"name": "habits", ...}, ...])。
    app_id: 前缀(如 "app_34f04b");空串 → 原样返回(向后兼容,但多 app 会冲突)。
    返回新的 files list(浅拷贝,不污染入参)。
    """
    if not app_id or not tables:
        return [dict(f) for f in files]  # 无前缀/无表 → 浅拷贝不动

    _check_app_id(app_id)

    # 收集 + 校验表名(双保险:design 已校验过,这里再验一次防直接调用)
    raw_names: list[str] = []
    for t in tables:
        name = t.get("name", "")
        if name:
            _check_ident(name, "表名")
            raw_names.append(name)
    raw_names = sorted(set(raw_names), key=len, reverse=True)  # 长表名优先,避免子串误匹配
    if not raw_names:
        return [dict(f) for f in files]

    # \.from\((['"])(?:habits|checkins)\1\)  —— 反向引用 \1 保证首尾引号一致
    alt = "|".join(re.escape(n) for n in raw_names)
    pattern = re.compile(rf'\.from\((["\'])({alt})\1\)')

    def repl(m: re.Match) -> str:
        quote, table = m.group(1), m.group(2)
        return f".from({quote}{app_id}_{table}{quote})"

    out: list[dict] = []
    for f in files:
        path = (f.get("path") or "").replace("\\", "/").lstrip("./")
        nf = dict(f)
        # supabase.ts 是刚注入的标准 client(createClient,无业务 .from)→ 跳过,免得误改
        if path == "src/lib/supabase.ts" or path.endswith("lib/supabase.ts"):
            out.append(nf)
            continue
        content = f.get("content")
        if isinstance(content, str):
            nf["content"] = pattern.sub(repl, content)
        out.append(nf)
    return out


# ────────────────────────────────────────────────────────────────
# inlined files 构造(state.files + 模板骨架 → Vercel [{file, data}])
# ────────────────────────────────────────────────────────────────

def _read_template_files() -> dict[str, str]:
    """读模板的 6 个项目骨架文件 + src/index.css(tailwind 三指令)→ {path: content}。"""
    out: dict[str, str] = {}
    for name in _TEMPLATE_FILES:
        p = TEMPLATE_DIR / name
        if p.exists():
            out[name] = p.read_text(encoding="utf-8")
    # src/index.css(tailwind base/components/utilities 三指令;Alex 没产时兜底)
    idx = TEMPLATE_DIR / "src" / "index.css"
    if idx.exists():
        out["src/index.css"] = idx.read_text(encoding="utf-8")
    return out


def build_vercel_files(files: list[dict]) -> list[dict]:
    """把 state.files + 模板骨架拼成 Vercel inlined files 列表:[{file, data}, ...]。

    合并语义:state.files 覆盖模板同路径(让 Alex 的 src/App.tsx 等生效)。
    路径规范化:去掉前导 "./" 和反斜杠(Vercel 期望 POSIX 相对路径)。
    """
    merged: dict[str, str] = {}
    # 先放模板骨架(允许被 state.files 覆盖)
    for path, content in _read_template_files().items():
        merged[path.replace("\\", "/").lstrip("./")] = content
    # 再放 state.files(index.css 例外:模板固定提供,Alex 若误产则忽略)
    for f in files:
        path = (f.get("path") or "").replace("\\", "/").lstrip("./")
        if not path:
            continue
        # index.css 是设计基线载体(@fontsource 字体 + tailwind 指令),由模板固定提供;
        # Alex 若误产 src/index.css 一律忽略,避免覆盖字体引入(此处与 validator._write_workspace 对齐)。
        if path == "src/index.css":
            continue
        merged[path] = f.get("content", "")
    # Vercel inlined files:[{file: <path>, data: <content string>}]
    return [{"file": p, "data": c} for p, c in merged.items()]


# ────────────────────────────────────────────────────────────────
# Vercel HTTP(stdlib urllib,绕过本机失效代理;绝不 log token)
# ────────────────────────────────────────────────────────────────

def _vercel_request(
    method: str,
    path: str,
    token: str,
    body: Any | None = None,
    timeout: int = _HTTP_TIMEOUT_CREATE,
) -> dict:
    """调 Vercel API,返回解析后的 JSON。

    - 用 ProxyHandler({}) 绕过本机失效 HTTP/SOCKS 代理(直连)
    - 错误体(urllib.HTTPError.e)可能含 Vercel 内部信息 → 异常消息只保留 code + 截断 body
    - **绝不**在异常或返回值里包含 Authorization header(token)
    """
    url = f"{VERCEL_API}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        method=method,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": _USER_AGENT,
        },
    )
    # ProxyHandler({}) = 不读环境代理,直连 api.vercel.com(本机失效代理兜底)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        # Vercel 错误体可能含 debug 信息,截断 200 字符;**不含 token**(token 只在请求 header)
        snippet = (e.read().decode("utf-8", errors="replace") or "")[:200]
        raise VercelAPIError(f"HTTP {e.code} {e.reason} | body: {snippet}") from None
    except urllib.error.URLError as e:
        raise VercelAPIError(f"网络错误:{e.reason}") from None


class VercelAPIError(Exception):
    """Vercel API 调用失败的友好错误(不含 token)。"""


# ────────────────────────────────────────────────────────────────
# 部署 + 轮询(纯函数,可单测)
# ────────────────────────────────────────────────────────────────

def create_deployment(
    files: list[dict],
    token: str,
    project_name: str | None = None,
    target: str | None = "production",
) -> dict:
    """POST /v13/deployments,返回 Vercel 响应(含 id / url / readyState)。

    files 是**注入 supabase 配置后**的完整 src 文件列表(本函数内部拼模板骨架)。
    project_name 不给则随机生成(atoms-app-<6 hex>)。
    """
    vercel_files = build_vercel_files(files)
    name = project_name or f"{_PROJECT_PREFIX}-{secrets.token_hex(3)}"
    body = {
        "name": name,
        "files": vercel_files,
        "projectSettings": {
            "framework": "vite",
            "buildCommand": "npm run build",
            "installCommand": "npm install",
            "outputDirectory": "dist",
        },
        # target="production":URL 更整洁(project.vercel.app);新项目首次部署自动建项目。
        "target": target,
    }
    return _vercel_request("POST", "/v13/deployments", token, body=body, timeout=_HTTP_TIMEOUT_CREATE)


def _normalize_url(url: str | None) -> str | None:
    """Vercel url 字段是 'xxx.vercel.app'(不带 schema),补 https:// 前缀。"""
    if not url:
        return None
    return url if url.startswith("http") else f"https://{url}"


def _pick_best_url(resp: dict) -> str | None:
    """从 Vercel 部署响应里挑**公开可访问**的最佳 URL。

    背景:Vercel 账号若开启 Deployment Protection(SSO / Email Auth),部署特有的
    `url`(如 atoms-app-xxx-abc123.vercel.app)会被 302 拦截到 vercel.com/sso-api 要登录;
    而 **production alias**(`{name}.vercel.app`,如 atoms-app-xxx.vercel.app)不受 SSO 保护,
    公开可访问(HTTP 200)。所以优先用 production alias 作为分享 URL。

    优先级:
      1. `{name}.vercel.app`(production alias,公开;name 字段创建时就有)
      2. alias 中最短的一个(production alias 比 deployment-specific 短)
      3. url(deployment-specific,兜底,可能被 SSO 拦截)
    """
    name = resp.get("name")
    aliases = resp.get("alias") or []
    # 优先:用 name 构造 production alias(公开可访问)
    if name:
        return f"https://{name}.vercel.app"
    # 次选:alias 列表里最短的(production alias 无 deployment hash 后缀,最短)
    if aliases:
        shortest = min(aliases, key=len)
        return _normalize_url(shortest)
    # 兜底:deployment-specific url(可能被 SSO 保护)
    return _normalize_url(resp.get("url"))


def poll_deployment(
    dep_id: str,
    token: str,
    timeout: float = _POLL_TIMEOUT,
    interval: float = _POLL_INTERVAL,
    sleep=lambda s: time.sleep(s),  # 测试可注入假 sleep
) -> tuple[str, str | None]:
    """轮询 GET /v13/deployments/{id} 直到 readyState 终态或超时。

    返回 (status, url):
    - status: "ready" / "failed" / "building"(超时仍未终态)
    - url: 部署的 vercel.app URL(只有 ready 时保证有效;其他情况可能 None)
    """
    deadline = time.time() + timeout
    last_url: str | None = None
    last_resp: dict = {}
    while time.time() < deadline:
        try:
            r = _vercel_request("GET", f"/v13/deployments/{dep_id}", token, timeout=_HTTP_TIMEOUT_POLL)
        except VercelAPIError:
            # 临时网络抖动:等下一轮(不立刻失败,提高鲁棒性)
            sleep(interval)
            continue
        last_resp = r
        last_url = _pick_best_url(r)
        state = (r.get("readyState") or r.get("status") or "").upper()
        if state == "READY":
            return "ready", _pick_best_url(r)
        if state in ("ERROR", "CANCELED"):
            return "failed", _normalize_url(last_resp.get("url"))
        # QUEUED / INITIALIZING / BUILDING → 继续轮询
        sleep(interval)
    return "building", last_url


# ────────────────────────────────────────────────────────────────
# Supabase 动态建表(design.supabase_tables → CREATE TABLE + RLS,调 Management API)
# ────────────────────────────────────────────────────────────────

# 标识符白名单:表名/字段名只允许 小写字母/数字/下划线,首字符非数字。
# 防御 LLM 产出恶意标识符(DDL 走特权 PAT,注入会真删库)。
_IDENT_RE = re.compile(r"^[a-z_][a-z0-9_]*$")

# Postgres 类型白名单(supabase_tables.fields[].type 校验用)。覆盖 Architect 常用类型。
# 不在表里的类型 → ValueError(拒绝生成 SQL),避免 "uuid; drop table x; --" 这类注入。
_PG_TYPES = {
    "uuid", "text", "varchar", "char", "bpchar",
    "integer", "int", "int4", "bigint", "int8", "smallint", "int2",
    "boolean", "bool",
    "date", "time", "timetz", "timestamp", "timestamptz",
    "numeric", "decimal", "real", "float4", "double precision", "float8",
    "json", "jsonb",
    "interval",
    "bytea",
    "inet", "cidr", "macaddr",
}

# 外键白名单:"表名.字段名" 格式,各自符合标识符规则。
_FK_RE = re.compile(r"^[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*$")

# 项目 ref 白铭牌:URL path 组件(不进 SQL,所以比 _IDENT_RE 宽 —— 允许数字开头/连字符)。
# 拒绝路径穿越(../, /)、空格、反斜杠等。Supabase ref 形如 gkcofqevmhenwdlbqbog(20 位字母数字),
# 但 vanity 子域可能带连字符,一并放行。
_REF_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _check_ident(name: str, what: str) -> str:
    """校验标识符(表名/字段名)合规,原样返回;违例 → ValueError。"""
    if not name or not _IDENT_RE.match(name):
        raise ValueError(f"非法{what}标识符:{name!r}(只允许小写字母/数字/下划线,首字符非数字)")
    return name


def _project_ref_from_url(url: str) -> str:
    """从 https://{ref}.supabase.co 抽出项目 ref(Management API path 用)。"""
    if not url:
        raise ValueError("SUPABASE_URL 为空")
    # 取 host,去 schema,取第一个域名段
    host = url.replace("https://", "").replace("http://", "").split("/")[0]
    ref = host.split(".")[0]
    if not _REF_RE.match(ref):
        raise ValueError(f"从 SUPABASE_URL 解析 ref 失败:{url!r} → {ref!r}")
    return ref


def _render_fk(fk: str) -> str:
    """fk="users.id" → "references auth.users(id) on delete cascade";其他 → references T(c) on delete cascade。

    Supabase auth 用户表在 auth schema,所以 users.id 特判为 auth.users(id)(多租户业务表标配)。
    """
    if not _FK_RE.match(fk):
        raise ValueError(f"非法外键格式(应为 表.字段):{fk!r}")
    tbl, col = fk.split(".", 1)
    ref = "auth.users" if tbl == "users" else f"public.{tbl}"
    return f"references {ref}({col}) on delete cascade"


def _render_column(field: dict) -> str:
    """单字段 → 列定义 SQL 片段(无前导缩进)。

    约定(对齐 Architect prompt tools.py:_DESIGN_INSTRUCTION):
      - 主键统一 id(uuid)→ uuid primary key default gen_random_uuid()
      - 业务表都有 created_at(timestamptz)→ timestamptz not null default now()
      - user_id(uuid, fk users.id)→ uuid not null references auth.users(id) on delete cascade(多租户标识,RLS 依赖)
      - 其他外键:默认可空 + references(避免阻断应用基础 CRUD,如直接记食物不强制先选 recipe)
      - 其他字段:仅类型(可空)
    """
    name = _check_ident(field.get("name", ""), "字段名")
    ftype = str(field.get("type", "")).strip().lower()
    if ftype not in _PG_TYPES:
        raise ValueError(f"字段 {name!r} 的类型 {ftype!r} 不在 Postgres 白名单内")
    is_pk = bool(field.get("pk"))
    fk = field.get("fk")

    parts: list[str] = [name, ftype]

    # created_at 约定(Architect 业务表恒带)
    if name == "created_at" and ftype in ("timestamptz", "timestamp"):
        parts.append("not null default now()")
    # 主键 uuid → 默认值
    if is_pk and ftype == "uuid":
        parts.append("primary key default gen_random_uuid()")
    elif is_pk:
        parts.append("primary key")

    # 外键
    if fk:
        if is_pk:
            # 主键同时是外键(罕见):把 references 附在 primary key 后
            parts.append(_render_fk(fk))
        else:
            # user_id(多租户标识)必须 not null(RLS auth.uid()=user_id 依赖);
            # 其他业务外键默认可空,避免阻断应用交互(如直接记食物/打卡,不强制先选关联实体)
            if name == "user_id":
                parts.append("not null")
            parts.append(_render_fk(fk))

    return " ".join(parts)


def _policy_name(table: str, op: str) -> str:
    """构造 RLS 策略名 `{table}_{op}_own`,超 63 字符(Postgres 标识符上限)截断 table。"""
    suffix = f"_{op}_own"
    if len(table) + len(suffix) <= 63:
        return f"{table}{suffix}"
    keep = 63 - len(suffix)
    return f"{table[:keep]}{suffix}"


def _render_rls(table: str, has_user_id: bool) -> str:
    """表的 RLS 段落:ENABLE RLS + (有 user_id 时)4 条 auth.uid()=user_id 策略(幂等)。

    无 user_id 的表(如 lookup 表)→ 仅 CREATE TABLE,不加 RLS(RLS 无策略=全锁,会让应用读不到,
    与其锁死不如先不开;多租户隔离针对带 user_id 的业务表)。
    """
    if not has_user_id:
        return ""  # 不开 RLS(见上注释)
    p = lambda op: _policy_name(table, op)  # noqa: E731
    return f"""
alter table public.{table} enable row level security;

-- 策略幂等:先 drop 再 create(重复部署不报错)
drop policy if exists "{p('select')}" on public.{table};
drop policy if exists "{p('insert')}" on public.{table};
drop policy if exists "{p('update')}" on public.{table};
drop policy if exists "{p('delete')}" on public.{table};

create policy "{p('select')}" on public.{table}
  for select to authenticated using (auth.uid() = user_id);
create policy "{p('insert')}" on public.{table}
  for insert to authenticated with check (auth.uid() = user_id);
create policy "{p('update')}" on public.{table}
  for update to authenticated using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "{p('delete')}" on public.{table}
  for delete to authenticated using (auth.uid() = user_id);
"""


def _check_app_id(app_id: str) -> str:
    """校验 app_id 前缀合规(进 SQL 表名 + 注入应用代码,防注入),原样返回;空串合法(向后兼容)。"""
    if not app_id:
        return ""
    if not _IDENT_RE.match(app_id):
        raise ValueError(f"非法 app_id 前缀:{app_id!r}(只允许小写字母/数字/下划线,首字符非数字)")
    if len(app_id) > _APP_ID_MAXLEN:
        raise ValueError(f"app_id 前缀过长:{app_id!r}(上限 {_APP_ID_MAXLEN} 字符)")
    return app_id


def generate_create_table_sql(tables: list[dict], app_id: str = "") -> str:
    """design.supabase_tables → 完整 CREATE TABLE IF NOT EXISTS + RLS SQL(幂等,可重复执行)。

    纯函数,可单测,不触网。任何字段/类型/外键不合规 → ValueError(整个 SQL 不输出,避免半截建表)。

    tables: [{"name": "habits", "fields": [{"name","type","pk?","fk?"}, ...]}, ...]
    app_id: 多租户前缀(如 "app_34f04b",见 _app_id_from_project_name)。给定时:
      - 表名加前缀:`habits` → `app_34f04b_habits`
      - 业务外键引用加前缀:`fk="habits.id"` → `references public.app_34f04b_habits(id)`(users.id 不动)
      - RLS policy 名随之带前缀(基于带前缀表名构造,自动唯一)
      每 app 独立表,永不冲突。空串 → 不加前缀(向后兼容,多 app 会冲突)。
    返回:可一次性喂给 Supabase /database/query 的多语句 SQL 字符串。
    """
    if not tables:
        return ""  # 无表(design 没产或 landing 类)→ 空 SQL,调用方应短路

    _check_app_id(app_id)

    # 先全量校验(任何一处非法 → 整体 raise,不产出半截 SQL)
    for t in tables:
        _check_ident(t.get("name", ""), "表名")
        if not t.get("fields"):
            raise ValueError(f"表 {t.get('name')!r} 无字段")
        for f in t["fields"]:
            _render_column(f)  # raise 即终止

    # 多租户前缀:把表名 + 业务外键引用加 app_id 前缀(normalize 出新数据,下游 _render_* 不变)。
    # users.id 是 Supabase 内置 auth 表,不加前缀;业务表相互引用(habits.id 等)需加前缀,
    # 否则 checkins 的 habit_id 外键会指向不存在的 public.habits(已被前缀表替代)→ 建表失败。
    biz_tables = {t["name"] for t in tables}

    def pref(name: str) -> str:
        return f"{app_id}_{name}" if app_id else name

    norm_tables: list[dict] = []
    for t in tables:
        norm_fields = []
        for f in t["fields"]:
            nf = dict(f)
            fk = nf.get("fk")
            if fk:
                tbl, col = fk.split(".", 1)
                # 业务表外键 → 引用加前缀的同 app 表;users.id(auth 表)原样保留
                nf["fk"] = f"{pref(tbl)}.{col}" if tbl in biz_tables else fk
            norm_fields.append(nf)
        norm_tables.append({**t, "name": pref(t["name"]), "fields": norm_fields})

    blocks: list[str] = []
    for t in norm_tables:
        name = t["name"]
        cols = [f"  {_render_column(f)}" for f in t["fields"]]
        has_user_id = any(f.get("name") == "user_id" for f in t["fields"])
        ddl = (
            f"\n-- 表 {name}\n"
            f"create table if not exists public.{name} (\n"
            + ",\n".join(cols)
            + "\n);"
        )
        rls = _render_rls(name, has_user_id)
        blocks.append(ddl + (rls if rls else ""))

    return "\n".join(blocks) + "\n"


class SupabaseAPIError(Exception):
    """Supabase Management API 调用失败的友好错误(不含 token)。"""


def _supabase_request(
    path: str,
    body: dict | None,
    access_token: str,
    timeout: int = _HTTP_TIMEOUT_DDL,
) -> dict:
    """调 Supabase Management API,返回解析后的 JSON。

    - Bearer = Personal Access Token(**不是** service_role;见模块 docstring)
    - ProxyHandler({}) 绕本机失效代理;**必带 User-Agent**(Cloudflare 拦 Python-urllib)
    - 错误体可能含 debug 信息 → 截断 200 字符;**不含 token**(token 只在请求 header)
    """
    url = f"{SUPABASE_MGMT_API}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        method="POST",
        data=data,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "User-Agent": _USER_AGENT,
        },
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        snippet = (e.read().decode("utf-8", errors="replace") or "")[:200]
        raise SupabaseAPIError(f"HTTP {e.code} {e.reason} | body: {snippet}") from None
    except urllib.error.URLError as e:
        raise SupabaseAPIError(f"网络错误:{e.reason}") from None


def create_supabase_tables(
    tables: list[dict], access_token: str, project_ref: str, app_id: str = ""
) -> dict:
    """生成 SQL + 调 Management API /database/query 建表。

    app_id: 多租户前缀(空串 → 旧无前缀行为);透传给 generate_create_table_sql。
    返回结果摘要(进 ToolMessage 用,**不含 token**):
      {"status": "ok"|"empty", "tables": ["habits","checkins"], "sql_chars": N}
    失败 → raise SupabaseAPIError(调用方决定是否阻塞)。
    """
    sql = generate_create_table_sql(tables, app_id=app_id)
    if not sql:
        return {"status": "empty", "tables": [], "sql_chars": 0}
    body = {"query": sql, "read_only": False}
    # 201 = 查询执行成功(Management API 文档约定)
    _supabase_request(
        f"/v1/projects/{project_ref}/database/query", body, access_token
    )
    return {
        "status": "ok",
        "tables": [t.get("name", "?") for t in tables],
        "sql_chars": len(sql),
    }


def _try_create_supabase_tables(
    design: dict | None, app_id: str = ""
) -> dict:
    """deploy_app 调:读 design.supabase_tables → 建表(表名带 app_id 前缀)。**永远不抛**(非阻塞)。

    app_id: 多租户前缀(空串 → 旧无前缀行为,多 app 会冲突——不推荐)。
    返回可进 ToolMessage 的状态 dict:
      {"level": "ok"|"warn"|"skip", "msg": "...", "tables": [...]}
    - 缺 access_token / 缺 design / 无表 → skip(部署照常进行)
    - SQL 生成或 API 调用失败 → warn(部署照常进行,明告用户表没建好)
    - 成功 → ok(消息里列已建表)
    **绝不**把 token / 完整 SQL(可能含细节)回显,只回显表名 + 状态。
    """
    access_token = settings.supabase_access_token
    if not access_token:
        return {"level": "skip", "msg": "未配 SUPABASE_ACCESS_TOKEN(PAT),跳过自动建表", "tables": []}
    if not design:
        return {"level": "skip", "msg": "state.design 为空(Architect 未产),跳过建表", "tables": []}
    tables = design.get("supabase_tables") or []
    if not tables:
        return {"level": "skip", "msg": "design.supabase_tables 为空(无业务表),跳过建表", "tables": []}
    try:
        ref = _project_ref_from_url(settings.supabase_url)
    except ValueError as e:
        return {"level": "warn", "msg": f"解析 Supabase 项目 ref 失败:{e}", "tables": []}
    try:
        res = create_supabase_tables(tables, access_token, ref, app_id=app_id)
    except SupabaseAPIError as e:
        return {"level": "warn", "msg": f"Supabase 建表 API 失败({e})", "tables": []}
    except ValueError as e:
        # SQL 生成阶段(标识符/类型/app_id 校验)失败 —— design 产出不合规
        return {"level": "warn", "msg": f"design.supabase_tables 不合规,建表 SQL 未生成:{e}", "tables": []}
    return {
        "level": "ok",
        "msg": f"已建 {len(res['tables'])} 张表({', '.join(res['tables'])})",
        "tables": res["tables"],
    }


def _format_ddl_note(ddl: dict) -> str:
    """把建表状态 dict 渲染成 ToolMessage 里的一段提示(非阻塞说明)。"""
    level = ddl.get("level", "skip")
    msg = ddl.get("msg", "")
    if level == "ok":
        return f"✅ Supabase 动态建表:{msg}(RLS auth.uid()=user_id 已加)。"
    if level == "warn":
        return (
            f"⚠️ Supabase 动态建表未完成:{msg}。\n"
            "    部署的应用站点可访问,但登录后 CRUD 会因表不存在而失败。"
            "可补配 SUPABASE_ACCESS_TOKEN(PAT)后重新 deploy_app,或在 Supabase Dashboard SQL Editor 手动建表。"
        )
    # skip
    return f"⏭  Supabase 动态建表:{msg}(部署照常进行)。"


# ────────────────────────────────────────────────────────────────
# deploy_app tool(create_agent 第 6 个 tool,Validator 之后用户触发)
# ────────────────────────────────────────────────────────────────

def _missing_config() -> str | None:
    """检查部署必要配置,返回缺失提示(None 表示齐全)。"""
    if not settings.vercel_token:
        return "VERCEL_TOKEN"
    if not settings.supabase_url or not settings.supabase_anon_key:
        return "SUPABASE_URL / SUPABASE_ANON_KEY"
    return None


@tool
def deploy_app(
    state: Annotated[dict, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """把已生成的代码(state.files + 项目模板)部署到 Vercel,产出真站点 xxx.vercel.app URL。

    调用前提:write_code + validate_build 已完成(build_status="passed")。
    本工具会:
    1. **动态建表(非阻塞)**:读 state.design.supabase_tables → 调 Supabase Management API 建
       CREATE TABLE + RLS。失败/缺 PAT → 仅在返回消息提示,不阻塞部署。
    2. 注入真实 Supabase 配置(覆盖 src/lib/supabase.ts),让部署的应用能真登录/CRUD。
    3. POST /v13/deployments(inlined files,免 git)→ 拿到 deployment id + 临时 URL。
    4. 轮询构建状态(最长 90s,见 _POLL_TIMEOUT)→ READY 时返回最终 URL。

    成功 → state.deploy_status="ready" + state.deployment_url=vercel.app URL。
    失败 → state.deploy_status="failed"(Vercel build error / 配置缺失 / 网络异常)。
    超时 → state.deploy_status="building" + state.deployment_url(用户可稍后访问)。

    何时调用:用户明确要求"部署/上线/发布"时(validate_build 已通过)。不要在 build 未通过时调用。
    """
    files = state.get("files") or []
    if not files:
        return Command(update={"deploy_status": "failed", "messages": [ToolMessage(
            content="没有可部署的代码(state.files 为空)。请先完成 write_code + validate_build(build_status=passed)后再部署。",
            tool_call_id=tool_call_id,
        )]})

    # 配置缺失是运维问题,不耗部署次数,直接明告 agent/用户
    missing = _missing_config()
    if missing:
        return Command(update={"deploy_status": "failed", "messages": [ToolMessage(
            content=(
                f"⚠️ 后端 .env 未配置 {missing},无法部署到 Vercel。\n"
                "这不是代码问题 —— state.files 本身正确,无需重写。请运维在 backend/.env 补配 VERCEL_TOKEN + SUPABASE_URL + SUPABASE_ANON_KEY 后重试。"
            ),
            tool_call_id=tool_call_id,
        )]})

    # 多租户隔离 + 固定链接:project_name 基于 thread_id(稳定)→ 同一会话重复部署复用同一 vercel
    # URL(https://atoms-app-{tid}.vercel.app);app_id 同源 → 表前缀稳定 → 数据连续(不会每次部署
    # 新建一套表)。project_name 同源生成 app_id,保证"建表用的前缀"与"注入应用代码用的前缀"一致
    # (不一致 → 应用 .from('habits') 查无此表 → PostgREST 400)。
    # thread_id 由 main.py merge_state 注入 state(InjectedConfig 本 langgraph 版本不存在)。
    _tid_hex = str(state.get("thread_id") or "").replace("-", "")
    suffix = _tid_hex[:10] or secrets.token_hex(3)  # thread_id 兜底(空则随机,理论不发生)
    project_name = f"{_PROJECT_PREFIX}-{suffix}"
    app_id = _app_id_from_project_name(project_name)
    design = state.get("design") or {}
    tables = design.get("supabase_tables") or []

    # 0) 动态建表(非阻塞,带 app_id 前缀):design.supabase_tables → Supabase Management API。失败仅记 note。
    ddl_result = _try_create_supabase_tables(design, app_id=app_id)
    ddl_note = _format_ddl_note(ddl_result)

    # 1) 注入 Supabase 配置(覆盖 src/lib/supabase.ts)
    files_with_supabase = inject_supabase_config(
        files, settings.supabase_url, settings.supabase_anon_key
    )

    # 1.5) 注入表名前缀(关键):.from('habits') → .from('{app_id}_habits'),
    # 让应用代码访问的前缀表与第 0 步建的表一致(多租户隔离)。
    files_prefixed = inject_table_prefix(files_with_supabase, tables, app_id)

    # 2) 创建部署(用同源 project_name,Vercel URL 与 app_id 共用 hex 后缀)
    try:
        resp = create_deployment(files_prefixed, settings.vercel_token, project_name=project_name)
    except VercelAPIError as e:
        return Command(update={"deploy_status": "failed", "messages": [ToolMessage(
            content=(
                f"❌ 创建 Vercel 部署失败({e})。\n请稍后重试 deploy_app;若持续失败,检查 VERCEL_TOKEN 是否有效/有额度。\n\n"
                f"{ddl_note}"
            ),
            tool_call_id=tool_call_id,
        )]})

    dep_id = resp.get("id")
    init_url = _pick_best_url(resp)
    if not dep_id or not init_url:
        # Vercel 响应异常(理论不应发生):把去敏的响应 key 给 agent 诊断
        diag = {k: v for k, v in resp.items() if k in ("id", "url", "readyState", "status", "error", "name", "alias")}
        return Command(update={"deploy_status": "failed", "messages": [ToolMessage(
            content=f"❌ Vercel 响应异常,缺 id 或 url。诊断(去敏):{json.dumps(diag, ensure_ascii=False)[:300]}",
            tool_call_id=tool_call_id,
        )]})

    # 3) 轮询构建状态
    final_status, final_url = poll_deployment(dep_id, settings.vercel_token)

    if final_status == "ready":
        url = final_url or init_url
        return Command(update={
            "deployment_url": url,
            "deploy_status": "ready",
            "messages": [ToolMessage(
                content=(
                    f"✅ 部署成功!真站点 URL(可在新标签打开,真 Supabase 注册/登录/CRUD 已就绪):\n{url}\n\n"
                    f"{ddl_note}"
                ),
                tool_call_id=tool_call_id,
            )],
        })

    if final_status == "failed":
        return Command(update={
            "deployment_url": init_url,
            "deploy_status": "failed",
            "messages": [ToolMessage(
                content=(
                    f"❌ Vercel 部署失败(build error)。临时 URL:{init_url}\n"
                    "请到 Vercel 控制台查看该 deployment 的 Build Logs 定位原因(常见:依赖缺失、Supabase import 路径错)。修复后重新调用 deploy_app。\n\n"
                    f"{ddl_note}"
                ),
                tool_call_id=tool_call_id,
            )],
        })

    # 超时(仍 BUILDING):不阻塞 SSE,返回 building + URL,用户可稍后访问
    return Command(update={
        "deployment_url": init_url,
        "deploy_status": "building",
        "messages": [ToolMessage(
            content=(
                f"⏳ 部署已提交,Vercel 仍在构建中(>{int(_POLL_TIMEOUT)}s 未完成)。\n"
                f"临时 URL:{init_url}\n"
                "稍后(1-2 分钟)直接访问该 URL;或到 Vercel 控制台看构建进度。state.deploy_status 当前为 'building'。\n\n"
                f"{ddl_note}"
            ),
            tool_call_id=tool_call_id,
        )],
    })


# `python -m app.deploy`:配置自检(不真部署,避免烧配额)
if __name__ == "__main__":
    missing = _missing_config()
    if missing:
        raise SystemExit(f"❌ backend/.env 未配置 {missing},部署不可用。")
    print("✅ 部署配置就绪:VERCEL_TOKEN + SUPABASE_URL + SUPABASE_ANON_KEY 已读入。")
    print(f"   SUPABASE_URL = {settings.supabase_url}")
    ref = _project_ref_from_url(settings.supabase_url)
    print(f"   Supabase 项目 ref = {ref}")
    print(f"   SUPABASE_ACCESS_TOKEN(PAT)={'已配(' + str(len(settings.supabase_access_token)) + ' 字符)' if settings.supabase_access_token else '⚠️ 未配 → 动态建表会 skip,需手抄 SQL'}")
    # PAT 是 sbp_...,service_role 是 JWT(eyJ...)—— 自检提醒别填错
    if settings.supabase_access_token and not settings.supabase_access_token.startswith("sbp_"):
        print(f"   ⚠️ SUPABASE_ACCESS_TOKEN 不以 sbp_ 开头(疑似填成 service_role/anon),动态建表大概率 401")
    print(f"   模板目录:{TEMPLATE_DIR}")
    print(f"   模板骨架文件:{_TEMPLATE_FILES}")
    # 验证 _read_template_files + build_vercel_files 能跑(用一个最小 state.files)
    sample = [{"path": "src/App.tsx", "content": "export default function App(){return <div>hi</div>}"}]
    injected = inject_supabase_config(sample, settings.supabase_url, settings.supabase_anon_key)
    vf = build_vercel_files(injected)
    print(f"   inlined files 数:{len(vf)}(模板骨架 + src/*)")
    paths = [f["file"] for f in vf]
    assert any(p == "src/lib/supabase.ts" for p in paths), "supabase.ts 注入失败"
    assert any("SUPABASE_URL" in (f["data"] if p == "src/lib/supabase.ts" else "") or
               settings.supabase_url in (f["data"] if p == "src/lib/supabase.ts" else "")
               for p, f in zip(paths, vf)), "supabase.ts 未含真实 SUPABASE_URL"
    print("   ✅ supabase.ts 注入自检通过(含真实 SUPABASE_URL)")
    # 动态建表 SQL 生成自检(habits + checkins 示例,覆盖 PK/FK/created_at/RLS 全部约定)
    demo_tables = [
        {"name": "habits", "fields": [
            {"name": "id", "type": "uuid", "pk": True},
            {"name": "user_id", "type": "uuid", "fk": "users.id"},
            {"name": "name", "type": "text"},
            {"name": "created_at", "type": "timestamptz"},
        ]},
        {"name": "checkins", "fields": [
            {"name": "id", "type": "uuid", "pk": True},
            {"name": "habit_id", "type": "uuid", "fk": "habits.id"},
            {"name": "user_id", "type": "uuid", "fk": "users.id"},
            {"name": "created_at", "type": "timestamptz"},
        ]},
    ]
    sql = generate_create_table_sql(demo_tables)
    assert "create table if not exists public.habits" in sql
    assert "primary key default gen_random_uuid()" in sql, "uuid 主键应带 gen_random_uuid()"
    assert "references auth.users(id) on delete cascade" in sql, "users.id 应特判为 auth.users(id)"
    assert "references public.habits(id) on delete cascade" in sql, "业务外键应 references public.表"
    assert "created_at timestamptz not null default now()" in sql, "created_at 应带 default now()"
    assert "enable row level security" in sql and "auth.uid() = user_id" in sql, "RLS 策略应生成"
    assert "create policy" in sql and "drop policy if exists" in sql, "策略应幂等(drop+create)"
    print(f"   ✅ 动态建表 SQL 生成自检通过(habits/checkins,{len(sql)} 字符,含 PK/FK/created_at/RLS)")
    # 多租户 app_id 前缀自检:同一 design + 不同 app_id → 独立表(不共用 habits)
    aid_a = _app_id_from_project_name("atoms-app-34f04b")
    aid_b = _app_id_from_project_name("atoms-app-8ea1a9")
    assert aid_a == "app_34f04b" and aid_b == "app_8ea1a9", f"app_id 抽取错:{aid_a}/{aid_b}"
    sql_a = generate_create_table_sql(demo_tables, app_id=aid_a)
    sql_b = generate_create_table_sql(demo_tables, app_id=aid_b)
    assert "create table if not exists public.app_34f04b_habits" in sql_a, "app A 应有前缀表"
    assert "create table if not exists public.app_8ea1a9_habits" in sql_b, "app B 应有独立前缀表"
    assert "references public.app_34f04b_habits(id) on delete cascade" in sql_a, "业务外键应带前缀"
    assert "references auth.users(id) on delete cascade" in sql_a, "users.id 仍特判为 auth.users(不加前缀)"
    # inject_table_prefix:.from('habits') → .from('app_34f04b_habits')
    demo_files = [{"path": "src/api.ts", "content": "const x = await supabase.from('habits').select()\nconst y = await supabase.from('checkins').select()"}]
    inj = inject_table_prefix(demo_files, demo_tables, aid_a)
    c = inj[0]["content"]
    assert "from('app_34f04b_habits')" in c and "from('app_34f04b_checkins')" in c, f"from() 应带前缀:{c}"
    assert "from('habits')" not in c, "裸 from('habits') 应已被替换"
    print(f"   ✅ 多租户 app_id 前缀自检通过(app_34f04b_habits / app_8ea1a9_habits 独立;inject 替换正确)")
