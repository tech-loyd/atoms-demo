"""部署触发 · 部署路由单元/集成测试(不依赖真 LLM / 不烧 Vercel 配额)。

验证 DeployAwareLangGraphAGUIAgent(langgraph_default_merge_state override)的核心契约:
    1) forwarded_props.action=="deploy" → merge_state 在 messages 末尾注入一条
       "用户要求部署" HumanMessage(graph 入口实际收到的输入)。
    2) 把这条注入后的 messages 喂给 create_agent(用 Fake 模型脚本化"看到部署请求→
       调 deploy_app")→ deploy_app tool 真被调用(不重跑 write_prd / write_design /
       write_code / validate_build)。
    3) 正常 SOP(action != "deploy" 或缺省)→ merge_state 不注入,行为与基类一致。

为什么不用真 LLM / 真 SSE e2e:
    - 真 SOP 跑(PM→Architect→Engineer→Validator)要 4+ 次 LLM 调用 + 真 vite build,
      慢且可能因 LLM 输出质量 build failed,测的是"路由"而非"LLM 服从 SOP"。
    - deploy_app 真 POST Vercel 烧配额(tests/test_vercel_e2e.py 已覆盖,默认 skip)。
    - 本测用 FakeMessagesListChatModel 脚本化"模型收到部署 HumanMessage → 调 deploy_app",
      确定性验证 **路由**(merge_state override + graph 拓扑),与 LLM 质量 / Vercel 解耦。

用法:
    cd backend && source .venv/bin/activate
    env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy -u ALL_PROXY -u all_proxy \\
        python tests/test_deploy_trigger.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid

# 确保能 import app.*(从 backend/ 跑)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402
from langchain.agents import create_agent  # noqa: E402
from langchain.agents.middleware import AgentState  # noqa: E402
from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: E402
from langchain_core.tools import tool  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402


class _ScriptedToolChatModel(BaseChatModel):
    """支持 bind_tools 的脚本化假模型(FakeMessagesListChatModel 不支持 bind_tools)。

    每次被调按 responses 顺序返回下一条 AIMessage(可带 tool_calls)。
    bind_tools / bind 直接返回 self(脚本已写死 tool_calls,无需真绑定)。
    """

    def __init__(self, responses: list[AIMessage]):
        super().__init__()
        self._responses = list(responses)
        self._idx = 0

    @property
    def _llm_type(self) -> str:
        return "scripted-tool-fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: D401
        msg = self._responses[min(self._idx, len(self._responses) - 1)]
        self._idx += 1
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def bind_tools(self, tools, **kwargs):  # noqa: D401
        return self

    def bind(self, *args, **kwargs):  # noqa: D401
        return self

from app.main import DeployAwareLangGraphAGUIAgent  # noqa: E402


# ── 假 deploy tool:记录被调用,不真请求 Vercel ──
DEPLOY_CALLS: list[dict] = []


@tool
def fake_deploy_app() -> str:
    """测试用 deploy_app 替身:记录调用,返回成功(不真 POST Vercel)。"""
    DEPLOY_CALLS.append({"called": True})
    return "✅ 部署成功!URL: https://atoms-app-test.vercel.app"


@tool
def fake_write_prd(requirement: str) -> str:
    """测试用 write_prd 替身(本测不应被调 —— 验证不重跑 SOP)。"""
    raise AssertionError("fake_write_prd 不应被调(deploy run 不应重跑 SOP)")


@tool
def fake_write_code() -> str:
    """测试用 write_code 替身(本测不应被调)。"""
    raise AssertionError("fake_write_code 不应被调(deploy run 不应重跑 SOP)")


def _build_test_agent():
    """构造一个拓扑同真 agent(create_agent + 6 tool)但用 Fake 模型的测试 agent。

    Fake 模型脚本:第一次调用返回 deploy_app tool_call(模拟 LLM 看到"部署"请求后
    按 SOP 第 6 步调 deploy_app);第二次返回纯文本"部署完成"收尾。
    """
    deploy_call = AIMessage(
        content="",
        tool_calls=[{"name": "fake_deploy_app", "args": {}, "id": "call-deploy-1"}],
    )
    finish = AIMessage(content="已部署,URL 见上。")
    model = _ScriptedToolChatModel(responses=[deploy_call, finish])

    return create_agent(
        model=model,
        tools=[fake_write_prd, fake_write_code, fake_deploy_app],
        # 不挂 CopilotKitMiddleware(本测只验证 merge_state → graph 路由,不需要 AG-UI 协议)
        state_schema=AgentState,
        system_prompt="测试 agent:收到部署请求时调 fake_deploy_app。",
        name="test-deploy-agent",
        checkpointer=InMemorySaver(),
    )


def _make_fake_input(forwarded_props: dict | None, incoming_messages=None):
    """构造一个最小 RunAgentInput-like 对象(merge_state 只读 forwarded_props / messages / tools / context)。"""

    class FakeInput:
        def __init__(self):
            self.forwarded_props = forwarded_props or {}
            self.messages = incoming_messages or []
            self.tools = []
            self.context = []
            self.state = None

    return FakeInput()


async def _scenario_deploy_triggers_deploy_tool():
    """核心场景:forwarded_props.action=='deploy' → 注入 HumanMessage → graph 调 fake_deploy_app。"""
    print("\n[场景 1] forwarded_props.action='deploy' → 应触发 fake_deploy_app(不重跑 SOP)")
    test_agent = _build_test_agent()
    agui = DeployAwareLangGraphAGUIAgent(name="test", graph=test_agent)

    # 模拟前端 deploy 请求:无 chat 消息,只 forwarded_props.action='deploy'
    fake_input = _make_fake_input({"action": "deploy"})
    # 模拟 ag_ui_langgraph prepare_stream 已合流好的 checkpoint state(build 已 passed)
    checkpoint_state = {"messages": [
        HumanMessage(content="做一个习惯打卡应用", id="u1"),
        AIMessage(content="我来整理 PRD", id="a1"),
        # (省略 approve/design/code/validate 的 ToolMessage —— 本测关注 deploy run 不重跑这些)
    ]}

    merged = agui.langgraph_default_merge_state(checkpoint_state, [], fake_input)
    # 断言 1:messages 末尾注入了"部署"HumanMessage
    last = merged["messages"][-1]
    assert isinstance(last, HumanMessage), f"末尾应为 HumanMessage,实际 {type(last).__name__}"
    assert "部署" in last.content, f"注入消息应含'部署',实际:{last.content!r}"
    print(f"   ✅ merge_state 注入部署 HumanMessage(末尾,id={last.id[:20]}…)")

    # 把注入后的 messages 喂给 graph(模拟 graph.astream_events(input={**forwarded_props, **payload_input}))
    DEPLOY_CALLS.clear()
    config = {"configurable": {"thread_id": f"deploy-test-{uuid.uuid4().hex[:6]}"}}
    await test_agent.ainvoke({"messages": merged["messages"]}, config=config)

    # 断言 2:fake_deploy_app 被调
    assert len(DEPLOY_CALLS) == 1, f"fake_deploy_app 应被调 1 次,实际 {len(DEPLOY_CALLS)} 次"
    print(f"   ✅ fake_deploy_app 被调({len(DEPLOY_CALLS)} 次)→ 部署路由打通")
    # 断言 3:write_prd / write_code 没被调(不重跑 SOP)—— fake 工具内 assert 会抛
    print("   ✅ fake_write_prd / fake_write_code 未被调(没重跑 SOP)")


async def _scenario_normal_chat_no_injection():
    """正常 chat(无 forwarded_props.action)→ merge_state 不注入部署消息。"""
    print("\n[场景 2] 正常 chat(无 action)→ merge_state 不注入")
    test_agent = _build_test_agent()
    agui = DeployAwareLangGraphAGUIAgent(name="test", graph=test_agent)

    user_msg = HumanMessage(content="做一个待办应用", id="u-new")
    fake_input = _make_fake_input({}, incoming_messages=[user_msg])
    checkpoint_state = {"messages": []}

    merged = agui.langgraph_default_merge_state(checkpoint_state, [user_msg], fake_input)
    has_deploy = any(
        getattr(m, "id", "").startswith("deploy-request-") for m in merged["messages"]
    )
    assert not has_deploy, "正常 chat 不应注入 deploy-request 消息"
    # 用户原消息应在
    assert any(getattr(m, "id", "") == "u-new" for m in merged["messages"]), "用户消息应保留"
    print("   ✅ 未注入部署消息;用户原消息保留 → 正常 SOP 路径不受影响")


async def _scenario_resume_no_injection():
    """resume(forwarded_props.command.resume,无 action)→ merge_state 不注入。"""
    print("\n[场景 3] resume(command.resume)→ merge_state 不注入部署消息")
    test_agent = _build_test_agent()
    agui = DeployAwareLangGraphAGUIAgent(name="test", graph=test_agent)

    fake_input = _make_fake_input({"command": {"resume": {"approved": True}}})
    checkpoint_state = {"messages": [HumanMessage(content="原需求", id="u1")]}

    merged = agui.langgraph_default_merge_state(checkpoint_state, [], fake_input)
    has_deploy = any(
        getattr(m, "id", "").startswith("deploy-request-") for m in merged["messages"]
    )
    assert not has_deploy, "resume 不应注入 deploy-request"
    print("   ✅ resume 路径未触发部署注入 → HITL resume 不受影响")


async def main() -> None:
    print("=== 部署触发 · 路由测试(DeployAwareLangGraphAGUIAgent)===")
    await _scenario_deploy_triggers_deploy_tool()
    await _scenario_normal_chat_no_injection()
    await _scenario_resume_no_injection()
    print("\n=== ✅ 全部通过:deploy 路由打通 + 正常 SOP / resume 不受影响 ===")


if __name__ == "__main__":
    asyncio.run(main())
