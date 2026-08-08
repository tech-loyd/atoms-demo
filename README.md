# atoms

> 用自然语言生成**可运行、可登录、可分享**的全栈应用。输入一句话,PM → 架构 → 工程三角色协作产出 React + Supabase 应用,一键部署为真 `vercel.app` 站点。

输入「做一个带登录的习惯打卡应用」→ Emma 产出 PRD → 你批准 → Bob 产出数据模型 → Alex 生成代码 → 真实 `vite build` 校验 → 一键部署,拿到能注册、登录、打卡的真站点。

## 亮点

- **真编排,不是 prompt 包装** —— 后端 LangGraph 状态机驱动三角色 SOP(PM / Architect / Engineer + Validator + Deploy),每步产物进 GraphState,前端经 AG-UI `STATE_SNAPSHOT` 实时回流;HITL 在 PRD 后真正 `interrupt` 暂停等批准。
- **前后端纵向贯穿** —— Python FastAPI 承载 LangGraph 编排,在容器里起 Node 子进程跑真实 `vite build`,集成 Vercel / Supabase 两个外部 API;不是纯前端 Function。
- **全栈生成物,不是单文件玩具** —— 生成的应用是 React + Vite + Tailwind + Supabase(Auth + Postgres),能真注册、真登录、真 CRUD、数据持久。
- **真部署,不是 URL 快照** —— 一键调 Vercel API `POST /v13/deployments`(inlined files,免 git)建独立 `xxx.vercel.app` 站点;Supabase Management API 按 LLM 产出的数据模型动态建表 + RLS。

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Next.js 15 · CopilotKit · Tailwind |
| 后端 | Python · FastAPI · LangGraph · ag-ui-langgraph |
| 生成物 | React · Vite · Tailwind · Supabase(Auth + Postgres) |
| 部署 | Vercel API(inlined files)· Supabase Management API(动态 DDL) |
| LLM | 智谱 GLM-5.2(Anthropic 兼容 API,可一行换 Claude) |

## 架构

### 后端:三角色 SOP 状态机

```
用户需求
   │
   ▼
Emma(PM) ──write_prd──▶ state.prd
   │
   ▼
approve_prd ──interrupt──▶ ⏸ 等用户批准(HITL)
   │ (resume {approved: true})
   ▼
Bob(Architect) ──write_design──▶ state.design(数据模型 + 页面)
   │
   ▼
Alex(Engineer) ──write_code──▶ state.files(React + Supabase 源码)
   │
   ▼
Validator ──vite build──▶ 通过 / 失败回喂(最多 3 次)
   │
   ▼
Deploy ──Vercel API + Supabase DDL──▶ vercel.app 真站点
```

每步产物都写入 `GraphState`,前端订阅同一 agent 实例,`STATE_SNAPSHOT` 自动推送,工作区实时看到产物流转。

### 前端:工作区三视图

- **Design** —— Emma 的 PRD 卡片 + 批准入口 + Bob 的设计(前后端架构分层 + 数据库 ER 表 + 外键关系)
- **Code** —— Alex 生成的源码(文件树 + Prism 高亮,实时跟随生成)
- **Preview** —— 运行应用(Sandpack 即时预览 / 后端 build 产物 iframe / Vercel 部署站点,按就绪状态自动切)

欢迎页(`/`)输入需求,带参跳到工作区(`/workspace`)自动触发生成;生成期间停在 Design 视图,代码写完自动切 Preview。

### 几个关键工程决策

- **AG-UI Direct Connection + `forwardedProps` 确定性触发**:前端 `agent.runAgent({forwardedProps:{...}})` 直接对 HttpAgent 方法调用,后端在 `langgraph_default_merge_state` 检测信号注入 HumanMessage —— 欢迎页需求触发首轮、批准 resume、部署触发,都走这条确定路径,不依赖 LLM 解析自然语言意图。
- **多租户表名前缀**:每个生成应用的业务表带 `app_{hex}_` 前缀,部署时正则改写应用代码的 `.from('表')`,配合 Supabase RLS,不同应用数据互不污染。
- **Validator 真 build 回喂**:生成的代码拼上 Vite 模板,起 Node 子进程跑真实 `vite build`,失败把错误日志回喂 Alex 重写,不是正则糊弄的"编译校验"。

## 快速开始

### 后端

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 填下面几个 key
uvicorn app.main:app --port 8000
```

`.env` 需要:

- `ANTHROPIC_API_KEY` + `ANTHROPIC_BASE_URL` + `ANTHROPIC_MODEL` —— LLM(智谱 GLM-5.2 经 Anthropic 兼容 API;换 Claude 见 `.env.example` 注释)
- `VERCEL_TOKEN` —— 部署生成应用到 Vercel
- `SUPABASE_URL` + `SUPABASE_ANON_KEY` —— 生成应用的后端
- `SUPABASE_ACCESS_TOKEN`(PAT)—— 动态建表(可选,不配则跳过,需手动建表)

### 前端

```bash
pnpm install
pnpm dev   # http://localhost:3000
```

打开 `localhost:3000`,在欢迎页输入需求,点「开始构建」。

## 项目结构

```
backend/
  app/           FastAPI + LangGraph:agent / tools(SOP 工具)/ validator(真 build)/ deploy(Vercel+Supabase)
  templates/     生成应用的 Vite + React + Tailwind 项目模板
  tests/         单元 + 集成测试(动态建表、validator、deploy、SOP HITL 等)
frontend/
  src/
    app/         路由:/(欢迎页)· /workspace(工作区)
    components/  Canvas(三视图)/ ChatPanel / PRDCard / DesignCard / CodeView / ...
    lib/         useApproval / useDeploy(HITL + 部署的 AG-UI 触发)/ types / 常量
```
