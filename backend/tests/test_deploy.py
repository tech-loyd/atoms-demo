"""deploy_app 单元测试(不调真 Vercel API,秒级)。

覆盖:
- inject_supabase_config:覆盖已有 / 追加缺失 / 处理路径变体
- build_vercel_files:模板骨架 + state.files 合并、路径规范化、inlined 输出 shape
- poll_deployment:READY/ERROR/CANCELED/超时(用假 sleep + mock _vercel_request)
- deploy_app tool:无 files / 缺 VERCEL_TOKEN / 创建失败 / ready / failed / building(超时)

不调 LLM,不调真 Vercel API(全程 mock _vercel_request),~1s 跑完。

用法:
    cd backend && source .venv/bin/activate
    env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy -u ALL_PROXY -u all_proxy \\
        python tests/test_deploy.py
"""
from __future__ import annotations

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import deploy as deploy_mod  # noqa: E402
from app.deploy import (  # noqa: E402
    SupabaseAPIError,
    VercelAPIError,
    _app_id_from_project_name,
    _pick_best_url,
    build_vercel_files,
    create_supabase_tables,
    deploy_app,
    generate_create_table_sql,
    inject_supabase_config,
    inject_table_prefix,
    poll_deployment,
)


SUPABASE_URL = "https://gkcofqevmhenwdlbqbog.supabase.co"
SUPABASE_ANON_KEY = "eyJtest.test.test"


# ────────────────────────────────────────────────────────────────
# inject_supabase_config
# ────────────────────────────────────────────────────────────────

def test_inject_overrides_existing_supabase_ts():
    """Alex 已产 src/lib/supabase.ts(占位)→ 覆盖为真实配置模板。"""
    files = [
        {"path": "src/App.tsx", "content": "export default () => null", "language": "tsx"},
        {"path": "src/lib/supabase.ts", "content": "createClient('https://YOUR-PROJECT.supabase.co', 'YOUR_KEY')", "language": "typescript"},
    ]
    out = inject_supabase_config(files, SUPABASE_URL, SUPABASE_ANON_KEY)
    sb = next(f for f in out if f["path"] == "src/lib/supabase.ts")
    assert SUPABASE_URL in sb["content"], "supabase.ts 应含真实 URL"
    assert SUPABASE_ANON_KEY in sb["content"], "supabase.ts 应含真实 anon key"
    assert "YOUR-PROJECT" not in sb["content"], "占位 URL 应被替换掉"
    assert "export const supabase" in sb["content"]
    # 其他文件不动
    app = next(f for f in out if f["path"] == "src/App.tsx")
    assert app["content"] == "export default () => null"
    print("✅ test_inject_overrides_existing_supabase_ts 通过")


def test_inject_appends_when_missing():
    """Alex 没产 supabase.ts → 追加一个。"""
    files = [{"path": "src/App.tsx", "content": "x", "language": "tsx"}]
    out = inject_supabase_config(files, SUPABASE_URL, SUPABASE_ANON_KEY)
    assert any(f["path"] == "src/lib/supabase.ts" for f in out), "应追加 supabase.ts"
    print("✅ test_inject_appends_when_missing 通过")


def test_inject_handles_path_variants():
    """路径变体(反斜杠 / 前导 ./ / 不同前缀)也能识别并标准化为 src/lib/supabase.ts。"""
    for variant in ["src/lib/supabase.ts", "./src/lib/supabase.ts",
                    "src\\lib\\supabase.ts", "lib/supabase.ts"]:
        files = [{"path": variant, "content": "placeholder", "language": "typescript"}]
        out = inject_supabase_config(files, SUPABASE_URL, SUPABASE_ANON_KEY)
        paths = [f["path"] for f in out]
        assert paths.count("src/lib/supabase.ts") == 1, f"路径变体 {variant!r} 应被标准化且唯一"
    print("✅ test_inject_handles_path_variants 通过")


def test_inject_no_service_role():
    """注入内容绝不包含 service_role key 的赋值(只 public anon key)。

    检查 createClient 第二参数是 SUPABASE_ANON_KEY 字面量,且无 SUPABASE_SERVICE_ROLE
    这类危险变量。注释里提到"无 service_role"(说明意图)是允许的,不算泄露。
    """
    out = inject_supabase_config([], SUPABASE_URL, SUPABASE_ANON_KEY)
    sb = next(f for f in out if f["path"] == "src/lib/supabase.ts")
    # 不应有 service_role 的变量赋值 / env 引用
    assert "SUPABASE_SERVICE_ROLE" not in sb["content"]
    assert "serviceRoleKey" not in sb["content"]
    assert "'service_role'" not in sb["content"]
    assert '"service_role"' not in sb["content"]
    # createClient 的第二参数就是 anon key 字面量(已注入真实值)
    assert SUPABASE_ANON_KEY in sb["content"]
    # 只有一个 createClient 调用,且第二行(参数 2)是 anon key
    assert sb["content"].count("createClient(") == 1
    print("✅ test_inject_no_service_role 通过")


# ────────────────────────────────────────────────────────────────
# build_vercel_files
# ────────────────────────────────────────────────────────────────

def test_build_vercel_files_merges_template_and_state():
    """模板骨架(package.json/vite.config 等)+ state.files 合并,state.files 覆盖同路径。"""
    files = [
        {"path": "src/App.tsx", "content": "ALEX_APP", "language": "tsx"},
        {"path": "src/main.tsx", "content": "ALEX_MAIN", "language": "tsx"},
    ]
    vf = build_vercel_files(files)
    paths = [f["file"] for f in vf]
    # 模板骨架
    assert "package.json" in paths
    assert "vite.config.ts" in paths
    assert "tsconfig.json" in paths
    assert "index.html" in paths
    assert "src/index.css" in paths  # tailwind 三指令兜底
    # state.files
    assert "src/App.tsx" in paths
    assert "src/main.tsx" in paths
    # state.files 覆盖模板同路径(模板的 src/App.tsx 占位应被 Alex 的覆盖)
    app_data = next(f["data"] for f in vf if f["file"] == "src/App.tsx")
    assert app_data == "ALEX_APP"
    # inlined shape:[{file, data}]
    assert all(set(f.keys()) == {"file", "data"} for f in vf)
    print("✅ test_build_vercel_files_merges_template_and_state 通过")


