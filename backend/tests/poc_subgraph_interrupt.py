"""POC:验证 subgraph 内的 interrupt() 能冒泡到外层 StateGraph,且 Command(resume) 可恢复。

拓扑:外层 StateGraph 把一个内层 compiled subgraph 作为节点,内层节点调 interrupt()。

验证点:
  - 第 1 段:跑到内层 interrupt → 外层 aget_state(config).tasks[*].interrupts 能看到
    冒泡上来的 interrupt,且 next 停在 subgraph 所属的外层节点上。
  - 第 2 段:Command(resume={...}) → resume payload 透传进 subgraph,继续跑到后续节点。

⚠️ Caveat:本脚本只覆盖 interrupt 的冒泡与恢复,**不**覆盖"subgraph 内写入的 state
  在 interrupt 暂停期间是否反映到顶层 state.values"——后者取决于 subgraph 节点是否
  完成、state 是否 merge 回 parent,需另行验证(见 LangGraph subgraph state 可见性)。
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from typing_extensions import TypedDict  # noqa: E402

from langgraph.graph.state import StateGraph, START, END  # noqa: E402
from langgraph.checkpoint.memory import MemorySaver  # noqa: E402
from langgraph.types import Command, interrupt  # noqa: E402


class St(TypedDict):
    msg: str
    approved: bool


# ── 内层 subgraph:模拟 create_agent 内部 tool 的 interrupt 行为 ──
def inner_pause(state: St) -> St:
    # 模拟 copilotkit_interrupt(内部就是 LangGraph interrupt())
    resp = interrupt({"question": "批准吗?"})
    approved = bool(resp) and (resp.get("approved") is True if isinstance(resp, dict) else True)
    return {"approved": approved, "msg": state["msg"] + " → resumed"}


inner = StateGraph(St)
inner.add_node("inner_pause", inner_pause)
inner.add_edge(START, "inner_pause")
inner.add_edge("inner_pause", END)
inner_graph = inner.compile()  # checkpointer=None → 继承父 checkpointer(per-invocation)


# ── 外层 StateGraph:把 subgraph 当节点 + 一个后置节点 ──
def after(state: St) -> St:
    return {"msg": state["msg"] + " | after-node-ran"}


parent = StateGraph(St)
parent.add_node("agent", inner_graph)   # subgraph 直接 add_node(共享 state keys)
parent.add_node("after", after)
parent.add_edge(START, "agent")
parent.add_edge("agent", "after")
parent.add_edge("after", END)

graph = parent.compile(checkpointer=MemorySaver())

CFG = {"configurable": {"thread_id": "poc-1"}}


async def main() -> None:
    print("=== POC:subgraph 内 interrupt 透传到顶层 graph ===\n")

    # 第 1 段:跑到 inner 的 interrupt
    await graph.ainvoke({"msg": "hi", "approved": False}, config=CFG)
    snap = await graph.aget_state(CFG)
    print("next:", snap.next)
    print("tasks:", len(snap.tasks))
    for t in snap.tasks:
        for ir in (t.interrupts or []):
            print("  interrupt.value:", ir.value)
    has_interrupt = any(t.interrupts for t in snap.tasks)
    assert has_interrupt, "❌ 顶层 graph 应能看到 subgraph 冒泡上来的 interrupt"
    assert snap.next and "agent" in snap.next, f"❌ 应停在 agent 节点内部,next={snap.next}"
    print("   ✅ subgraph 内 interrupt 冒泡到顶层 aget_state.tasks[*].interrupts")

    # 第 2 段:resume(模拟前端 resolve({"approved": True}))
    await graph.ainvoke(Command(resume={"approved": True}), config=CFG)
    snap2 = await graph.aget_state(CFG)
    print("\nresume 后 next:", snap2.next)
    print("最终 msg:", snap2.values.get("msg"))
    print("approved:", snap2.values.get("approved"))
    assert snap2.values.get("approved") is True, "❌ resume payload 应透传到 subgraph"
    assert "after-node-ran" in snap2.values.get("msg", ""), "❌ resume 后应继续跑到 after 节点"
    print("   ✅ Command(resume) 透传到 subgraph + 继续执行后续节点")

    print("\n=== ✅ POC 通过:subgraph 内 interrupt 冒泡到外层 StateGraph ===")


if __name__ == "__main__":
    asyncio.run(main())
