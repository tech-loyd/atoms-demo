# syntax=docker/dockerfile:1
# ==========================================================================
# atoms 后端镜像:Python 3.12 + Node 双基础
#   - Python:跑 FastAPI + LangGraph + CopilotKitMiddleware(无状态编排)
#   - Node  :Validator 起子进程跑 npm install + vite build
# 部署目标:Railway(Root Directory = backend)
# ==========================================================================

FROM python:3.12-slim

# 装 Node 20(Validator 子进程用;slim 镜像没有,需自装)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 1) 先装 Python 依赖(独立一层,代码改动不触发重装 → 加速构建)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2) 预装模板 node_modules(Validator 运行时直接复用,省 ~30-60s/次)
#    validator.py 的缓存策略(预装复用,省每次 build 重装)
COPY templates/ ./templates/
RUN cd templates/react-supabase-starter && npm install

# 3) 拷业务代码
COPY . .

# Railway 会注入 PORT;默认 8000 兜底
ENV PORT=8000
EXPOSE 8000

# bind 0.0.0.0 才能被 Railway 外网访问;端口走 $PORT
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
