"""PRD / Design / Files schema。

每个产物两份:
- `XxxSchema`:Pydantic 模型,给 LLM structured output 用(.with_structured_output)。
- `XxxDict`:TypedDict,给 LangGraph state schema 用(graph state 习惯用 TypedDict)。

字段是前后端共用的契约。
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field
from typing_extensions import TypedDict


# ────────────────────────────────────────────────────────────────
# PRD(PM / Emma 产)
# ────────────────────────────────────────────────────────────────

class PRDSchema(BaseModel):
    """Claude structured output 的目标 schema(Pydantic)。"""

    title: str = Field(description="产品名,中文,简洁有力,不超过 20 字")
    summary: str = Field(description="一段话产品概述(2-3 句:为谁 / 解决什么问题 / 怎么做)")
    features: List[str] = Field(description="核心功能列表,每项一句话,3-6 项")
    acceptanceChecks: List[str] = Field(description="验收标准清单,可逐条勾选验证,3-6 项")


class PRDDict(TypedDict):
    """graph state 里 prd 字段的形状(跟 PRDSchema 字段对齐)。"""

    title: str
    summary: str
    features: List[str]
    acceptanceChecks: List[str]


# ────────────────────────────────────────────────────────────────
# Design(Architect / Bob 产)
# ────────────────────────────────────────────────────────────────

class FieldSchema(BaseModel):
    """一张数据表里的字段。"""

    name: str = Field(description="字段名,小写下划线,如 id / user_id / created_at")
    type: str = Field(description="字段类型:uuid / text / date / timestamptz / boolean / integer / numeric / jsonb 等")
    pk: bool = Field(default=False, description="是否主键")
    fk: Optional[str] = Field(default=None, description="外键引用,格式 '表名.字段名',如 'users.id';无外键则留空")


class TableSchema(BaseModel):
    """一张 Supabase/Postgres 数据表。"""

    name: str = Field(description="表名,小写复数,如 users / habits / checkins")
    fields: List[FieldSchema] = Field(description="该表的字段列表,至少含主键")


class DesignSchema(BaseModel):
    """Architect 产出的设计文档(structured output 目标)。"""

    product_type: str = Field(description="产品类型:web_app / landing / tool 三选一")
    supabase_tables: List[TableSchema] = Field(description="数据模型:Supabase/Postgres 表清单(含字段/主键/外键)")
    pages: List[str] = Field(default_factory=list, description="页面/路由清单,如 ['/login', '/dashboard'];可为空")


class FieldDict(TypedDict):
    name: str
    type: str
    pk: bool
    fk: Optional[str]


class TableDict(TypedDict):
    name: str
    fields: List[FieldDict]


class DesignDict(TypedDict):
    """graph state 里 design 字段的形状(跟 DesignSchema 对齐)。"""

    product_type: str
    supabase_tables: List[TableDict]
    pages: List[str]


# ────────────────────────────────────────────────────────────────
# Files(Engineer / Alex 产)
# ────────────────────────────────────────────────────────────────

class FileSchema(BaseModel):
    """单个生成文件。content 是文件本身的代码(独立块),不是塞进一个大 JSON string。"""

    path: str = Field(description="文件相对路径,如 'src/App.tsx' / 'src/lib/supabase.ts'")
    content: str = Field(description="文件内容(源码)。完整、可读、可直接写入磁盘")
    language: str = Field(description="代码语言,用于前端高亮:tsx / ts / jsx / js / css / json / markdown 等")


class FileDict(TypedDict):
    """graph state 里 files 列表每个元素的形状。"""

    path: str
    content: str
    language: str
    status: str  # "done" / "generating" / "error";目前恒为 "done"


class FilesSchema(BaseModel):
    """Engineer 产出的文件集合(structured output 目标)。"""

    files: List[FileSchema] = Field(description="生成的全部文件,每文件一项;通常 4-7 个文件")
