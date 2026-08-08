"""三角色 SOP + HITL 端到端测试(直接调 graph,绕过 AG-UI 协议层)。

验证流程:
    1) 第一次 ainvoke:Emma 调 write_prd → approve_prd 触发 interrupt,graph 暂停。
       检查:state.prd 已写入;state 是 interrupted。
    2) resume:用 Command(resume={"approved": True}) 继续。
       检查:Bob 的 write_design → state.design;Alex 的 write_code → state.files。
    3) 最终 state 含 prd / design / files 三张"卡片"数据。
       agent 还会跑 validate_build,故另断言 build_status 已被设置(passed/failed)。

用法:
    cd backend && source .venv/bin/activate
    env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy -u ALL_PROXY -u all_proxy \
        python tests/test_sop_hitl.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

# 确保能 import app.*(从 backend/ 跑)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import HumanMessage  # noqa: E402
from langgraph.types import Command  # noqa: E402

from app.agent import agent  # noqa: E402
from app.agent import RECURSION_LIMIT  # noqa: E402


THREAD_ID = "sop-hitl-test-001"
# 用 agent.py 的 RECURSION_LIMIT(80)对齐,SOP + 可能的 Validator 回喂不撞顶。
CONFIG = {"configurable": {"thread_id": THREAD_ID}, "recursion_limit": RECURSION_LIMIT}


def _trim(s: str, n: int = 160) -> str:
    s = str(s).replace("\n", " ")
    return s if len(s) <= n else s[:n] + "…"


async def main() -> None:
    print("=== SOP + HITL 测试 ===\n")

    # ── 第 1 段:发需求,跑到 interrupt(should pause at approve_prd)──
    print("[1/3] 发送需求,期望跑到 approve_prd 的 interrupt 暂停…")
    await agent.ainvoke(
        {"messages": [HumanMessage(content="做一个带邮箱登录的习惯打卡应用,能记录每日打卡和连续天数")]},
        config=CONFIG,
    )

    snap = await agent.aget_state(CONFIG)
    print("   next node:", snap.next)
    print("   interrupted:", bool(snap.tasks))
    for t in snap.tasks:
        for ir in (t.interrupts or []):
            val = getattr(ir, "value", None)
            print("   interrupt.value:", _trim(val, 220))

    prd = snap.values.get("prd")
    design = snap.values.get("design")
    files = snap.values.get("files")
    print("\n   state.prd:", _trim(prd, 220) if prd else "(空)")
    print("   state.design:", design if design is None else "(已写入,不该这么早)")
    print("   state.files:", files if files is None else "(已写入,不该这么早)")

    assert prd, "❌ approve_prd 暂停时 state.prd 应已写入"
    assert not design and not files, "❌ 批准前不该有 design / files"
    assert snap.tasks, "❌ 应处于 interrupted 状态"
    print("   ✅ PM 产 PRD + interrupt 暂停 正常")

    # ── 第 2 段:resume(模拟前端"批准")──
    print("\n[2/3] 模拟前端'批准' → Command(resume={'approved': True}) 继续…")
    await agent.ainvoke(Command(resume={"approved": True}), config=CONFIG)

    snap2 = await agent.aget_state(CONFIG)
    design2 = snap2.values.get("design")
    files2 = snap2.values.get("files")
    build_status2 = snap2.values.get("build_status")
    print("   next node:", snap2.next)
    print("   state.design:", _trim(design2, 260) if design2 else "(空)")
    print("   state.files:", f"{len(files2)} 个文件" if files2 else "(空)")
    if files2:
        print("   文件列表:", [f["path"] for f in files2])

    assert design2, "❌ resume 后 Bob 应产出 design"
    assert files2, "❌ resume 后 Alex 应产出 files"
    assert len(files2) >= 3, f"❌ files 应至少 3 个,实际 {len(files2)}"
    # agent 在 write_code 后会调 validate_build,build_status 必须被写过。
    assert build_status2 in ("passed", "failed"), (
        f"❌ validate_build 似乎没被调用(build_status={build_status2!r})"
    )
    print(f"   state.build_status: {build_status2!r}(validate_build 已执行)")
    print("   ✅ resume 后 Bob 产 Design + Alex 产 files + Validator 执行 正常")

    # ── 第 3 段:完整性 dump ──
    print("\n[3/3] 完整产物 dump:")
    out = {
        "prd": prd,
        "design": {
            "product_type": design2["product_type"],
            "tables": [t["name"] for t in design2["supabase_tables"]],
            "pages": design2.get("pages", []),
        },
        "files": [{"path": f["path"], "language": f["language"], "len": len(f["content"])} for f in files2],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))

    print("\n=== ✅ 全部通过:三角色 SOP + HITL 闭环 ===")


if __name__ == "__main__":
    asyncio.run(main())
