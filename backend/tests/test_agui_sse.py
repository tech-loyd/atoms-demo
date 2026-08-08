"""AG-UI 协议层端到端测试:POST /api/copilotkit 的 SSE 事件流 + HITL。

验证:
    1) 第一段 SSE:发需求 → TEXT_MESSAGE → TOOL_CALL(write_prd)→ STATE_SNAPSHOT(prd)→ OnInterrupt(approve_prd)→ RUN_FINISHED
    2) 第二段 SSE(模拟前端 resume):forwarded_props={"command":{"resume":{"approved":true}}}
       → TOOL_CALL(write_design)→ STATE_SNAPSHOT(design)→ TOOL_CALL(write_code)
       → STATE_SNAPSHOT(files)→ **TOOL_CALL(validate_build)→ STATE_SNAPSHOT(build_status)**
       → RUN_FINISHED

这给前端 agent 提供 useInterrupt 契约依据:后端发的是 OnInterrupt CustomEvent
(ag-ui-langgraph legacy flow),前端用 useInterrupt(legacy on_interrupt)接收,
resolve(payload) 触发下一次请求带 forwarded_props.command.resume。

额外断言:第二段 SSE 应出现 validate_build 的 TOOL_CALL,且某条
STATE_SNAPSHOT 的 state.build_status ∈ {passed, failed}。

用法:
    cd backend && source .venv/bin/activate
    env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy -u ALL_PROXY -u all_proxy \
        python tests/test_agui_sse.py
"""
from __future__ import annotations

import asyncio
import json
import uuid

import httpx

URL = "http://localhost:8000/api/copilotkit"


def _mk_payload(thread_id: str, user_text: str | None, forwarded_props: dict | None = None) -> dict:
    msgs = []
    if user_text:
        msgs.append({"role": "user", "content": user_text, "id": f"u-{uuid.uuid4().hex[:8]}"})
    return {
        "thread_id": thread_id,
        "run_id": str(uuid.uuid4()),
        "messages": msgs,
        "tools": [],
        "context": [],
        "state": None,
        "forwarded_props": forwarded_props or {},
    }


async def _post_sse(payload: dict) -> list[dict]:
    events: list[dict] = []
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("POST", URL, json=payload) as resp:
            assert resp.status_code == 200, f"HTTP {resp.status_code}: {await resp.aread()[:300]}"
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                raw = line[6:]
                try:
                    events.append(json.loads(raw))
                except json.JSONDecodeError:
                    events.append({"_raw": raw})
    return events


def _snap_state(ev: dict) -> dict:
    """STATE_SNAPSHOT 事件的 state 在 'snapshot' 字段(ag-ui-protocol 0.1.19)。"""
    return ev.get("snapshot") or ev.get("state") or {}


def _summarize(events: list[dict], tag: str) -> None:
    print(f"\n━━━ {tag}:收到 {len(events)} 个 SSE 事件(只列关键)━━")
    SKIP_TYPES = {
        "RAW", "TOOL_CALL_ARGS", "TOOL_CALL_CHUNK", "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_CHUNK", "STEP_STARTED", "STEP_FINISHED",
        "MESSAGES_SNAPSHOT", "STATE_DELTA", "ACTIVITY_DELTA", "ACTIVITY_SNAPSHOT",
    }
    for ev in events:
        t = ev.get("type", "?")
        if t in SKIP_TYPES:
            continue
        if t == "TEXT_MESSAGE_START":
            print(f"  {t:24s} role={ev.get('role')} id={ev.get('id','')[:12]}")
        elif t == "TEXT_MESSAGE_END":
            print(f"  {t:24s} id={ev.get('id','')[:12]}")
        elif t == "TOOL_CALL_START":
            print(f"  {t:24s} tool={ev.get('toolCallName')} id={ev.get('toolCallId','')[:12]}")
        elif t == "TOOL_CALL_END":
            print(f"  {t:24s} tool={ev.get('toolCallName')}")
        elif t == "STATE_SNAPSHOT":
            s = _snap_state(ev)
            prd_title = (s.get("prd") or {}).get("title") if s.get("prd") else None
            n_files = len(s.get("files")) if s.get("files") else 0
            n_tables = len((s.get("design") or {}).get("supabase_tables")) if s.get("design") else 0
            build_st = s.get("build_status")
            print(f"  {t:24s} prd_title={prd_title!r} design_tables={n_tables} files={n_files} build_status={build_st!r}")
        elif t == "CUSTOM":
            name = ev.get("name")
            val = str(ev.get("value", ""))[:100]
            print(f"  CUSTOM/{name:18s} {val}")
        else:
            print(f"  {t:24s} {str(ev)[:100]}")


