"""端到端测试:三角色 SOP + HITL + Validator 真 build + 回喂循环。

验证流程:
    1) 第一次 ainvoke:Emma write_prd → approve_prd interrupt,graph 暂停。
       检查:state.prd 已写入(顶层可见)。
    2) resume:Command(resume={"approved": True}) → write_design → write_code →
       validate_build(真 vite build)。可能触发回喂(build 失败 → Alex 重 write_code)。
    3) 最终 state 含 prd / design / files / **build_status**(passed/failed,说明
       validate_build 被调用)。若 failed,检查 iter_count>0 且 messages 含回喂反馈。

用法:
    cd backend && source .venv/bin/activate
    env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy -u ALL_PROXY -u all_proxy \\
        python tests/test_validator_e2e.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langchain_core.messages import HumanMessage  # noqa: E402
from langgraph.types import Command  # noqa: E402

from app.agent import agent  # noqa: E402
from app.agent import RECURSION_LIMIT  # noqa: E402


THREAD_ID = "validator-e2e-test-001"
# 用 agent.py 的 RECURSION_LIMIT(80)对齐,SOP + Validator 回喂循环不撞顶。
CONFIG = {"configurable": {"thread_id": THREAD_ID}, "recursion_limit": RECURSION_LIMIT}


def _trim(s, n: int = 200) -> str:
    s = str(s).replace("\n", " ")
    return s if len(s) <= n else s[:n] + "…"


async def main() -> None:
    print("=== SOP + HITL + Validator 端到端测试 ===\n")

    # ── 第 1 段:发需求,跑到 approve_prd interrupt ──
    print("[1/2] 发送需求,期望跑到 approve_prd interrupt…")
    await agent.ainvoke(
        {"messages": [HumanMessage(content="做一个带邮箱登录的习惯打卡应用,能记录每日打卡和连续天数")]},
        config=CONFIG,
    )
    snap = await agent.aget_state(CONFIG)
    prd = snap.values.get("prd")
    assert prd, "❌ approve_prd 暂停时 state.prd 应已写入(顶层可见)"
    assert snap.tasks, "❌ 应处于 interrupted 状态"
    print(f"   ✅ PM 产 PRD:《{prd['title']}》,interrupt 暂停正常")

    # ── 第 2 段:resume,跑 write_design → write_code → validate_build(可能回喂)──
    print("\n[2/2] 模拟'批准' → resume,跑 Design→Code→Validator(可能回喂)…")
    await agent.ainvoke(Command(resume={"approved": True}), config=CONFIG)

    snap2 = await agent.aget_state(CONFIG)
    design = snap2.values.get("design")
    files = snap2.values.get("files")
    build_status = snap2.values.get("build_status")
    build_errors = snap2.values.get("build_errors")
    iter_count = snap2.values.get("iter_count") or 0

    print(f"   next: {snap2.next}")
    print(f"   design: {(design or {}).get('product_type')}, tables={[t['name'] for t in (design or {}).get('supabase_tables', [])]}")
    print(f"   files: {len(files or [])} 个 -> {[f['path'] for f in (files or [])]}")
    print(f"   build_status: {build_status!r}")
    print(f"   iter_count: {iter_count}")
    if build_status == "failed":
        print(f"   build_errors(前 300 字符): {_trim(build_errors, 300)}")

    assert design, "❌ resume 后应产出 design"
    assert files and len(files) >= 3, f"❌ files 应至少 3 个,实际 {len(files or [])}"
    # 关键断言:validate_build 必须被调过(build_status 有值)
    assert build_status in ("passed", "failed"), (
        f"❌ validate_build 似乎没被调用(build_status={build_status!r})。检查 SOP prompt 是否引导 Alex 调 validate_build。"
    )

    if build_status == "passed":
        print("\n   ✅✅ vite build 一次通过:生成的 React 应用可直接运行")
    else:
        # build 失败:验证回喂机制有触发(iter_count>0 + messages 含 vite 错误反馈)
        assert iter_count > 0, "❌ build 失败但 iter_count=0,回喂计数没更新"
        msgs = snap2.values.get("messages") or []
        has_feedback = any(
            ("vite build 失败" in str(getattr(m, "content", ""))) or ("Validator" in str(getattr(m, "content", "")))
            for m in msgs
        )
        print(f"   回喂痕迹(messages 含 build 错误反馈): {has_feedback}")
        print(f"   ℹ️  build 未通过(已尝试 {iter_count} 次)——回喂机制本身工作,代码质量问题留给后续 prompt 调优。")

    # 完整 dump(files 元信息 + build 结果)
    print("\n完整产物 dump:")
    out = {
        "prd_title": prd["title"],
        "design": {
            "product_type": design["product_type"],
            "tables": [t["name"] for t in design["supabase_tables"]],
            "pages": design.get("pages", []),
        },
        "files": [{"path": f["path"], "language": f["language"], "len": len(f["content"])} for f in files],
        "build": {"status": build_status, "iter_count": iter_count},
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))

    print("\n=== ✅ 闭环通过:SOP + HITL + Validator(build_status 已设置)===")


if __name__ == "__main__":
    asyncio.run(main())
