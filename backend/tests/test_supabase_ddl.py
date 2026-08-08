"""Supabase 动态建表测试:helper 单测 + 真 Supabase e2e(PAT 门控,默认 skip)。

覆盖:
- generate_create_table_sql:已在 test_deploy.py 覆盖主路径;这里补 helper 边界
  (_policy_name 截断 / _render_fk / _render_column 非 uuid 主键 / _project_ref_from_url)
- create_supabase_tables 请求形状:mock _supabase_request,验 path/body/token 不入 body
- 真 e2e(ATOMS_RUN_SUPABASE_DDL=1):建临时表 → 查 information_schema → DROP 清理

凭证安全:真 e2e 只打印 HTTP status + 表名/列名校验结果,**绝不**打印 PAT / 完整响应体。

用法:
    cd backend && source .venv/bin/activate
    # 单测(默认,秒级,不触网)
    env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy -u ALL_PROXY -u all_proxy \\
        python tests/test_supabase_ddl.py
    # 真 e2e(需 .env 配 SUPABASE_ACCESS_TOKEN,会真建表+清理)
    env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy -u ALL_PROXY -u all_proxy \\
        ATOMS_RUN_SUPABASE_DDL=1 python tests/test_supabase_ddl.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import deploy as deploy_mod  # noqa: E402
from app.deploy import (  # noqa: E402
    SupabaseAPIError,
    _policy_name,
    _project_ref_from_url,
    _render_column,
    _render_fk,
    create_supabase_tables,
    generate_create_table_sql,
)


# ────────────────────────────────────────────────────────────────
# helper 边界单测
# ────────────────────────────────────────────────────────────────

def test_policy_name_truncates_long_table():
    """表名 + _select_own 超 63 字符 → 截断表名段,总长 ≤63。"""
    long_table = "a" * 70  # 70 字符表名
    name = _policy_name(long_table, "select")
    assert len(name) == 63, f"策略名应截到 63 字符,实际 {len(name)}"
    assert name.endswith("_select_own")
    # 短表名不截断
    assert _policy_name("habits", "select") == "habits_select_own"
    print("✅ test_policy_name_truncates_long_table 通过")


def test_render_fk_users_id_special_case():
    """fk='users.id' → auth.users(id)(Supabase auth 用户在 auth schema);其他 → public.*。"""
    assert _render_fk("users.id") == "references auth.users(id) on delete cascade"
    assert _render_fk("habits.id") == "references public.habits(id) on delete cascade"
    # 非法外键格式 → ValueError
    for bad in ["users", "users.id; drop table x", "users.id extra", "", "1table.col", "t.1c"]:
        try:
            _render_fk(bad)
        except ValueError:
            continue
        raise AssertionError(f"恶意外键 {bad!r} 应被拒绝")
    print("✅ test_render_fk_users_id_special_case 通过")


def test_render_column_non_uuid_pk_and_types():
    """非 uuid 主键不加 gen_random_uuid();jsonb/varchar/integer 等白名单类型正常渲染。"""
    # integer 主键:不加 default gen_random_uuid
    col = _render_column({"name": "id", "type": "integer", "pk": True})
    assert col == "id integer primary key"
    assert "gen_random_uuid" not in col
    # jsonb 类型
    assert _render_column({"name": "meta", "type": "jsonb"}) == "meta jsonb"
    # varchar
    assert _render_column({"name": "title", "type": "varchar"}) == "title varchar"
    # created_at timestamptz 约定
    assert _render_column({"name": "created_at", "type": "timestamptz"}) == "created_at timestamptz not null default now()"
    print("✅ test_render_column_non_uuid_pk_and_types 通过")


def test_project_ref_from_url_variants():
    """从各种 SUPABASE_URL 形式抽 ref;ref 允许连字符/数字开头(vanity 子域),拒绝路径穿越/空格。"""
    assert _project_ref_from_url("https://abc123.supabase.co") == "abc123"
    assert _project_ref_from_url("https://my-proj.supabase.co/") == "my-proj"
    assert _project_ref_from_url("http://test.supabase.co") == "test"
    # 数字开头 OK(URL 组件,非 SQL 标识符)
    assert _project_ref_from_url("https://123abc.supabase.co") == "123abc"
    # 空 / 路径穿越 / 空格 / 反斜杠 → ValueError
    for bad in ["", "not a url", "https://t r.supabase.co", "https://../x.supabase.co"]:
        try:
            _project_ref_from_url(bad)
        except ValueError:
            continue
        raise AssertionError(f"恶意/空 URL {bad!r} 应被拒绝")
    print("✅ test_project_ref_from_url_variants 通过")


# ────────────────────────────────────────────────────────────────
# create_supabase_tables 请求形状(mock _supabase_request,不触网)
# ────────────────────────────────────────────────────────────────

def test_create_supabase_tables_request_shape(monkeypatch=None):
    """mock _supabase_request → 验 path/body/token 形状;token 不进 body,read_only=False。"""
    captured = {}

    def fake_req(path, body, access_token, timeout=None):
        captured["path"] = path
        captured["body"] = body
        captured["token"] = access_token
        return {}  # 201 空 body

    if monkeypatch is None:
        deploy_mod._supabase_request = fake_req
    else:
        monkeypatch.setattr(deploy_mod, "_supabase_request", fake_req)

    tables = [{"name": "habits", "fields": [
        {"name": "id", "type": "uuid", "pk": True},
        {"name": "user_id", "type": "uuid", "fk": "users.id"},
        {"name": "created_at", "type": "timestamptz"},
    ]}]
    try:
        res = create_supabase_tables(tables, "sbp-fake-pat", "ref123abc")
    finally:
        if monkeypatch is None:
            pass  # 不还原(进程退出即清);pytest 路径由 monkeypatch 还原
    assert res["status"] == "ok"
    assert res["tables"] == ["habits"]
    # path 含 ref
    assert captured["path"] == "/v1/projects/ref123abc/database/query"
    # body 含生成的 SQL + read_only=False
    assert "create table if not exists public.habits" in captured["body"]["query"]
    assert captured["body"]["read_only"] is False
    # token 透传给 _supabase_request(由它进 Authorization header);**不进 body**
    assert captured["token"] == "sbp-fake-pat"
    assert "sbp-fake-pat" not in captured["body"]["query"]
    print("✅ test_create_supabase_tables_request_shape 通过")


def test_create_supabase_tables_propagates_api_error(monkeypatch=None):
    """_supabase_request 抛 SupabaseAPIError → create_supabase_tables 透传(调用方决定阻塞)。"""
    def boom(path, body, access_token, timeout=None):
        raise SupabaseAPIError("HTTP 401 | body: JWT failed")
    if monkeypatch is None:
        deploy_mod._supabase_request = boom
    else:
        monkeypatch.setattr(deploy_mod, "_supabase_request", boom)
    tables = [{"name": "t", "fields": [{"name": "id", "type": "uuid", "pk": True}]}]
    try:
        create_supabase_tables(tables, "sbp-fake", "ref")
    except SupabaseAPIError as e:
        assert "401" in str(e)
        print("✅ test_create_supabase_tables_propagates_api_error 通过")
        return
    raise AssertionError("应透传 SupabaseAPIError")


def test_create_supabase_tables_empty_tables_no_http(monkeypatch=None):
    """无表 → 返回 status=empty,不调 _supabase_request(短路)。"""
    called = {"n": 0}
    def must_not_call(*a, **kw):
        called["n"] += 1
        return {}
    if monkeypatch is None:
        deploy_mod._supabase_request = must_not_call
    else:
        monkeypatch.setattr(deploy_mod, "_supabase_request", must_not_call)
    res = create_supabase_tables([], "sbp-fake", "ref")
    assert res["status"] == "empty"
    assert called["n"] == 0
    print("✅ test_create_supabase_tables_empty_tables_no_http 通过")


# ────────────────────────────────────────────────────────────────
# 真 Supabase e2e(默认 skip;ATOMS_RUN_SUPABASE_DDL=1 启用)
# 建临时表 → 查 information_schema 验证 → DROP 清理
# ────────────────────────────────────────────────────────────────

def _run_e2e() -> None:
    """真调 Supabase Management API:建一组 _atoms_probe_<ts> 临时表,验证,清理。"""
    from app.config import settings

    if not settings.supabase_access_token:
        print("❌ backend/.env 未配 SUPABASE_ACCESS_TOKEN(PAT),无法跑 e2e。")
        sys.exit(1)
    if not settings.supabase_access_token.startswith("sbp_"):
        print("⚠️ SUPABASE_ACCESS_TOKEN 不以 sbp_ 开头,疑似填错(service_role/anon);e2e 大概率 401。仍尝试…")

    ref = _project_ref_from_url(settings.supabase_url)
    # 唯一时间戳后缀,避免撞别人/历史残留
    ts = hex(int(time.time()))[2:]
    tables = [
        {"name": f"_atoms_probe_habits_{ts}", "fields": [
            {"name": "id", "type": "uuid", "pk": True},
            {"name": "user_id", "type": "uuid", "fk": "users.id"},
            {"name": "name", "type": "text"},
            {"name": "created_at", "type": "timestamptz"},
        ]},
        {"name": f"_atoms_probe_lookup_{ts}", "fields": [  # 无 user_id → 验证不开 RLS
            {"name": "id", "type": "uuid", "pk": True},
            {"name": "label", "type": "text"},
            {"name": "created_at", "type": "timestamptz"},
        ]},
    ]
    print(f"[1/3] 生成 CREATE TABLE + RLS SQL({len(tables)} 张临时表,前缀 _atoms_probe_)…")
    sql = generate_create_table_sql(tables)
    print(f"      SQL {len(sql)} 字符。建表中…")
    try:
        res = create_supabase_tables(tables, settings.supabase_access_token, ref)
    except SupabaseAPIError as e:
        print(f"❌ 建表 API 失败:{e}")
        print("   常见:PAT 无效/过期(401)、ref 错、表名撞、网络。PAT 绝不会被打印。")
        sys.exit(2)
    print(f"      ✅ 建表调用成功({res})。")

    t1, t2 = tables[0]["name"], tables[1]["name"]
    print(f"[2/3] 查 information_schema 验证表/列/RLS 落地…")
    verify_sql = (
        "select "
        f"(select count(*) from information_schema.tables where table_schema='public' and table_name='{t1}'),"
        f"(select count(*) from information_schema.columns where table_schema='public' and table_name='{t1}' and column_name='user_id'),"
        f"(select count(*) from pg_policies where schemaname='public' and tablename='{t1}'),"
        f"(select count(*) from information_schema.tables where table_schema='public' and table_name='{t2}'),"
        f"(select count(*) from pg_policies where schemaname='public' and tablename='{t2}');"
    )
    try:
        rows = deploy_mod._supabase_request(
            f"/v1/projects/{ref}/database/query",
            {"query": verify_sql, "read_only": True},
            settings.supabase_access_token,
        )
    except SupabaseAPIError as e:
        print(f"❌ 验证查询失败:{e}")
        rows = None

    # 解析:不同 Supabase 版本返回 [{...}] 或 {rows:[...]};尽量取一行
    def _first_row(d):
        if isinstance(d, list) and d:
            return d[0]
        if isinstance(d, dict):
            if d.get("rows"):
                return d["rows"][0]
            # 平铺 {col:val, ...}
            return d
        return {}
    row = _first_row(rows) if rows else {}
    cols = list(row.values()) if isinstance(row, dict) else []
    print(f"      验证结果(顺序:t1存在 / t1.user_id / t1策略数 / t2存在 / t2策略数):{cols}")
    ok = True
    if len(cols) >= 5:
        if cols[0] != 1: print(f"   ❌ 表 {t1} 未建"); ok = False
        if cols[1] != 1: print(f"   ❌ {t1}.user_id 列未建"); ok = False
        if cols[2] != 4: print(f"   ❌ {t1} 应有 4 条 RLS 策略,实际 {cols[2]}"); ok = False
        if cols[3] != 1: print(f"   ❌ 表 {t2} 未建"); ok = False
        if cols[4] != 0: print(f"   ❌ {t2}(无 user_id)不应有策略,实际 {cols[4]}"); ok = False
    if ok:
        print("      ✅ 表/列/RLS 全部落地正确")
    else:
        print("      ⚠️ 部分校验未通过(去 Dashboard 人工核对)")

    print(f"[3/3] 清理:DROP 两张临时表…")
    drop_sql = f"drop table if exists public.{t1} cascade; drop table if exists public.{t2} cascade;"
    try:
        deploy_mod._supabase_request(
            f"/v1/projects/{ref}/database/query",
            {"query": drop_sql, "read_only": False},
            settings.supabase_access_token,
        )
        print("      ✅ 清理完成")
    except SupabaseAPIError as e:
        print(f"      ⚠️ 清理失败({e});请到 Dashboard 手动删 public.{t1} / public.{t2}")

    print(f"\n=== e2e 完成({'✅ 全通过' if ok else '⚠️ 有未通过项'}) ===")


# ────────────────────────────────────────────────────────────────
# 简易 runner(避免依赖 pytest)
# ────────────────────────────────────────────────────────────────

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


def _run_unit():
    import inspect
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v) and k != "_run_e2e"]
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
    print(f"\n=== Supabase DDL 单测全部通过({len(fns)} 项)===")


if __name__ == "__main__":
    if os.getenv("ATOMS_RUN_SUPABASE_DDL") == "1":
        _run_e2e()
    else:
        _run_unit()