def test_build_vercel_files_normalizes_paths():
    """前导 ./ 和反斜杠路径被规范化为 POSIX 相对路径。"""
    files = [
        {"path": "./src/App.tsx", "content": "x"},
        {"path": "src\\lib\\x.ts", "content": "y"},
    ]
    vf = build_vercel_files(files)
    paths = [f["file"] for f in vf]
    assert "src/App.tsx" in paths, "./ 前缀应去掉"
    assert "src/lib/x.ts" in paths, "反斜杠应收成 /"
    print("✅ test_build_vercel_files_normalizes_paths 通过")


# ────────────────────────────────────────────────────────────────
# _pick_best_url(优先 production alias,避开 SSO 拦截)
# ────────────────────────────────────────────────────────────────

def test_pick_best_url_prefers_name_alias():
    """有 name 字段 → 优先返回 {name}.vercel.app(production alias,公开可访问)。"""
    resp = {
        "name": "atoms-app-abc",
        "url": "atoms-app-abc-xyz123.vercel.app",  # deployment-specific(被 SSO 保护)
        "alias": ["atoms-app-abc.vercel.app", "atoms-app-abc-xyz123.vercel.app"],
    }
    url = _pick_best_url(resp)
    assert url == "https://atoms-app-abc.vercel.app", "应用 production alias,不用 deployment-specific"
    print("✅ test_pick_best_url_prefers_name_alias 通过")


def test_pick_best_url_falls_back_to_alias():
    """无 name → alias 里最短(production alias 比 deployment-specific 短)。"""
    resp = {"alias": ["atoms-x.vercel.app", "atoms-x-abc123.vercel.app"]}
    url = _pick_best_url(resp)
    assert url == "https://atoms-x.vercel.app"
    print("✅ test_pick_best_url_falls_back_to_alias 通过")


def test_pick_best_url_falls_back_to_url():
    """无 name 无 alias → url 字段(可能被 SSO 保护,但兜底)。"""
    resp = {"url": "fallback.vercel.app"}
    url = _pick_best_url(resp)
    assert url == "https://fallback.vercel.app"
    print("✅ test_pick_best_url_falls_back_to_url 通过")


# ────────────────────────────────────────────────────────────────
# poll_deployment(用假 sleep + mock _vercel_request)
# ────────────────────────────────────────────────────────────────

class _FakeTime:
    """可控时钟(让 poll_deployment 不真等)。"""
    def __init__(self):
        self.t = 0.0
    def time(self):
        return self.t
    def advance(self, dt):
        self.t += dt


def _patch_time(monkey):
    """patch deploy_mod.time + 默认 sleep,让轮询受控。"""
    fake = _FakeTime()
    monkey.time = fake.time  # deploy_mod.time.time → fake.time(经下面 setattr)
    deploy_mod.time.time = fake.time
    sleeps = []
    def fake_sleep(s):
        fake.advance(s)
        sleeps.append(s)
    return fake, fake_sleep, sleeps


def test_poll_returns_ready(monkeypatch):
    """readyState=READY → 立即返回 ('ready', url)。"""
    fake, fake_sleep, sleeps = _patch_time(deploy_mod.time)
    monkeypatch.setattr(deploy_mod, "_vercel_request", lambda *a, **kw: {
        "readyState": "BUILDING" if fake.t < 6 else "READY",
        "url": "atoms-app-xyz.vercel.app",
    })
    status, url = poll_deployment("dpl_test", "fake-token", timeout=60, interval=3, sleep=fake_sleep)
    assert status == "ready"
    assert url == "https://atoms-app-xyz.vercel.app", "url 应补 https:// 前缀"
    print("✅ test_poll_returns_ready 通过")


def test_poll_returns_failed_on_error(monkeypatch):
    """readyState=ERROR → 返回 ('failed', url)。"""
    fake, fake_sleep, _ = _patch_time(deploy_mod.time)
    monkeypatch.setattr(deploy_mod, "_vercel_request", lambda *a, **kw: {
        "readyState": "ERROR", "url": "atoms-app-fail.vercel.app",
    })
    status, url = poll_deployment("dpl", "tok", timeout=30, interval=2, sleep=fake_sleep)
    assert status == "failed"
    assert url == "https://atoms-app-fail.vercel.app"
    print("✅ test_poll_returns_failed_on_error 通过")


def test_poll_returns_failed_on_canceled(monkeypatch):
    """readyState=CANCELED → 也视为 failed。"""
    _, fake_sleep, _ = _patch_time(deploy_mod.time)
    monkeypatch.setattr(deploy_mod, "_vercel_request", lambda *a, **kw: {
        "readyState": "CANCELED", "url": None,
    })
    status, url = poll_deployment("dpl", "tok", timeout=10, interval=1, sleep=fake_sleep)
    assert status == "failed"
    assert url is None
    print("✅ test_poll_returns_failed_on_canceled 通过")


def test_poll_timeout_returns_building(monkeypatch):
    """一直 BUILDING 直到超时 → 返回 ('building', url)。"""
    fake, fake_sleep, _ = _patch_time(deploy_mod.time)
    monkeypatch.setattr(deploy_mod, "_vercel_request", lambda *a, **kw: {
        "readyState": "BUILDING", "url": "atoms-app-slow.vercel.app",
    })
    status, url = poll_deployment("dpl", "tok", timeout=12, interval=3, sleep=fake_sleep)
    assert status == "building", "超时应返回 building"
    assert url == "https://atoms-app-slow.vercel.app"
    print("✅ test_poll_timeout_returns_building 通过")