async def main() -> None:
    print("=== AG-UI 协议层 SOP + HITL 测试 ===")
    thread = f"agui-{uuid.uuid4().hex[:6]}"

    # ── 第一段:发需求,期望跑到 approve_prd 的 interrupt ──
    print(f"\n[1/2] POST 需求(thread={thread}),期望 SSE 流跑到 OnInterrupt…")
    ev1 = await _post_sse(_mk_payload(thread, "做一个带邮箱登录的习惯打卡应用,记录每日打卡和连续天数"))
    _summarize(ev1, "第一段(应含 write_prd + OnInterrupt)")

    types1 = [e.get("type") for e in ev1]
    custom_names = [e.get("name") for e in ev1 if e.get("type") == "CUSTOM"]
    has_interrupt = any("interrupt" in str(n).lower() for n in custom_names)
    has_prd = any((_snap_state(e).get("prd")) for e in ev1 if e.get("type") == "STATE_SNAPSHOT")
    assert "RUN_FINISHED" in types1, "第一段应 RUN_FINISHED"
    print(f"   OnInterrupt 出现: {has_interrupt}")
    print(f"   STATE_SNAPSHOT 含 prd: {has_prd}")
    assert has_interrupt, "❌ 第一段应出现 OnInterrupt 事件(approve_prd)"
    assert has_prd, "❌ 第一段 STATE_SNAPSHOT 应含 prd"
    print("   ✅ HITL interrupt 通过 AG-UI SSE 透传")

    # ── 第二段:resume(模拟前端"批准")──
    print(f"\n[2/2] POST resume(thread={thread}, forwarded_props.command.resume={{'approved':true}})…")
    ev2 = await _post_sse(_mk_payload(thread, None, forwarded_props={"command": {"resume": {"approved": True}}}))
    _summarize(ev2, "第二段(应含 write_design + write_code + files)")

    types2 = [e.get("type") for e in ev2]
    snapshot = None
    for e in ev2:
        if e.get("type") == "STATE_SNAPSHOT":
            snapshot = _snap_state(e)
            if snapshot.get("files"):
                break
    has_design = bool(snapshot and snapshot.get("design"))
    has_files = bool(snapshot and snapshot.get("files"))
    assert "RUN_FINISHED" in types2, "第二段应 RUN_FINISHED"
    print(f"   STATE_SNAPSHOT 含 design: {has_design}")
    print(f"   STATE_SNAPSHOT 含 files: {has_files}")
    assert has_design, "❌ 第二段应含 design"
    assert has_files, "❌ 第二段应含 files"

    # 第二段应出现 validate_build 的 TOOL_CALL,且某条 STATE_SNAPSHOT
    # 的 build_status ∈ {passed, failed}。这给前端 Validator 徽标/回喂提示提供 SSE 依据。
    tool_names2 = [
        e.get("toolCallName") for e in ev2
        if e.get("type") in ("TOOL_CALL_START", "TOOL_CALL_END") and e.get("toolCallName")
    ]
    has_validate_call = any("validate_build" in str(n) for n in tool_names2)
    build_status_snap = None
    for e in ev2:
        if e.get("type") == "STATE_SNAPSHOT":
            st = _snap_state(e).get("build_status")
            if st in ("passed", "failed"):
                build_status_snap = st
                break
    print(f"   第二段 TOOL_CALL 列表: {sorted(set(tool_names2))}")
    print(f"   含 validate_build TOOL_CALL: {has_validate_call}")
    print(f"   STATE_SNAPSHOT build_status: {build_status_snap!r}")
    assert has_validate_call, "❌ 第二段应含 validate_build 的 TOOL_CALL"
    assert build_status_snap in ("passed", "failed"), (
        f"❌ 第二段 STATE_SNAPSHOT 应含 build_status(passed/failed),实际 {build_status_snap!r}"
    )
    print("   ✅ validate_build TOOL_CALL + build_status STATE_SNAPSHOT 通过 AG-UI SSE 透传")
    print("   ✅ resume 后 Design + files 通过 AG-UI SSE 透传")

    print("\n=== ✅ AG-UI 协议层闭环验证通过(前端可用此 SSE 契约)===")


if __name__ == "__main__":
    asyncio.run(main())
