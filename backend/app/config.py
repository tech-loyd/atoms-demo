"""配置:从环境变量 / .env 读取。"""

from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv

# 从 backend/.env 读(存在则加载,不存在静默跳过)
load_dotenv()


@lru_cache
def get_settings() -> "Settings":
    return Settings()


class Settings:
    """运行时配置。所有字段都可在 .env 覆盖。"""

    def __init__(self) -> None:
        # 必填:调 Claude 的 key
        self.anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")

        # LLM 模型(智谱 GLM-5.2,经 Anthropic 兼容 API)
        self.anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "GLM-5.2")

        # Anthropic 兼容端点(智谱 BigModel;空则用 Anthropic 官方)
        self.anthropic_base_url: str = os.getenv("ANTHROPIC_BASE_URL", "")

        # 服务端口
        self.port: int = int(os.getenv("PORT", "8000"))

        # 前端 CORS 源(开发地址)
        self.frontend_origin: str = os.getenv("FRONTEND_ORIGIN", "http://localhost:3000")

        # AG-UI 端点路径(契约:前后端对齐 /api/copilotkit)
        self.endpoint_path: str = "/api/copilotkit"

        # agent 名:对齐 CopilotKit 前端默认 agentId "default"(CopilotChat 自动找 default)
        self.agent_name: str = "default"

        # Vercel API 部署生成应用为真站点(xxx.vercel.app)
        # ⚠️ 敏感:VERCEL_TOKEN 能操作整个 Vercel 账号。只从环境读,绝不 log/打印/回喂 LLM。
        self.vercel_token: str = os.getenv("VERCEL_TOKEN", "")

        # Supabase 配置(注入部署的应用,公开 anon key,不注入 service_role)
        self.supabase_url: str = os.getenv("SUPABASE_URL", "")
        self.supabase_anon_key: str = os.getenv("SUPABASE_ANON_KEY", "")

        # Supabase service_role key(极敏感,绕 RLS)。
        # ⚠️ 预留字段(按 PM/用户指示读入):**目前 Supabase HTTP API 不支持用 service_role JWT
        #   执行 DDL** —— 实测 Management API `POST /v1/projects/{ref}/database/query` 对
        #   service_role Bearer 返回 401 "JWT failed verification"(该端点要求 Personal Access
        #   Token,见 supabase_access_token)。保留本字段以备:(a) 未来 Supabase 支持服务端 DDL;
        #   (b) 直连 Postgres 兜底。**绝不** log/打印/注入生成应用/前端/日志。
        self.supabase_service_role_key: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

        # Supabase Personal Access Token(sbp_...),用于 Management API 动态建表(DDL)。
        # 在 https://supabase.com/dashboard/account/tokens 生成。**极敏感**:能管理整个 Supabase
        # 账号,只后端 deploy_app 建表用,**绝不** log/打印/写 ToolMessage/注入生成应用。
        # 没配 → deploy_app 跳过自动建表(非阻塞,见 deploy.py / README)。
        self.supabase_access_token: str = os.getenv("SUPABASE_ACCESS_TOKEN", "")

        # 后端 Vite 构建产物静态托管的基址(替代 Sandpack in-browser bundler)。
        # Validator build 成功后,把 dist/ 持久化到 backend/static/previews/{session_id}/dist/,
        # main.py 用 StaticFiles 把 /preview 挂出去;前端 iframe 直接加载,不依赖 CodeSandbox CDN。
        # 默认指向本后端(origin + /preview 前缀);改部署域名时覆盖。
        # 注意:这里读不到 port 字段(self.port 还没赋值),所以默认值硬编 8000,与 PORT 默认一致;
        # 改 PORT 时需同步设 PREVIEW_BASE_URL。
        self.preview_base_url: str = os.getenv(
            "PREVIEW_BASE_URL",
            f"http://localhost:{self.port}/preview",
        )

        # LangGraph 会话持久化:Supabase Postgres 连接串。
        # 配了 → 用 AsyncPostgresSaver(对话/PRD/代码/预览状态跨刷新 + 容器重启存活);
        # 空 → 回落 InMemorySaver(本地/测试,进程重启即清空)。
        # Supabase dashboard → Project Settings → Database → Connect → "URI"(Session mode,端口 5432)。
        # 必须用 session 模式而非 transaction 模式(6543):psycopg 默认用 prepared statements,
        # pgbouncer 事务模式会与之冲突。
        # ⚠️ 含数据库密码,只环境读取,绝不 log/打印/注入生成应用。
        self.database_url: str = os.getenv("DATABASE_URL", "")


settings = get_settings()
