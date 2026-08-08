"""LLM model 工厂:agent.py 与 tools.py 共用,避免两处各 new ChatAnthropic。

base_url 显式传(智谱 BigModel 的 Anthropic 兼容端点),不靠 env fallback——
否则部署环境没设 ANTHROPIC_BASE_URL 会打到 Anthropic 官方,model-not-found。

build_model 用 lru_cache 缓存单例:一次 SOP 跑 4 次(agent + write_prd /
approve_prd / write_design / write_code),复用同一个 ChatAnthropic,避免每次
tool 调用都重建 HTTP 连接池。lru_cache 在 CPython 下由 GIL 保护,
LangGraph tool 在线程池并发调用时安全(最坏两个线程各 new 一次、留一份进缓存,
ChatAnthropic 构造不走网络,代价可忽略)。
"""
from __future__ import annotations

from functools import lru_cache

from langchain_anthropic import ChatAnthropic

from .config import settings


@lru_cache(maxsize=1)
def build_model() -> ChatAnthropic:
    """构造 ChatAnthropic(智谱 GLM-5.2 经 Anthropic 兼容 API),模块级单例。

    max_tokens=8192:write_code 一次产多个文件(含完整源码),4096 经实测会被
    截断(structured output 解析失败)。GLM-5.2 输出上限充足,提到 8192 稳妥。
    """
    return ChatAnthropic(
        model=settings.anthropic_model,
        api_key=settings.anthropic_api_key,
        base_url=settings.anthropic_base_url or None,
        max_tokens=8192,
    )