def test_poll_tolerates_transient_network_error(monkeypatch):
    """中间一次网络错误(VercelAPIError)不立刻失败,下一轮继续。"""
    fake, fake_sleep, _ = _patch_time(deploy_mod.time)
    calls = {"n": 0}
    def fake_req(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise VercelAPIError("transient 502")
        return {"readyState": "READY", "url": "atoms-app.vercel.app"}
    monkeypatch.setattr(deploy_mod, "_vercel_request", fake_req)
    status, url = poll_deployment("dpl", "tok", timeout=30, interval=2, sleep=fake_sleep)
    assert status == "ready"
    assert calls["n"] >= 2, "应在首次失败后继续轮询"
    print("✅ test_poll_tolerates_transient_network_error 通过")


# ────────────────────────────────────────────────────────────────
# deploy_app tool(用 monkeypatch settings + mock Vercel API)
# ────────────────────────────────────────────────────────────────

def _make_state(files=None):
    return {"files": files or [], "iter_count": 0}


def test_deploy_no_files_returns_failed_message():
    cmd = deploy_app.func(state=_make_state(None), tool_call_id="tc-1")
    upd = cmd.update if hasattr(cmd, "update") else cmd.get("update", {})
    assert upd.get("deploy_status") == "failed"
    msg = upd["messages"][0]
    assert "state.files 为空" in msg.content or "write_code" in msg.content
    print("✅ test_deploy_no_files_returns_failed_message 通过")


def test_deploy_missing_token_returns_failed_message(monkeypatch):
    """VERCEL_TOKEN 缺失 → failed + 明示运维补配(不耗部署次数)。"""
    monkeypatch.setattr(deploy_mod.settings, "vercel_token", "")
    monkeypatch.setattr(deploy_mod.settings, "supabase_url", SUPABASE_URL)
    monkeypatch.setattr(deploy_mod.settings, "supabase_anon_key", SUPABASE_ANON_KEY)
    files = [{"path": "src/App.tsx", "content": "x", "language": "tsx"}]
    cmd = deploy_app.func(state=_make_state(files), tool_call_id="tc-2")
    upd = cmd.update if hasattr(cmd, "update") else cmd.get("update", {})
    assert upd.get("deploy_status") == "failed"
    assert "VERCEL_TOKEN" in upd["messages"][0].content
    print("✅ test_deploy_missing_token_returns_failed_message 通过")


def test_deploy_success_flow(monkeypatch):
    """完整成功流:POST 创建 → 轮询 READY → state.deployment_url + deploy_status=ready。"""
    monkeypatch.setattr(deploy_mod.settings, "vercel_token", "fake-token")
    monkeypatch.setattr(deploy_mod.settings, "supabase_url", SUPABASE_URL)
    monkeypatch.setattr(deploy_mod.settings, "supabase_anon_key", SUPABASE_ANON_KEY)

    def fake_create(files, token, project_name=None, target="production"):
        assert token == "fake-token", "token 应原样传给 API"
        assert any(f["file"] == "src/lib/supabase.ts" for f in
                   deploy_mod.build_vercel_files(files)), "inlined files 应含 supabase.ts"
        return {"id": "dpl_ok", "url": "atoms-app-ok.vercel.app", "readyState": "BUILDING"}
    monkeypatch.setattr(deploy_mod, "create_deployment", fake_create)
    monkeypatch.setattr(deploy_mod, "poll_deployment",
                        lambda dep_id, token, **kw: ("ready", "https://atoms-app-ok.vercel.app"))

    files = [{"path": "src/App.tsx", "content": "x", "language": "tsx"}]
    cmd = deploy_app.func(state=_make_state(files), tool_call_id="tc-3")
    upd = cmd.update if hasattr(cmd, "update") else cmd.get("update", {})
    assert upd.get("deploy_status") == "ready"
    assert upd.get("deployment_url") == "https://atoms-app-ok.vercel.app"
    msg = upd["messages"][0]
    assert "https://atoms-app-ok.vercel.app" in msg.content
    # 关键:tool 消息里绝不出现 token
    assert "fake-token" not in msg.content, "token 绝不能出现在 ToolMessage"
    print("✅ test_deploy_success_flow 通过")


def test_deploy_vercel_api_error_returns_failed(monkeypatch):
    """create_deployment 抛 VercelAPIError → deploy_status=failed,消息含错误但不含 token。"""
    monkeypatch.setattr(deploy_mod.settings, "vercel_token", "super-secret-token")
    monkeypatch.setattr(deploy_mod.settings, "supabase_url", SUPABASE_URL)
    monkeypatch.setattr(deploy_mod.settings, "supabase_anon_key", SUPABASE_ANON_KEY)
    def boom(*a, **kw):
        raise VercelAPIError("HTTP 403 Forbidden | body: bad token")
    monkeypatch.setattr(deploy_mod, "create_deployment", boom)
    files = [{"path": "src/App.tsx", "content": "x", "language": "tsx"}]
    cmd = deploy_app.func(state=_make_state(files), tool_call_id="tc-4")
    upd = cmd.update if hasattr(cmd, "update") else cmd.get("update", {})
    assert upd.get("deploy_status") == "failed"
    msg = upd["messages"][0]
    assert "403" in msg.content
    assert "super-secret-token" not in msg.content, "token 绝不能泄露进 ToolMessage"
    print("✅ test_deploy_vercel_api_error_returns_failed 通过")


def test_deploy_poll_timeout_returns_building(monkeypatch):
    """轮询超时(仍 building)→ deploy_status=building + 临时 URL(不阻塞)。"""
    monkeypatch.setattr(deploy_mod.settings, "vercel_token", "tok")
    monkeypatch.setattr(deploy_mod.settings, "supabase_url", SUPABASE_URL)
    monkeypatch.setattr(deploy_mod.settings, "supabase_anon_key", SUPABASE_ANON_KEY)
    monkeypatch.setattr(deploy_mod, "create_deployment",
                        lambda *a, **kw: {"id": "dpl", "url": "atoms-app-t.vercel.app", "readyState": "BUILDING"})
    monkeypatch.setattr(deploy_mod, "poll_deployment",
                        lambda dep_id, token, **kw: ("building", "https://atoms-app-t.vercel.app"))
    files = [{"path": "src/App.tsx", "content": "x", "language": "tsx"}]
    cmd = deploy_app.func(state=_make_state(files), tool_call_id="tc-5")
    upd = cmd.update if hasattr(cmd, "update") else cmd.get("update", {})
    assert upd.get("deploy_status") == "building"
    assert upd.get("deployment_url") == "https://atoms-app-t.vercel.app"
    print("✅ test_deploy_poll_timeout_returns_building 通过")


# ────────────────────────────────────────────────────────────────
# Supabase 动态建表(generate_create_table_sql + deploy_app 集成)
# ────────────────────────────────────────────────────────────────

_DEMO_TABLES = [
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


def test_generate_sql_basic_structure():
    """habits/checkins → CREATE TABLE IF NOT EXISTS + PK + FK + created_at + RLS 全齐。"""
    sql = generate_create_table_sql(_DEMO_TABLES)
    # 幂等:IF NOT EXISTS
    assert "create table if not exists public.habits" in sql
    assert "create table if not exists public.checkins" in sql
    # 主键 uuid → default gen_random_uuid()
    assert "id uuid primary key default gen_random_uuid()" in sql
    # 外键:users.id 特判 auth.users(id);业务外键 public.habits(id);都带 on delete cascade
    assert "references auth.users(id) on delete cascade" in sql
    assert "references public.habits(id) on delete cascade" in sql
    # created_at 约定
    assert "created_at timestamptz not null default now()" in sql
    # RLS + 策略(4 操作 × 2 表 = 8 条 create policy)
    assert sql.count("create policy") == 8
    assert "enable row level security" in sql
    assert "auth.uid() = user_id" in sql
    assert "to authenticated" in sql
    # 策略幂等:drop policy if exists 先行
    assert "drop policy if exists" in sql
    print("✅ test_generate_sql_basic_structure 通过")


def test_generate_sql_no_user_id_skips_rls():
    """无 user_id 的表(lookup 类)→ 仅 CREATE TABLE,不开 RLS(避免无策略全锁)。"""
    tables = [{"name": "categories", "fields": [
        {"name": "id", "type": "uuid", "pk": True},
        {"name": "label", "type": "text"},
        {"name": "created_at", "type": "timestamptz"},
    ]}]
    sql = generate_create_table_sql(tables)
    assert "create table if not exists public.categories" in sql
    assert "enable row level security" not in sql, "无 user_id 不应开 RLS"
    assert "create policy" not in sql, "无 user_id 不应有策略"
    print("✅ test_generate_sql_no_user_id_skips_rls 通过")


def test_generate_sql_empty_tables_returns_empty():
    """tables 为空 → 空字符串(调用方应短路,不调 API)。"""
    assert generate_create_table_sql([]) == ""
    print("✅ test_generate_sql_empty_tables_returns_empty 通过")


def test_generate_sql_rejects_bad_identifier():
    """恶意表名/字段名/类型/外键 → ValueError(防注入;DDL 走特权 PAT)。"""
    bad_cases = [
        ({"name": "habits; drop table users; --", "fields": [{"name": "id", "type": "uuid", "pk": True}]}, "恶意表名"),
        ({"name": "ok", "fields": [{"name": "evil col", "type": "uuid", "pk": True}]}, "恶意字段名(空格)"),
        ({"name": "ok", "fields": [{"name": "id", "type": "uuid; drop table x", "pk": True}]}, "恶意类型"),
        ({"name": "ok", "fields": [{"name": "id", "type": "uuid", "pk": True}, {"name": "u", "type": "uuid", "fk": "users.id; drop table x"}]}, "恶意外键"),
        ({"name": "ok", "fields": [{"name": "id", "type": "weird_type", "pk": True}]}, "白名单外类型"),
    ]
    for tbl, label in bad_cases:
        try:
            generate_create_table_sql([tbl])
        except ValueError:
            continue
        raise AssertionError(f"{label} 应被拒绝,却生成了 SQL")
    print("✅ test_generate_sql_rejects_bad_identifier 通过")


def test_deploy_ddl_ok_note_in_success_message(monkeypatch):
    """有 PAT + design.supabase_tables → 建表成功,success 消息含 ok note + 表名。"""
    monkeypatch.setattr(deploy_mod.settings, "vercel_token", "fake-token")
    monkeypatch.setattr(deploy_mod.settings, "supabase_url", SUPABASE_URL)
    monkeypatch.setattr(deploy_mod.settings, "supabase_anon_key", SUPABASE_ANON_KEY)
    monkeypatch.setattr(deploy_mod.settings, "supabase_access_token", "sbp-fake-pat")
    monkeypatch.setattr(deploy_mod, "create_deployment",
                        lambda *a, **kw: {"id": "dpl", "url": "atoms-app-ok.vercel.app", "readyState": "BUILDING"})
    monkeypatch.setattr(deploy_mod, "poll_deployment",
                        lambda dep_id, token, **kw: ("ready", "https://atoms-app-ok.vercel.app"))
    seen = {}
    def fake_create(tables, access_token, project_ref, app_id=""):
        seen["tables"] = list(tables)
        seen["ref"] = project_ref
        seen["token"] = access_token
        seen["app_id"] = app_id
        return {"status": "ok", "tables": [t["name"] for t in tables], "sql_chars": 100}
    monkeypatch.setattr(deploy_mod, "create_supabase_tables", fake_create)

    state = {"files": [{"path": "src/App.tsx", "content": "x", "language": "tsx"}],
             "design": {"product_type": "web_app", "supabase_tables": _DEMO_TABLES, "pages": []},
             "iter_count": 0}
    cmd = deploy_app.func(state=state, tool_call_id="tc-ddl-ok")
    upd = cmd.update if hasattr(cmd, "update") else cmd.get("update", {})
    assert upd.get("deploy_status") == "ready"
    msg = upd["messages"][0].content
    # ok note + 表名出现
    assert "动态建表" in msg and "habits" in msg and "checkins" in msg
    # 传给 create_supabase_tables 的 ref 来自 SUPABASE_URL
    assert seen["ref"] == "gkcofqevmhenwdlbqbog"
    # 多租户:deploy_app 必须传非空 app_id(以 app_ 开头,字母合规)
    assert seen["app_id"].startswith("app_") and len(seen["app_id"]) == 10, \
        f"app_id 应为 'app_' + 6 位 hex,实际:{seen['app_id']!r}"
    # PAT 绝不进 ToolMessage
    assert "sbp-fake-pat" not in msg
    print("✅ test_deploy_ddl_ok_note_in_success_message 通过")


def test_deploy_ddl_skipped_when_no_pat(monkeypatch):
    """无 PAT + design 有表 → skip note,不调建表 API,部署照常 ready。"""
    monkeypatch.setattr(deploy_mod.settings, "vercel_token", "fake-token")
    monkeypatch.setattr(deploy_mod.settings, "supabase_url", SUPABASE_URL)
    monkeypatch.setattr(deploy_mod.settings, "supabase_anon_key", SUPABASE_ANON_KEY)
    monkeypatch.setattr(deploy_mod.settings, "supabase_access_token", "")
    monkeypatch.setattr(deploy_mod, "create_deployment",
                        lambda *a, **kw: {"id": "dpl", "url": "atoms-app-ok.vercel.app", "readyState": "BUILDING"})
    monkeypatch.setattr(deploy_mod, "poll_deployment",
                        lambda dep_id, token, **kw: ("ready", "https://atoms-app-ok.vercel.app"))
    called = {"n": 0}
    def must_not_call(*a, **kw):
        called["n"] += 1
        return {"status": "ok", "tables": [], "sql_chars": 0}
    monkeypatch.setattr(deploy_mod, "create_supabase_tables", must_not_call)

    state = {"files": [{"path": "src/App.tsx", "content": "x", "language": "tsx"}],
             "design": {"product_type": "web_app", "supabase_tables": _DEMO_TABLES, "pages": []},
             "iter_count": 0}
    cmd = deploy_app.func(state=state, tool_call_id="tc-ddl-skip")
    upd = cmd.update if hasattr(cmd, "update") else cmd.get("update", {})
    assert upd.get("deploy_status") == "ready", "无 PAT 不应阻塞部署"
    msg = upd["messages"][0].content
    assert "跳过" in msg or "skip" in msg.lower() or "未配" in msg
    assert called["n"] == 0, "无 PAT 不应调建表 API"
    print("✅ test_deploy_ddl_skipped_when_no_pat 通过")


def test_deploy_ddl_failure_is_nonblocking(monkeypatch):
    """建表 API 抛 SupabaseAPIError → warn note,但部署照常 ready(非阻塞)。"""
    monkeypatch.setattr(deploy_mod.settings, "vercel_token", "fake-token")
    monkeypatch.setattr(deploy_mod.settings, "supabase_url", SUPABASE_URL)
    monkeypatch.setattr(deploy_mod.settings, "supabase_anon_key", SUPABASE_ANON_KEY)
    monkeypatch.setattr(deploy_mod.settings, "supabase_access_token", "sbp-fake-pat")
    monkeypatch.setattr(deploy_mod, "create_deployment",
                        lambda *a, **kw: {"id": "dpl", "url": "atoms-app-ok.vercel.app", "readyState": "BUILDING"})
    monkeypatch.setattr(deploy_mod, "poll_deployment",
                        lambda dep_id, token, **kw: ("ready", "https://atoms-app-ok.vercel.app"))
    def boom(*a, **kw):
        raise SupabaseAPIError("HTTP 500 | body: something")
    monkeypatch.setattr(deploy_mod, "create_supabase_tables", boom)

    state = {"files": [{"path": "src/App.tsx", "content": "x", "language": "tsx"}],
             "design": {"product_type": "web_app", "supabase_tables": _DEMO_TABLES, "pages": []},
             "iter_count": 0}
    cmd = deploy_app.func(state=state, tool_call_id="tc-ddl-fail")
    upd = cmd.update if hasattr(cmd, "update") else cmd.get("update", {})
    assert upd.get("deploy_status") == "ready", "建表失败不应阻塞部署"
    msg = upd["messages"][0].content
    assert "未完成" in msg or "⚠️" in msg, "应有警告 note"
    assert "HTTP 500" in msg, "错误摘要应进 note(帮用户诊断)"
    assert "sbp-fake-pat" not in msg, "PAT 绝不泄露"
    print("✅ test_deploy_ddl_failure_is_nonblocking 通过")


# ────────────────────────────────────────────────────────────────
# 多租户 app_id 前缀隔离
#   - _app_id_from_project_name:从 atoms-app-{6hex} 抽前缀(字母开头合规)
#   - generate_create_table_sql(app_id=...):表名 + 业务外键 + RLS policy 名都带前缀
#   - inject_table_prefix:应用代码 .from('t') → .from('{app_id}_t')(不误改其他字符串)
#   - deploy_app e2e:两个不同 app → 不同前缀表 + 应用代码各自带对的前缀
# ────────────────────────────────────────────────────────────────

def test_app_id_from_project_name_hex():
    """atoms-app-34f04b → app_34f04b(取末段 hex,加 app_ 前缀,字母开头合规)。"""
    assert _app_id_from_project_name("atoms-app-34f04b") == "app_34f04b"
    assert _app_id_from_project_name("atoms-app-8ea1a9") == "app_8ea1a9"
    print("✅ test_app_id_from_project_name_hex 通过")


def test_app_id_digit_leading_hex_still_valid_identifier():
    """hex 以数字开头(如 3abcde)→ app_3abcde:首字符仍是字母(a),Postgres 标识符合规。

    这是 app_id 加 'app_' 前缀(而非纯 hex)的关键理由 —— 纯 hex '3abcde' 以数字开头会
    违反 Postgres 无引号标识符规则(必须字母/下划线开头),让 Supabase CREATE TABLE 语法错。
    """
    aid = _app_id_from_project_name("atoms-app-3abcde")
    assert aid == "app_3abcde"
    # 首字符是字母(不是数字)→ _IDENT_RE 能过 → SQL 标识符合规
    assert aid[0].isalpha(), "app_id 首字符必须是字母(否则 SQL 表名非法)"
    print("✅ test_app_id_digit_leading_hex_still_valid_identifier 通过")


def test_generate_sql_with_app_id_prefix():
    """app_id 给定 → 表名/业务外键/RLS policy 名全带前缀;users.id 特判不加(仍 auth.users)。"""
    sql = generate_create_table_sql(_DEMO_TABLES, app_id="app_34f04b")
    # 表名加前缀(原来的 public.habits 不应再出现裸形态)
    assert "create table if not exists public.app_34f04b_habits" in sql
    assert "create table if not exists public.app_34f04b_checkins" in sql
    assert "public.habits " not in sql and "public.habits(" not in sql, "裸 public.habits 不应再出现"
    # 业务外键:checkins.habit_id → references public.app_34f04b_habits(id)(带前缀)
    assert "references public.app_34f04b_habits(id) on delete cascade" in sql
    # users.id 特判仍为 auth.users(不加前缀,Supabase 内置 auth 表)
    assert "references auth.users(id) on delete cascade" in sql
    assert "app_34f04b_users" not in sql, "users 表绝不能加业务前缀(它是 auth 内置)"
    # RLS policy 名随之带前缀(基于带前缀表名)
    assert 'app_34f04b_habits_select_own' in sql
    assert 'app_34f04b_checkins_insert_own' in sql
    # 注释里的表名也带前缀(便于日志诊断)
    assert "-- 表 app_34f04b_habits" in sql
    print("✅ test_generate_sql_with_app_id_prefix 通过")


def test_generate_sql_two_app_ids_produce_disjoint_tables():
    """同一 design + 不同 app_id → 两个 SQL 里没有重合表名(隔离核心验证)。"""
    sql_a = generate_create_table_sql(_DEMO_TABLES, app_id="app_34f04b")
    sql_b = generate_create_table_sql(_DEMO_TABLES, app_id="app_8ea1a9")
    assert "app_34f04b_habits" in sql_a and "app_34f04b_habits" not in sql_b
    assert "app_8ea1a9_habits" in sql_b and "app_8ea1a9_habits" not in sql_a
    # 两 app 的 habits 表名不同 → 第二次部署 IF NOT EXISTS 不会因表已存在而跳过
    print("✅ test_generate_sql_two_app_ids_produce_disjoint_tables 通过")


def test_generate_sql_empty_app_id_backward_compat():
    """app_id 空串 → 沿用旧无前缀行为(向后兼容;DDL 测试默认路径仍可用)。"""
    sql = generate_create_table_sql(_DEMO_TABLES)  # 不传 app_id
    assert "create table if not exists public.habits" in sql
    assert "app_" not in sql, "空 app_id 不应产生任何前缀"
    print("✅ test_generate_sql_empty_app_id_backward_compat 通过")


def test_generate_sql_rejects_bad_app_id():
    """恶意/过长 app_id → ValueError(进 SQL 表名,防注入)。"""
    bad_app_ids = [
        "34f04b",               # 数字开头(纯 hex 无 app_ 前缀)→ 非法标识符
        "app_34f04b;",          # 含分号
        "app_evil; drop table", # 空格 + SQL
        "app_" + "a" * 100,     # 过长(撑爆 Postgres 标识符 63 上限)
        "APP_34f04b",           # 大写(违反 _IDENT_RE)
    ]
    for aid in bad_app_ids:
        try:
            generate_create_table_sql(_DEMO_TABLES, app_id=aid)
        except ValueError:
            continue
        raise AssertionError(f"恶意 app_id {aid!r} 应被拒绝")
    print("✅ test_generate_sql_rejects_bad_app_id 通过")


# ────────────────────────────────────────────────────────────────
# inject_table_prefix
# ────────────────────────────────────────────────────────────────

def test_inject_table_prefix_single_quote():
    """.from('habits') → .from('app_34f04b_habits')(单引号)。"""
    files = [{"path": "src/api.ts", "content":
        "const { data } = await supabase.from('habits').select()", "language": "typescript"}]
    out = inject_table_prefix(files, _DEMO_TABLES, "app_34f04b")
    c = out[0]["content"]
    assert ".from('app_34f04b_habits')" in c
    assert ".from('habits')" not in c, "裸 .from('habits') 应被替换掉"
    print("✅ test_inject_table_prefix_single_quote 通过")


def test_inject_table_prefix_double_quote():
    """.from("habits") → .from("app_34f04b_habits")(双引号,首尾一致)。"""
    files = [{"path": "src/api.ts", "content":
        'const { data } = await supabase.from("habits").select()', "language": "typescript"}]
    out = inject_table_prefix(files, _DEMO_TABLES, "app_34f04b")
    c = out[0]["content"]
    assert '.from("app_34f04b_habits")' in c
    assert '.from("habits")' not in c
    print("✅ test_inject_table_prefix_double_quote 通过")


def test_inject_table_prefix_multiple_tables():
    """多张表(habits + checkins)同时出现 → 都被替换。"""
    files = [{"path": "src/api.ts", "content":
        "supabase.from('habits').select(); supabase.from('checkins').insert({})", "language": "typescript"}]
    out = inject_table_prefix(files, _DEMO_TABLES, "app_34f04b")
    c = out[0]["content"]
    assert ".from('app_34f04b_habits')" in c
    assert ".from('app_34f04b_checkins')" in c
    print("✅ test_inject_table_prefix_multiple_tables 通过")


def test_inject_table_prefix_no_false_positive():
    """白名单外的字符串绝不被误改(关键:不破坏其他代码)。"""
    content = (
        "// habits 表说明(注释里的 habits 单词不应改)\n"
        "const habitList = []  // 变量名含 habit 子串(不应改)\n"
        "const { data: users } = await supabase.from('users').select()  // users 是 auth 表,不在白名单\n"
        "const label = 'habits'  // 裸字符串 'habits'(无 .from 前缀),不应改\n"
        "fetch('/api/habits')  // URL 路径,不是 .from 调用,不应改\n"
    )
    files = [{"path": "src/api.ts", "content": content, "language": "typescript"}]
    out = inject_table_prefix(files, _DEMO_TABLES, "app_34f04b")
    c = out[0]["content"]
    # 注释里的 habits 单词、变量名 habitList、裸字符串 'habits'、URL 路径都不应被改
    assert "// habits 表说明" in c, "注释不应被改"
    assert "habitList" in c, "变量名不应被改"
    assert "label = 'habits'" in c, "裸字符串 'habits'(非 .from())不应被改"
    assert "fetch('/api/habits')" in c, "URL 路径不应被改"
    # users 不在 design.supabase_tables(是 auth 表)→ .from('users') 不改
    assert ".from('users')" in c, "users 不在白名单,不应被改"
    # 整个文件没有合法的 .from('habits') 调用 → 不应注入任何前缀
    assert "app_34f04b_" not in c, "本例无可替换的 .from('habits'),不应注入任何前缀"
    print("✅ test_inject_table_prefix_no_false_positive 通过")


def test_inject_table_prefix_substring_safety():
    """表名按长度降序匹配:若同时有 'checkin' 和 'checkins',长表名优先,避免子串误匹配。"""
    tables = [
        {"name": "checkin", "fields": [{"name": "id", "type": "uuid", "pk": True}]},
        {"name": "checkins", "fields": [{"name": "id", "type": "uuid", "pk": True}]},
    ]
    files = [{"path": "src/api.ts", "content":
        "supabase.from('checkins').select(); supabase.from('checkin').select()",
        "language": "typescript"}]
    out = inject_table_prefix(files, tables, "app_34f04b")
    c = out[0]["content"]
    assert ".from('app_34f04b_checkins')" in c, "checkins(长)应整体匹配,不被 checkin 吃掉"
    assert ".from('app_34f04b_checkin')" in c, "checkin(短)也应单独匹配"
    # 两者都替换成功,无残留裸 .from('checkin...')
    assert ".from('checkins')" not in c and ".from('checkin')" not in c
    print("✅ test_inject_table_prefix_substring_safety 通过")


def test_inject_table_prefix_empty_app_id_noop():
    """空 app_id → 原样返回(浅拷贝,不污染入参;向后兼容)。"""
    files = [{"path": "src/api.ts", "content": "supabase.from('habits').select()", "language": "typescript"}]
    out = inject_table_prefix(files, _DEMO_TABLES, "")
    assert out[0]["content"] == "supabase.from('habits').select()", "空 app_id 应原样不动"
    print("✅ test_inject_table_prefix_empty_app_id_noop 通过")


def test_inject_table_prefix_skips_supabase_ts():
    """supabase.ts(刚注入的标准 client)不应被改写(无业务 .from,免得误伤)。"""
    files = [
        {"path": "src/lib/supabase.ts", "content":
            "export const supabase = createClient(url, key)", "language": "typescript"},
        {"path": "src/api.ts", "content": "supabase.from('habits').select()", "language": "typescript"},
    ]
    out = inject_table_prefix(files, _DEMO_TABLES, "app_34f04b")
    sb = next(f for f in out if f["path"] == "src/lib/supabase.ts")
    api = next(f for f in out if f["path"] == "src/api.ts")
    assert sb["content"] == "export const supabase = createClient(url, key)", "supabase.ts 不应被改"
    assert ".from('app_34f04b_habits')" in api["content"], "api.ts 仍应被注入前缀"
    print("✅ test_inject_table_prefix_skips_supabase_ts 通过")


def test_inject_table_prefix_does_not_mutate_input():
    """inject_table_prefix 不应修改入参 files(返回浅拷贝)。"""
    original = "supabase.from('habits').select()"
    files = [{"path": "src/api.ts", "content": original, "language": "typescript"}]
    out = inject_table_prefix(files, _DEMO_TABLES, "app_34f04b")
    assert files[0]["content"] == original, "入参 files 不应被污染"
    assert out is not files, "应返回新列表"
    assert out[0] is not files[0], "应返回新 dict(浅拷贝)"
    print("✅ test_inject_table_prefix_does_not_mutate_input 通过")


# ────────────────────────────────────────────────────────────────
# deploy_app e2e:多租户隔离(任务的硬验证标准)
# ────────────────────────────────────────────────────────────────

def test_deploy_app_two_apps_use_disjoint_prefixes(monkeypatch):
    """同 Supabase 项目,两次 deploy_app 不同 app → 不同 app_id → 不同前缀表 + 应用代码各自带前缀。

    验证任务的硬标准:app A habits[name/freq] + app B habits[title/goal] 同一 Supabase 项目
    → 建 app_34f04b_habits 和 app_8ea1a9_habits 独立表(字段不同也不冲突);
    应用代码的 .from('habits') 各自被换成 .from('app_{hex}_habits')。
    """
    monkeypatch.setattr(deploy_mod.settings, "vercel_token", "tok")
    monkeypatch.setattr(deploy_mod.settings, "supabase_url", SUPABASE_URL)
    monkeypatch.setattr(deploy_mod.settings, "supabase_anon_key", SUPABASE_ANON_KEY)
    monkeypatch.setattr(deploy_mod.settings, "supabase_access_token", "sbp-fake-pat")
    monkeypatch.setattr(deploy_mod, "poll_deployment",
                        lambda dep_id, token, **kw: ("ready", "https://x.vercel.app"))

    # 控制 secrets.token_hex:App A → '34f04b',App B → '8ea1a9'
    hex_seq = iter(["34f04b", "8ea1a9"])
    monkeypatch.setattr(deploy_mod.secrets, "token_hex", lambda n: next(hex_seq))

    # 捕获传给建表 API 的 app_id(应不同)
    ddl_seen = []

    def fake_create_tables(tables, access_token, project_ref, app_id=""):
        ddl_seen.append(app_id)
        return {"status": "ok", "tables": [t["name"] for t in tables], "sql_chars": 100}
    monkeypatch.setattr(deploy_mod, "create_supabase_tables", fake_create_tables)

    # 捕获传给 create_deployment 的 files(检查应用代码 .from() 前缀注入)
    deploy_seen = []

    def fake_create_deployment(files, token, project_name=None, target="production"):
        deploy_seen.append({
            "project_name": project_name,
            "api_content": next((f.get("content") for f in files
                                 if (f.get("path") or "").endswith("api.ts")), None),
        })
        return {"id": f"dpl-{project_name}", "url": f"{project_name}.vercel.app",
                "name": project_name, "readyState": "BUILDING"}
    monkeypatch.setattr(deploy_mod, "create_deployment", fake_create_deployment)

    # App A:habits[name, frequency];App B:habits[title, goal](字段不同,模拟不同 app)
    design_a = {"supabase_tables": [{"name": "habits", "fields": [
        {"name": "id", "type": "uuid", "pk": True},
        {"name": "user_id", "type": "uuid", "fk": "users.id"},
        {"name": "name", "type": "text"},
        {"name": "frequency", "type": "text"},
    ]}], "pages": []}
    design_b = {"supabase_tables": [{"name": "habits", "fields": [
        {"name": "id", "type": "uuid", "pk": True},
        {"name": "user_id", "type": "uuid", "fk": "users.id"},
        {"name": "title", "type": "text"},
        {"name": "goal", "type": "integer"},
    ]}], "pages": []}

    files_tpl = [{"path": "src/api.ts", "content":
        "await supabase.from('habits').select()", "language": "typescript"}]

    deploy_app.func(state={"files": list(files_tpl), "design": design_a, "iter_count": 0},
                    tool_call_id="tc-iso-a")
    deploy_app.func(state={"files": list(files_tpl), "design": design_b, "iter_count": 0},
                    tool_call_id="tc-iso-b")

    # 1) 两次 deploy_app 用了不同的 app_id(隔离前提)
    assert ddl_seen == ["app_34f04b", "app_8ea1a9"], f"app_id 序列错:{ddl_seen}"
    # 2) 两次的 project_name 也不同(各自的 atoms-app-{hex})
    assert deploy_seen[0]["project_name"] == "atoms-app-34f04b"
    assert deploy_seen[1]["project_name"] == "atoms-app-8ea1a9"
    # 3) 应用代码:.from('habits') 各自换成对应前缀(关键:字段不同也不冲突,各查各表)
    assert "from('app_34f04b_habits')" in deploy_seen[0]["api_content"]
    assert "from('app_8ea1a9_habits')" in deploy_seen[1]["api_content"]
    assert "from('habits')" not in deploy_seen[0]["api_content"], "App A 裸 from('habits') 应被替换"
    assert "from('habits')" not in deploy_seen[1]["api_content"], "App B 裸 from('habits') 应被替换"
    # 4) 两个前缀互不重叠(隔离生效)
    assert deploy_seen[0]["api_content"] != deploy_seen[1]["api_content"]
    print("✅ test_deploy_app_two_apps_use_disjoint_prefixes 通过")


def test_deploy_app_passes_project_name_to_create_deployment(monkeypatch):
    """deploy_app 生成的 project_name 同源传给 create_deployment(与 app_id 共用 hex)。"""
    monkeypatch.setattr(deploy_mod.settings, "vercel_token", "tok")
    monkeypatch.setattr(deploy_mod.settings, "supabase_url", SUPABASE_URL)
    monkeypatch.setattr(deploy_mod.settings, "supabase_anon_key", SUPABASE_ANON_KEY)
    monkeypatch.setattr(deploy_mod, "poll_deployment",
                        lambda dep_id, token, **kw: ("ready", "https://x.vercel.app"))
    monkeypatch.setattr(deploy_mod.secrets, "token_hex", lambda n: "abcdef")

    seen_name = {}

    def fake_deploy(files, token, project_name=None, target="production"):
        seen_name["name"] = project_name
        return {"id": "dpl", "url": "x.vercel.app", "name": project_name, "readyState": "BUILDING"}
    monkeypatch.setattr(deploy_mod, "create_deployment", fake_deploy)

    state = {"files": [{"path": "src/App.tsx", "content": "x", "language": "tsx"}], "iter_count": 0}
    deploy_app.func(state=state, tool_call_id="tc-pn")
    assert seen_name["name"] == "atoms-app-abcdef", \
        f"project_name 应为 atoms-app-abcdef,实际:{seen_name['name']!r}"
    print("✅ test_deploy_app_passes_project_name_to_create_deployment 通过")


# 简易 monkeypatch(避免依赖 pytest,可独立 python tests/test_deploy.py 跑)
class _Monkey:
    def __init__(self):
        self._stash = []
    def setattr(self, target, name, value):
        old = getattr(target, name)
        self._stash.append((target, name, old))
        setattr(target, name, value)
    def undo(self):
        for target, name, old in reversed(self._stash):
            setattr(target, name, old)
        self._stash.clear()


def _run_all():
    """简单 test runner:依次跑所有 test_*,失败抛 AssertionError。"""
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]

    # 救济:用 pytest 跑时(导入了 pytest.monkeypatch)就直接跑;独立跑用 _Monkey
    import inspect
    for fn in fns:
        sig = inspect.signature(fn)
        params = list(sig.parameters)
        if params and params[0] == "monkeypatch":
            mp = _Monkey()
            try:
                fn(mp)
            finally:
                mp.undo()
        else:
            fn()
    print(f"\n=== deploy 单元测试全部通过({len(fns)} 项)===")


if __name__ == "__main__":
    _run_all()
