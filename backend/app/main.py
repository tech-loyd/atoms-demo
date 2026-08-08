"""FastAPI 入口:CORS + 把 LangGraph agent 暴露为 AG-UI 端点。

挂载方式遵循 LangChain 官方文档(LangChain × CopilotKit 集成页):
`add_langgraph_fastapi_endpoint`(来自 ag-ui-langgraph)把 graph 挂在
`/api/copilotkit` 上,前端 `<CopilotKit runtimeUrl="...">` 连过来。

启动:
    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import threading
import uuid
from contextlib import asynccontextmanager

from ag_ui_langgraph import add_langgraph_fastapi_endpoint
from copilotkit import LangGraphAGUIAgent
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from langchain_core.messages import HumanMessage

from .agent import RECURSION_LIMIT, agent
from .config import settings

# 部署触发对齐(前端 useDeploy → 后端 deploy_app)。
#
# 注入给 LLM 的"用户要求部署"HumanMessage 内容。SOP_SYSTEM_PROMPT 第 6 步约束:
# 仅在 validate_build 通过 + 用户明确要求"部署/上线/发布/给我 URL"时调 deploy_app。
# 这条消息字面含"部署/上线",确定性触发 LLM 调 deploy_app(不依赖前端发 chat 消息)。
_DEPLOY_REQUEST_CONTENT = (
    "请把当前已通过构建校验(build_status=passed)的应用部署到 Vercel(部署 / 上线),"
    "给我一个可访问的 vercel.app 真站点 URL。"
)


class DeployAwareLangGraphAGUIAgent(LangGraphAGUIAgent):
    """LangGraphAGUIAgent + 检测 `forwarded_props.{message,action}` 注入 HumanMessage。

    ## 背景(部署触发不对齐)
    前端 useDeploy(`frontend/src/lib/useDeploy.ts`)走 `agent.runAgent({forwardedProps:
    {action:"deploy"}})` —— 确定性触发,**不发 chat 消息**。后端 `deploy_app` 是
    create_agent 第 6 个 tool,靠 LLM 看 chat"部署"消息 + SOP_SYSTEM_PROMPT 第 6 步调用,
    **没有检测 forwarded_props.action**。结果:前端点部署 → runAgent 发 action:"deploy"
    → 后端 graph 收到 forwarded_props={action:"deploy"},但 create_agent 只看 messages
    (没有"部署"chat 消息)→ LLM 不调 deploy_app → 部署失败。

    ## 修法(在 AG-UI → graph 的 state 合流点检测 forwarded_props)
    override `langgraph_default_merge_state` —— 这是 ag-ui-langgraph 把 RunAgentInput
    合流成 graph input state 的钩子(`ag_ui_langgraph/agent.py:475` 处 `self.
    langgraph_default_merge_state(state_input, langchain_messages, input)` 调用),签名含
    `input`,可直接读 `input.forwarded_props.action`。copilotkit 的 LangGraphAGUIAgent
    本身也 override 了同名方法(加 copilotkit.actions),同路可达,super() 链完整。

    检测到 `action=="deploy"` → 往 merged state 的 messages 追加一条 HumanMessage
    (`_DEPLOY_REQUEST_CONTENT`),LLM 按 SOP 第 6 步调 deploy_app。**不重跑 SOP**:deploy
    run 只追加这一条消息,模型看到历史(build 已 passed)+ 部署请求 → 直接调 deploy_app,
    不会从 write_prd 重新开始(SOP 硬约束"一次完整流程只走一遍")。

    同一路径还处理欢迎页带需求的首轮触发:前端 ChatPanel 走
    `agent.runAgent({forwardedProps:{message:q}})`(ag-ui 的 RunAgentParameters 不含
    message 字段,只能走 forwardedProps;绕开 CopilotKit chat send API 的限制)→
    检测 `forwarded_props.message` → 注入 HumanMessage → Emma 据此 write_prd。

    ## 为什么不在 CopilotKitMiddlewareNoContext.before_agent 里检测
    查源码结论:**middleware hook 读不到 forwarded_props.action**,除非给 GraphState 加
    action 字段。理由:`ag_ui_langgraph` 的 prepare_stream 把 forwarded_props 直接展开进
    graph input(`stream_input = {**forwarded_props, **payload_input}`,agent.py:589),但
    LangGraph 按 graph 的 input schema 过滤 —— `action` 不在 GraphState → 被丢弃(实测确认:
    `agent.get_input_jsonschema()` 不含 action)。所以 before_agent(state, runtime) 的 state
    里没有 action;runtime.context 也没被 ag-ui-langgraph 设置(为 None)。

    要让 middleware 读到,得:① 给 GraphState 加 action 字段(污染前端 STATE_SNAPSHOT 可见
    状态);② 处理跨 run 持久化 —— checkpoint 会保留 action="deploy",下次正常 chat 误触发
    部署,必须在 before_agent 里手动 reset。代价大且脆弱。

    merge_state 路径直接拿原始 `input.forwarded_props`(每 run 都重新读,无持久化副作用),
    无需改状态 schema、无跨 run 残留 —— 更干净、更可靠。**保留 create_agent 拓扑 + 前端确定性**。

    ## 正常 SOP 不受影响
    既无 `forwarded_props.message` 也无 `action=="deploy"`(普通 chat / resume / 初始 SOP)→
    原样走 super(),不追加任何消息,行为与未加本类完全一致。
    """

    def langgraph_default_merge_state(self, state, messages, input):  # type: ignore[override]
        merged = super().langgraph_default_merge_state(state, messages, input)
        forwarded_props = getattr(input, "forwarded_props", None) or {}
        # ag_ui_langgraph.LangGraphAgent.run 已对 forwarded_props 的 key 做 camel_to_snake
        # (agent.py:174-178);"message"/"action" 无驼峰形式,snake 后仍原样。
        #
        # 欢迎页带需求触发首轮(Emma):forwardedProps.message → HumanMessage,LLM 据此 write_prd。
        # 同 deploy 模式:runAgent 不发 chat 消息,用 forwardedProps 确定性传需求(绕开
        # CopilotKit 1.66 chat send API 的 premium/deprecated 限制 —— RunAgentParameters 不
        # 含 message 字段,只能走 forwardedProps)。
        req_msg = forwarded_props.get("message")
        if isinstance(req_msg, str) and req_msg.strip():
            merged = {
                **merged,
                "messages": [
                    *merged.get("messages", []),
                    HumanMessage(
                        content=req_msg.strip(),
                        id=f"welcome-request-{uuid.uuid4().hex[:8]}",
                    ),
                ],
            }
        elif forwarded_props.get("action") == "deploy":
            deploy_msg = HumanMessage(
                content=_DEPLOY_REQUEST_CONTENT,
                # 唯一 id:add_messages reducer 按 id 去重,新 id 保证追加而非覆盖;
                # 也避免与上一轮部署请求(若用户重复点)同 id 被合并。
                id=f"deploy-request-{uuid.uuid4().hex[:8]}",
            )
            merged = {
                **merged,
                "messages": [*merged.get("messages", []), deploy_msg],
            }
        return merged


def _preheat_in_background() -> None:
    """后台跑 Validator 的 `preheat()`:npm install 预装模板 node_modules。

    首次 npm install 实测 ~19s(纯净环境 30-60s)。若不做预热,首个用户首次 build
    会在 SSE 流内同步等这 19s(Validator tool 阻塞),体验为"卡住"。这里在 FastAPI
    startup 起一个 daemon 线程跑 preheat,服务一启动就开始装,等用户真请求时基本已
    就绪,首次 build 命中预装缓存 → vite build 仅 ~0.5s。

    preheat 幂等(node_modules 已存在直接 return),重复调用无副作用;线程设 daemon
    即便它还没跑完服务退出也不会阻塞进程。
    """
    # 延后 import,避免 main 模块 import 时把 validator 的 npm 调用链拉进来形成循环。
    from .validator import preheat

    try:
        preheat()
    except Exception:  # noqa: BLE001
        # 预热失败不影响服务启动 —— 后续 validate_build 会落到 run_build 的"未就绪"分支,
        # 由 ToolMessage 友好提示,不阻塞 SSE。
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI 生命周期:startup 起后台预热,Ctrl-C 时无论预热是否完成都退出。"""
    t = threading.Thread(target=_preheat_in_background, name="validator-preheat", daemon=True)
    t.start()
    yield


