"""parse_files_markdown 单元测试(纯函数,不调 LLM,秒级)。"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.tools import parse_files_markdown


def test_basic_two_files():
    md = """##FILE: src/App.tsx
```tsx
export default function App() {
  return <div>hi</div>
}
```

##FILE: src/lib/supabase.ts
```typescript
import { createClient } from '@supabase/supabase-js'
export const supabase = createClient('https://x.supabase.co', 'key')
```
"""
    files = parse_files_markdown(md)
    assert len(files) == 2, f"应解析 2 个文件,实际 {len(files)}: {[f['path'] for f in files]}"
    assert files[0]["path"] == "src/App.tsx"
    assert files[0]["language"] == "tsx"
    assert "export default function App" in files[0]["content"]
    assert files[1]["path"] == "src/lib/supabase.ts"
    assert files[1]["language"] == "typescript"
    print("✅ test_basic_two_files 通过")


def test_no_language_fenced():
    md = """##FILE: README.md
```
# hi
some text
```
"""
    files = parse_files_markdown(md)
    assert len(files) == 1
    assert files[0]["language"] == "markdown"  # 按扩展名兜底
    print("✅ test_no_language_fenced 通过")


def test_dedup_same_path():
    md = """##FILE: src/App.tsx
```tsx
version 1
```

##FILE: src/App.tsx
```tsx
version 2
```
"""
    files = parse_files_markdown(md)
    assert len(files) == 1, f"重复 path 去重,应 1 个,实际 {len(files)}"
    print("✅ test_dedup_same_path 通过")


def test_empty_content_skipped():
    md = """##FILE: empty.ts
```ts
```

##FILE: real.ts
```ts
export const x = 1
```
"""
    files = parse_files_markdown(md)
    assert len(files) == 1
    assert files[0]["path"] == "real.ts"
    print("✅ test_empty_content_skipped 通过")


def test_no_file_blocks():
    md = "这是一段没有文件块的普通文本。"
    files = parse_files_markdown(md)
    assert files == []
    print("✅ test_no_file_blocks 通过")


def test_nested_fence_not_truncated():
    """内容里出现独立 ``` 行(嵌套 markdown 代码块)用 4 反引号外层围栏包裹,
    内层 ``` 不应误闭合;模板字符串里的行内反引号也不应截断。"""
    md = "##FILE: docs/guide.md\n````markdown\n# 指南\n\n示例:\n\n```tsx\nconst s = `x`\n```\n\n结尾。\n````\n"
    files = parse_files_markdown(md)
    assert len(files) == 1, f"应解析 1 个文件,实际 {len(files)}"
    content = files[0]["content"]
    assert "```tsx" in content, "内层 ```tsx 应被原样保留,不被误判为闭合"
    assert "结尾。" in content, "外层 4 反引号围栏应包裹到末尾,不被内层 ``` 截断"
    assert files[0]["language"] == "markdown"
    print("✅ test_nested_fence_not_truncated 通过")


def test_inline_triple_backticks_in_content():
    """正则非贪婪会把行内 ``` 当闭合截断;按行扫描只认独立 ``` 行,行内的不算。"""
    md = '##FILE: src/App.tsx\n```tsx\nconst tpl = `code: ```x````\nexport default function App() { return <div/> }\n```\n'
    files = parse_files_markdown(md)
    assert len(files) == 1, f"应解析 1 个文件,实际 {len(files)}"
    assert "export default function App" in files[0]["content"], "行内 ``` 不应截断内容"
    print("✅ test_inline_triple_backticks_in_content 通过")


if __name__ == "__main__":
    test_basic_two_files()
    test_no_language_fenced()
    test_dedup_same_path()
    test_empty_content_skipped()
    test_no_file_blocks()
    test_nested_fence_not_truncated()
    test_inline_triple_backticks_in_content()
    print("\n=== parse_files_markdown 全部通过 ===")
