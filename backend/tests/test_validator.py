"""Validator 单元测试:run_build + validate_build tool 的成功/失败/iter 上限/回喂语义。

不调 LLM,直接测纯构建逻辑 + tool 的 Command 返回(秒级,~3-4s)。

用法:
    cd backend && source .venv/bin/activate
    python tests/test_validator.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.validator import MAX_BUILD_ITERS, run_build, validate_build  # noqa: E402

TEMPLATE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "templates", "react-supabase-starter",
)


def _tpl(name: str) -> str:
    with open(os.path.join(TEMPLATE, name), encoding="utf-8") as f:
        return f.read()


def test_run_build_success():
    """模板占位 main.tsx + App.tsx 应 build 通过。"""
    files = [
        {"path": "src/main.tsx", "content": _tpl("src/main.tsx")},
        {"path": "src/App.tsx", "content": _tpl("src/App.tsx")},
    ]
    ok, out = run_build(files)
    assert ok, f"应 build 通过,实际输出:{out}"
    print("✅ test_run_build_success 通过")


def test_run_build_failure_captures_error():
    """import 不存在的模块 → build 失败,output 含 'Could not resolve'。"""
    files = [
        {"path": "src/main.tsx", "content": _tpl("src/main.tsx")},
        {"path": "src/App.tsx", "content": "import { NonExistent } from './no-such-file'\nexport default function App(){ return <NonExistent/> }"},
    ]
    ok, out = run_build(files)
    assert not ok, "应 build 失败"
    assert "Could not resolve" in out or "no-such-file" in out, f"输出应含 resolve 错误:{out[:300]}"
    print("✅ test_run_build_failure_captures_error 通过")


def test_validate_build_success_returns_command():
    """validate_build 成功 → Command.update 含 build_status='passed' + 正向 ToolMessage。"""
    files = [
        {"path": "src/main.tsx", "content": _tpl("src/main.tsx")},
        {"path": "src/App.tsx", "content": _tpl("src/App.tsx")},
    ]
    cmd = validate_build.func(state={"files": files, "iter_count": 0}, tool_call_id="tc-1")
    upd = cmd.update if hasattr(cmd, "update") else cmd.get("update", {})
    assert upd.get("build_status") == "passed", f"应 passed,实际 {upd.get('build_status')}"
    assert upd.get("iter_count") == 1
    assert upd.get("build_errors") is None
    msg = upd["messages"][0]
    assert "通过" in msg.content or "passed" in msg.content.lower()
    assert msg.tool_call_id == "tc-1"
    print("✅ test_validate_build_success_returns_command 通过")


def test_validate_build_failure_sets_feedback_for_alex():
    """validate_build 失败 → build_status='failed' + ToolMessage 含错误 + 重写指令(回喂 Alex)。"""
    files = [
        {"path": "src/main.tsx", "content": _tpl("src/main.tsx")},
        {"path": "src/App.tsx", "content": "import { X } from './missing'\nexport default function App(){ return <X/> }"},
    ]
    cmd = validate_build.func(state={"files": files, "iter_count": 0}, tool_call_id="tc-2")
    upd = cmd.update if hasattr(cmd, "update") else cmd.get("update", {})
    assert upd.get("build_status") == "failed", f"应 failed,实际 {upd.get('build_status')}"
    assert upd.get("iter_count") == 1
    assert "Could not resolve" in upd.get("build_errors", "") or "missing" in upd.get("build_errors", "")
    msg = upd["messages"][0]
    assert "vite build 失败" in msg.content, "ToolMessage 应说明 build 失败"
    assert "write_code" in msg.content, "回喂消息应指示重新调用 write_code"
    print("✅ test_validate_build_failure_sets_feedback_for_alex 通过")


def test_validate_build_iter_exhausted_stops():
    """iter_count 达上限 → 不再 build,返回'已达上限'消息(防止无限回喂)。"""
    files = [
        {"path": "src/main.tsx", "content": _tpl("src/main.tsx")},
        {"path": "src/App.tsx", "content": _tpl("src/App.tsx")},
    ]
    # iter_count 已达 MAX,validate_build 应直接返回停止消息,不跑 build
    cmd = validate_build.func(state={"files": files, "iter_count": MAX_BUILD_ITERS}, tool_call_id="tc-3")
    upd = cmd.update if hasattr(cmd, "update") else cmd.get("update", {})
    assert "build_status" not in upd, "iter 用尽不应再跑 build(不该写 build_status)"
    msg = upd["messages"][0]
    assert "上限" in msg.content, "应提示已达上限"
    print("✅ test_validate_build_iter_exhausted_stops 通过")


def test_validate_build_no_files():
    """state.files 为空 → 友好提示先 write_code(不 build)。"""
    cmd = validate_build.func(state={"files": None, "iter_count": 0}, tool_call_id="tc-4")
    upd = cmd.update if hasattr(cmd, "update") else cmd.get("update", {})
    msg = upd["messages"][0]
    assert "write_code" in msg.content, "应提示先 write_code"
    assert "build_status" not in upd
    print("✅ test_validate_build_no_files 通过")


if __name__ == "__main__":
    test_run_build_success()
    test_run_build_failure_captures_error()
    test_validate_build_success_returns_command()
    test_validate_build_failure_sets_feedback_for_alex()
    test_validate_build_iter_exhausted_stops()
    test_validate_build_no_files()
    print("\n=== Validator 单元测试全部通过 ===")