app = FastAPI(
    title="atoms-backend",
    version="0.2.0",
    description="atoms 复刻后端:LangGraph + CopilotKitMiddleware + GLM-5.2(三角色 SOP PM→Architect→Engineer + HITL 批准)",
    lifespan=lifespan,
)

# CORS:允许前端开发地址(契约:http://localhost:3000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 把编译后的 graph 包成 CopilotKit/AG-UI 兼容的 agent
# DeployAwareLangGraphAGUIAgent:在 AG-UI → graph 合流点检测 forwarded_props.{message,action}
# → 注入对应 HumanMessage(对齐前端 useDeploy / ChatPanel 的确定性触发),见该类 docstring。
agui_agent = DeployAwareLangGraphAGUIAgent(
    name=settings.agent_name,
    graph=agent,
    description="atoms 三角色 SOP agent:PM(PRD)→ HITL 批准 → Architect(设计)→ Engineer(代码)",
    # 关键修复:AG-UI 层用 ensure_config(self.config) 重建 RunnableConfig,
    # 不读 graph.config(那里有 with_config 绑的 recursion_limit)。若不在这里显式传,
    # ensure_config({}) 会回落到 langchain 默认 recursion_limit=25,SOP 全链路必崩。
    # 与 agent.py 的 RECURSION_LIMIT 同源,两条调用路径都兜住。
    config={"recursion_limit": RECURSION_LIMIT},
)

# 暴露 AG-UI 端点(契约:/api/copilotkit)
# 由此注册两条路由:POST {path}(主端点,SSE 流)+ GET {path}/health(健康检查)
add_langgraph_fastapi_endpoint(app, agui_agent, path=settings.endpoint_path)


@app.get("/")
def root() -> dict:
    """根路径自检(给浏览器/PM 整合验证用)。"""
    return {
        "service": "atoms-backend",
        "status": "ok",
        "agent": settings.agent_name,
        "model": settings.anthropic_model,
        "endpoint": settings.endpoint_path,
    }


# Validator build 产物静态托管(替代 Sandpack CDN)。
# Validator build 成功后把 dist/ 复制到 static/previews/{session_id}/dist/,
# 这里用 StaticFiles 把它挂出去 → 前端 iframe 直接加载 /preview/{session_id}/dist/index.html。
# 不依赖 CodeSandbox CDN(Sandpack 在受限网络全不可达 → 一直编译中/白屏)。
_STATIC_PREVIEWS = Path(__file__).resolve().parent.parent / "static" / "previews"
_STATIC_PREVIEWS.mkdir(parents=True, exist_ok=True)
app.mount("/preview", StaticFiles(directory=str(_STATIC_PREVIEWS)), name="previews")
