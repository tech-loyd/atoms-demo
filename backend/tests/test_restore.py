"""刷新恢复(restore)测试:验证 action="restore" 只回吐 state/messages 快照,不推进 graph。

模拟"刷新已有会话":先把一个含 prd/files 的 state 写进 checkpointer,再用
forwarded_props.action="restore" 跑一轮 agui_agent.run,断言:
  - 产出 RUN_STARTED + STATE_SNAPSHOT + MESSAGES_SNAPSHOT + RUN_FINISHED;
  - STATE_SNAPSHOT 含之前写入的 prd / files(证明从 checkpointer 拉回了历史 state);
  - 不含 TOOL_CALL / TEXT_MESSAGE(短路成功,没有推进 graph、没有调 model)。

用法:
    cd backend && source .venv/bin/activate
    env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy -u ALL_PROXY -u all_proxy \
        python tests/test_restore.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid

# 确保能 import app.*(从 backend/ 跑)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ag_ui.core import EventType, RunAgentInput  # noqa: E402

from app.agent import RECURSION_LIMIT, agent  # noqa: E402
from app.main import DeployAwareLangGraphAGUIAgent  # noqa: E402

THREAD_ID = "restore-test-001"
CONFIG = {"configurable": {"thread_id": THREAD_ID}, "recursion_limit": RECURSION_LIMIT}

# 种子 state:模拟"刷新前已生成 PRD + 代码"。
SEEDED_PRD = {
    "title": "测试应用",
    "summary": "用于验证 restore 短路的种子数据",
    "features": ["功能 A"],
    "acceptanceChecks": ["验收 1"],
}
SEEDED_FILES = [
    {
        "path": "src/App.tsx",
        "content": "export default function App(){return null}",
        "language": "tsx",
        "status": "done",
    }
]


async def main() -> None:
    print("=== restore 短路测试 ===\n")

    # 1) 往 checkpointer 塞一份"已有会话"的 state(模拟刷新前已生成 PRD + 代码)
    print("[1/2] 写入种子 state(prd + files)…")
    await agent.aupdate_state(
        CONFIG, {"requirement": "测试", "prd": SEEDED_PRD, "files": SEEDED_FILES}
    )
    snap = await agent.aget_state(CONFIG)
    assert snap.values.get("prd"), "种子 prd 未写入"
    assert snap.values.get("files"), "种子 files 未写入"
    print(
        "   checkpointer 现有 prd.title="
        f"{snap.values['prd']['title']!r}, files={len(snap.values['files'])} 个"
    )

    # 2) 构造 agui_agent + restore 输入,跑一轮
    agui_agent = DeployAwareLangGraphAGUIAgent(
        name="default",
        graph=agent,
        description="test",
        config={"recursion_limit": RECURSION_LIMIT},
    )
    inp = RunAgentInput(
        thread_id=THREAD_ID,
        run_id=str(uuid.uuid4()),
        messages=[],
        tools=[],
        context=[],
        state=None,
        forwarded_props={"action": "restore"},
    )

    print("\n[2/2] 触发 action=restore 的 run,收集事件…")
    events = [ev async for ev in agui_agent.run(inp)]
    types = [e.type for e in events]
    print(
        "   事件类型序列:",
        [t.value if hasattr(t, "value") else t for t in types],
    )

    # 3) 断言:短路基线事件齐全
    assert EventType.RUN_STARTED in types, "❌ restore 应发 RUN_STARTED"
    assert EventType.RUN_FINISHED in types, "❌ restore 应发 RUN_FINISHED"
    assert EventType.STATE_SNAPSHOT in types, "❌ restore 应发 STATE_SNAPSHOT"
    assert EventType.MESSAGES_SNAPSHOT in types, "❌ restore 应发 MESSAGES_SNAPSHOT"

    # 4) STATE_SNAPSHOT 含种子 prd/files(证明从 checkpointer 拉回了历史 state)
    restored_state = None
    for e in events:
        if e.type == EventType.STATE_SNAPSHOT:
            restored_state = getattr(e, "snapshot", None) or {}
            if restored_state.get("prd"):
                break
    assert restored_state, "❌ 未拿到 STATE_SNAPSHOT 的 state"
    assert restored_state.get("prd", {}).get("title") == SEEDED_PRD["title"], (
        "❌ restore 的 prd 不匹配种子"
    )
    assert restored_state.get("files"), "❌ restore 的 files 为空"
    print(
        f"   restore 回吐 prd.title={restored_state['prd']['title']!r}, "
        f"files={len(restored_state['files'])} 个 ✅"
    )

    # 5) 断言:没推进 graph —— 无 TOOL_CALL / TEXT_MESSAGE(没调 model,没跑工具)
    progressed = [
        t for t in types if t in (EventType.TOOL_CALL_START, EventType.TEXT_MESSAGE_START)
    ]
    assert not progressed, f"❌ restore 不该推进 graph,却出现 {progressed}"

    print("\n=== ✅ restore 短路通过:刷新恢复只回吐快照、不推进 graph ===")


if __name__ == "__main__":
    asyncio.run(main())
