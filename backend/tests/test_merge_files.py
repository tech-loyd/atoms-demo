"""_merge_files 单元测试(update_code 的安全核心:按 path 合并,未提及文件保留)。

纯函数,不调 LLM,秒级。验证"用户只改一个文件 → 其余文件原样保留"这一不变式。
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.tools import _merge_files


def _f(path, content, language="tsx"):
    """构造一个文件 dict(模拟 state.files 元素 / parse_files_markdown 产物)。"""
    return {"path": path, "content": content, "language": language, "status": "done"}


def test_overwrite_same_path():
    """changed 覆盖同 path 的 existing,内容更新为 changed 的版本。"""
    existing = [_f("src/App.tsx", "old"), _f("src/lib/supabase.ts", "keep")]
    changed = [{"path": "src/App.tsx", "content": "new", "language": "tsx"}]
    merged = _merge_files(existing, changed)
    by_path = {f["path"]: f for f in merged}
    assert by_path["src/App.tsx"]["content"] == "new", "同 path 应被 changed 覆盖"
    assert by_path["src/lib/supabase.ts"]["content"] == "keep", "未提及文件应保留"
    print("✅ test_overwrite_same_path 通过")


def test_keep_unmentioned_files():
    """安全核心:用户只改一个文件,其余文件内容原样保留(不被无意改动)。"""
    existing = [
        _f("src/App.tsx", "app"),
        _f("src/components/Dashboard.tsx", "dashboard"),
        _f("src/components/Stats.tsx", "stats"),
        _f("src/lib/supabase.ts", "supabase"),
    ]
    # 用户只想改 Dashboard
    changed = [{"path": "src/components/Dashboard.tsx", "content": "dashboard v2", "language": "tsx"}]
    merged = _merge_files(existing, changed)
    assert len(merged) == 4, f"文件总数应不变(4),实际 {len(merged)}"
    by_path = {f["path"]: f for f in merged}
    assert by_path["src/App.tsx"]["content"] == "app"
    assert by_path["src/components/Dashboard.tsx"]["content"] == "dashboard v2"
    assert by_path["src/components/Stats.tsx"]["content"] == "stats"
    assert by_path["src/lib/supabase.ts"]["content"] == "supabase"
    print("✅ test_keep_unmentioned_files 通过")


def test_add_new_file():
    """changed 含 existing 没有的 path → 追加为新文件(迭代时加新组件)。"""
    existing = [_f("src/App.tsx", "app")]
    changed = [{"path": "src/components/New.tsx", "content": "new comp", "language": "tsx"}]
    merged = _merge_files(existing, changed)
    by_path = {f["path"]: f for f in merged}
    assert len(merged) == 2, f"应追加为 2 个文件,实际 {len(merged)}"
    assert by_path["src/components/New.tsx"]["content"] == "new comp"
    print("✅ test_add_new_file 通过")


def test_empty_changed_returns_existing():
    """changed 为空 → 返回 existing 原样。"""
    existing = [_f("src/App.tsx", "app")]
    merged = _merge_files(existing, [])
    assert merged == existing
    print("✅ test_empty_changed_returns_existing 通过")


def test_existing_empty_returns_changed():
    """existing 为空 + changed → 返回 changed。"""
    changed = [{"path": "src/App.tsx", "content": "app", "language": "tsx"}]
    merged = _merge_files([], changed)
    assert merged == changed
    print("✅ test_existing_empty_returns_changed 通过")


def test_skip_empty_path_entries():
    """existing / changed 里 path 为空的项被跳过(不污染合并结果)。"""
    existing = [_f("src/App.tsx", "app"), {"path": "", "content": "x", "language": "ts"}]
    changed = [{"path": "src/App.tsx", "content": "v2", "language": "tsx"}, {"path": "", "content": "y", "language": "ts"}]
    merged = _merge_files(existing, changed)
    assert all(f.get("path") for f in merged), "不应有空 path 项"
    by_path = {f["path"]: f for f in merged}
    assert by_path["src/App.tsx"]["content"] == "v2"
    print("✅ test_skip_empty_path_entries 通过")


if __name__ == "__main__":
    test_overwrite_same_path()
    test_keep_unmentioned_files()
    test_add_new_file()
    test_empty_changed_returns_existing()
    test_existing_empty_returns_changed()
    test_skip_empty_path_entries()
    print("\n=== _merge_files 全部通过 ===")
