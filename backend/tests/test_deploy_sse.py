"""部署触发 SSE 端到端验证(真 AGUI 协议栈 + 真 LLM 路由)。

验证任务契约:"起后端,模拟前端发 forwarded_props={action:"deploy"} → 后端应调
deploy_app(不重跑 SOP)"。

## 思路
跑全量真 SOP(PM→批准→Architect→Engineer→Validator)要 4+ 次 LLM 调用 + 真 vite build,
慢且可能因 LLM 输出质量 build failed。本测**预埋一个已完成 SOP 的 checkpoint**(build_status
= "passed" + 一段连贯对话 ending 于 validate_build 通过),然后 POST forwarded_props.
{action:"deploy"} 到该 thread → 验证 SSE 流里出现 deploy_app 的 TOOL_CALL。

这样确定性验证 **真 AGUI 协议栈 + 真 LLM** 收到 forwarded_props.action=="deploy" 后:
  ① DeployAwareLangGraphAGUIAgent.langgraph_default_merge_state 注入部署 HumanMessage;
  ② 真 LLM(GLM-5.2)按 SOP 第 6 步调 deploy_app(build 已 passed);
  ③ 不重跑 write_prd / write_design / write_code / validate_build。

deploy_app 会真 POST Vercel(VERCEL_TOKEN 已配置)—— 本测**不等轮询结束**,只要 SSE
出现 deploy_app 的 TOOL_CALL 即判定路由打通(避免每次跑烧配额;真部署覆盖在
tests/test_vercel_e2e.py,默认 skip)。

## 用法
    cd backend && source .venv/bin/activate
    env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy -u ALL_PROXY -u all_proxy \\
        python tests/test_deploy_sse.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: E402

from app.agent import agent  # noqa: E402

URL = "http://127.0.0.1:8765/api/copilotkit"
THREAD = f"deploy-sse-{uuid.uuid4().hex[:6]}"
CONFIG = {"configurable": {"thread_id": THREAD}}


async def _seed_completed_sop():
    """预埋一个"已完成 SOP、build passed"的 checkpoint(绕过真 SOP 跑)。"""
    # 一段精简但连贯的 SOP 对话:PM→批准→Architect→Engineer→Validator(build passed)。
    # tool_call_id 严格配对(AIMessage.tool_calls[].id == ToolMessage.tool_call_id),
    # 让 LLM 看到合法的工具调用历史,确信 build 已通过。
    messages = [
        HumanMessage(content="做一个带邮箱登录的习惯打卡应用", id="u-seed-1"),
        AIMessage(
            content="我来整理 PRD 并走批准流程。",
            tool_calls=[{"name": "write_prd", "args": {"requirement": "习惯打卡"}, "id": "tc-prd"}],
            id="a-seed-1",
        ),
        ToolMessage(content='{"title":"习惯打卡","summary":"每日打卡+连续天数"}', tool_call_id="tc-prd", id="t-prd"),
        AIMessage(
            content="PRD 已就绪,请批准。",
            tool_calls=[{"name": "approve_prd", "args": {}, "id": "tc-approve"}],
            id="a-seed-2",
        ),
        ToolMessage(content="用户已批准", tool_call_id="tc-approve", id="t-approve"),
        AIMessage(
            content="设计完成,交给 Alex 写代码。",
            tool_calls=[{"name": "write_design", "args": {}, "id": "tc-design"}],
            id="a-seed-3",
        ),
        ToolMessage(content='{"product_type":"web_app","supabase_tables":[]}', tool_call_id="tc-design", id="t-design"),
        AIMessage(
            content="代码已生成,跑构建校验。",
            tool_calls=[{"name": "write_code", "args": {}, "id": "tc-code"}],
            id="a-seed-4",
        ),
        ToolMessage(content="代码已写入 state.files", tool_call_id="tc-code", id="t-code"),
        AIMessage(
            content="代码写完,跑 vite build。",
            tool_calls=[{"name": "validate_build", "args": {}, "id": "tc-build"}],
            id="a-seed-5",
        ),
        ToolMessage(content="✅ vite build 通过(0.5s),build_status=passed。", tool_call_id="tc-build", id="t-build"),
    ]
    await agent.aupdate_state(CONFIG, {
        "messages": messages,
        "build_status": "passed",
        "prd": {"title": "习惯打卡", "summary": "每日打卡", "features": [], "acceptanceChecks": []},
        "design": {"product_type": "web_app", "supabase_tables": [], "pages": ["Home"]},
        "files": [{"path": "src/App.tsx", "content": "export default function App(){return <div>hi</div>}", "language": "tsx"}],
    })
    snap = await agent.aget_state(CONFIG)
    print(f"   预埋 checkpoint:build_status={snap.values.get('build_status')!r}, "
          f"files={len(snap.values.get('files') or [])} 个,messages={len(snap.values.get('messages') or [])} 条")


def _mk_deploy_payload() -> dict:
    """模拟前端 useDeploy 的 runAgent 请求:forwardedProps.action='deploy',无 chat 消息。"""
    return {
        "thread_id": THREAD,
        "run_id": str(uuid.uuid4()),
        "messages": [],  # 关键:前端 useDeploy 不发 chat 消息,只发 forwardedProps
        "tools": [],
        "context": [],
        "state": None,
        "forwarded_props": {"action": "deploy"},  # ← 确定性部署触发
    }


async def _post_sse(payload: dict) -> list[dict]:
    events: list[dict] = []
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream("POST", URL, json=payload) as resp:
            assert resp.status_code == 200, f"HTTP {resp.status_code}"
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    raw = line[6:]
                    try:
                        events.append(json.loads(raw))
                    except json.JSONDecodeError:
                        events.append({"_raw": raw})
    return events


async def main() -> None:
    print("=== 部署触发 · SSE 端到端(真 AGUI + 真 LLM 路由)===")
    print(f"thread: {THREAD}")

    print("\n[1/2] 预埋已完成 SOP 的 checkpoint(build passed)…")
    await _seed_completed_sop()

    print(f"\n[2/2] POST forwarded_props={{action:'deploy'}}(无 chat 消息)→ 期望 SSE 出现 deploy_app TOOL_CALL…")
    events = await _post_sse(_mk_deploy_payload())

    # 关键判定:deploy_app 的 TOOL_CALL 出现(路由打通)
    tool_calls = [
        e.get("toolCallName") for e in events
        if e.get("type") in ("TOOL_CALL_START", "TOOL_CALL_END") and e.get("toolCallName")
    ]
    # 也检查是否误重跑了 SOP
    sop_tools = {"write_prd", "write_design", "write_code", "validate_build", "approve_prd"}
    deploy_called = any("deploy_app" in str(n) for n in tool_calls)
    sop_rerun = [n for n in tool_calls if n in sop_tools]

    types = [e.get("type") for e in events]
    print(f"   SSE 事件数:{len(events)},含 RUN_FINISHED:{'RUN_FINISHED' in types}")
    print(f"   TOOL_CALL 列表:{sorted(set(tool_calls))}")
    print(f"   ✅ deploy_app 被调:{deploy_called}")
    print(f"   {'✅' if not sop_rerun else '❌'} 未重跑 SOP:{'无 write_prd/design/code/validate_build' if not sop_rerun else sop_rerun}")

    assert deploy_called, "❌ SSE 未出现 deploy_app TOOL_CALL —— forwarded_props.action 路由未打通"
    assert not sop_rerun, f"❌ 误重跑 SOP:{sop_rerun}"
    print("\n=== ✅ SSE 端到端验证通过:forwarded_props.action=='deploy' → deploy_app(不重跑 SOP)===")


if __name__ == "__main__":
    asyncio.run(main())
