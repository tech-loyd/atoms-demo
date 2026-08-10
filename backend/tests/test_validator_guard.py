"""scan_supabase_when_no_tables 单元测试(硬护栏:design 无表时禁止代码用 Supabase)。

纯函数,不调 LLM/Node,秒级。验证"design 无表 → 代码必须纯 localStorage"这一不变式:
design.supabase_tables 为空时,任何文件出现 supabase 痕迹即判违规(对应面试反馈:计数器
被 Alex 塞 Supabase + counters 表 → 404 → "离线演示"降级)。design 有表则放行。
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.validator import scan_supabase_when_no_tables


def _f(path, content, language="tsx"):
    """构造一个文件 dict(模拟 state.files 元素)。"""
    return {"path": path, "content": content, "language": language, "status": "done"}


# design 形状
_NO_TABLES = {"supabase_tables": []}
_HAS_TABLES = {"supabase_tables": [
    {"name": "habits", "fields": [{"name": "id", "type": "uuid", "pk": True}]}
]}


def test_no_tables_with_supabase_import():
    """design 无表 + 代码 import supabase → 检出违规。"""
    files = [_f("src/App.tsx", "import { supabase } from '@/lib/supabase'\nexport default () => null")]
    offenders = scan_supabase_when_no_tables(files, _NO_TABLES)
    assert offenders == ["src/App.tsx"], f"应检出 App.tsx,实际 {offenders}"
    print("✅ test_no_tables_with_supabase_import 通过")


def test_no_tables_with_from_call_and_createclient():
    """design 无表 + 代码含 .from()/createClient → 检出(计数器会话的真实形态)。"""
    files = [
        _f("src/lib/supabase.ts", "import { createClient } from '@supabase/supabase-js'\nexport const supabase = createClient('x','y')"),
        _f("src/api.ts", "const { data } = await supabase.from('counters').select()"),
    ]
    offenders = scan_supabase_when_no_tables(files, _NO_TABLES)
    assert set(offenders) == {"src/lib/supabase.ts", "src/api.ts"}, f"两个文件都应检出,实际 {offenders}"
    print("✅ test_no_tables_with_from_call_and_createclient 通过")


def test_no_tables_pure_localstorage():
    """design 无表 + 纯 localStorage 代码(无 supabase 痕迹)→ 放行(不检出)。"""
    files = [_f("src/App.tsx", """
import { useEffect, useState } from 'react'
export default function Counter() {
  const [n, setN] = useState(() => Number(localStorage.getItem('count') || 0))
  useEffect(() => localStorage.setItem('count', String(n)), [n])
  return <button onClick={() => setN(n+1)}>{n}</button>
}
""")]
    offenders = scan_supabase_when_no_tables(files, _NO_TABLES)
    assert offenders == [], f"纯 localStorage 不应检出,实际 {offenders}"
    print("✅ test_no_tables_pure_localstorage 通过")


def test_with_tables_supabase_allowed():
    """design 有表 + 代码含 supabase → 放行(supabase 在有表应用里合法)。"""
    files = [
        _f("src/lib/supabase.ts", "import { createClient } from '@supabase/supabase-js'\nexport const supabase = createClient('x','y')"),
        _f("src/api.ts", "const { data } = await supabase.from('habits').select()"),
    ]
    offenders = scan_supabase_when_no_tables(files, _HAS_TABLES)
    assert offenders == [], f"design 有表应放行,实际 {offenders}"
    print("✅ test_with_tables_supabase_allowed 通过")


def test_design_none_treated_as_no_tables():
    """design=None / 缺 supabase_tables → 等同无表,代码含 supabase → 检出。"""
    files = [_f("src/App.tsx", "import { supabase } from '@/lib/supabase'")]
    assert scan_supabase_when_no_tables(files, None) == ["src/App.tsx"]
    assert scan_supabase_when_no_tables(files, {}) == ["src/App.tsx"]
    print("✅ test_design_none_treated_as_no_tables 通过")


def test_case_insensitive_and_nonstring_skipped():
    """大小写不敏感(Supabase/CREATECLIENT),非字符串 content 跳过不崩。"""
    files = [
        _f("src/a.ts", "// uses Supabase backend"),     # 大写 S → 检出
        _f("src/b.ts", "const x = CREATECLIENT()"),      # 大写 → 检出
        {"path": "src/c.ts", "content": None, "language": "tsx"},  # 非 str → 跳过
    ]
    offenders = scan_supabase_when_no_tables(files, _NO_TABLES)
    assert set(offenders) == {"src/a.ts", "src/b.ts"}, f"大小写不敏感 + 非 str 跳过,实际 {offenders}"
    print("✅ test_case_insensitive_and_nonstring_skipped 通过")


if __name__ == "__main__":
    test_no_tables_with_supabase_import()
    test_no_tables_with_from_call_and_createclient()
    test_no_tables_pure_localstorage()
    test_with_tables_supabase_allowed()
    test_design_none_treated_as_no_tables()
    test_case_insensitive_and_nonstring_skipped()
    print("\n✅ test_validator_guard 全部通过")
