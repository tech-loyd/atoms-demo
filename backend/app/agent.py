"""组装 LangGraph agent:三角色 SOP + HITL 批准 + Validator 真 build 回喂 + Vercel 部署。

## 拓扑:create_agent + 6 tool(ReAct,system prompt 强约束顺序)

用 `create_agent` + 多 tool + `CopilotKitMiddleware`。六个 tool 由 `SOP_SYSTEM_PROMPT`
强约束顺序,ReAct 按序调用:
    Emma(PM)   write_prd(requirement)  → 写 state.prd
              approve_prd()           → HITL interrupt,等用户批准
    Bob(架构)  write_design()          → 读 state.prd,写 state.design
    Alex(工程) write_code()            → 读 state.design,写 state.files
              validate_build()        → 真 vite build;失败回喂 Alex 重 write_code(iter<3)
              deploy_app()            → validate_build 通过后,用户触发部署到 Vercel
                                          → state.deployment_url + deploy_status

`CopilotKitMiddleware` 是 `AgentMiddleware`,依赖 `create_agent` 内部的 model-call /
tool-call 节点触发 hooks —— 这是用 create_agent、不裸 StateGraph 的根因。

## 为什么 Validator 是 tool,不是独立 graph 节点?

曾试过外层 StateGraph 包 create_agent + Validator 兄弟节点 + conditional edge 回喂。
POC(tests/poc_subgraph_interrupt.py)验证了 subgraph 内 interrupt 能冒泡到顶层,但
端到端实测暴露硬伤:create_agent 作为 subgraph 时,它在 approve_prd 的 HITL interrupt
暂停期间,内部写入的 state.prd **不反映到顶层 state.values**(subgraph 节点未完成,
state 更新未 merge)。而 ag-ui-langgraph 的 STATE_SNAPSHOT 用
`graph.aget_state(config)`(不带 subgraphs=True)取顶层 state → 前端拿到 state.prd
为空 → PRDCard 空 → 破坏 HITL 契约。

改用当前拓扑(顶层 create_agent,state 直接顶层可见),回喂靠 ReAct 的 ToolMessage +
SOP prompt 约束。Validator / deploy_app 作为 tool 在 ReAct loop 内是明确的执行单元,
语义上等价 SOP 的"Validator 节点"。详见 app/validator.py 顶部注释。

HITL 由 ag-ui-langgraph 透传:
- copilotkit_interrupt → LangGraph 暂停 → ag-ui-langgraph 发 OnInterrupt CustomEvent
- 前端 resolve(payload) → forwarded_props.command.resume → interrupt() 返回 payload
"""
from __future__ import annotations

from copilotkit import CopilotKitMiddleware
from langchain.agents import create_agent
from langgraph.checkpoint.memory import InMemorySaver

from .config import settings
from .deploy import deploy_app
from .llm import build_model
from .prompts import SOP_SYSTEM_PROMPT
from .state import GraphState
from .tools import approve_prd, update_code, write_code, write_design, write_prd
from .validator import validate_build


# LangGraph recursion_limit。
#
# 背景:`create_agent` 内部其实给 compiled graph 的 `graph.config` 盖了一个
# `recursion_limit=9999` 的默认值(langchain 1.3.14 实测),所以**直接 ainvoke**
# 的调用方(测试、`langgraph dev`)本来不会撞顶。
#
# 但 AG-UI 服务路径(`/api/copilotkit`)有硬伤:`ag_ui_langgraph.LangGraphAgent.run`
# 在每次请求时用 `ensure_config(self.config or {})` **重建** RunnableConfig
# (ag_ui_langgraph/agent.py:203),根本不读 `graph.config`。`self.config` 默认空 →
# `ensure_config({})` 填 langchain 默认 `recursion_limit=25`。该 per-call config
# 经 `astream_events(config=...)` 传给 graph,**覆盖** graph.config 里的 9999。
# → SOP 全链路(PM→HITL→Architect→Engineer≈15-20 superstep)+ Validator 回喂循环
# (失败重 write_code→validate_build,每轮再 +5-8 superstep)+ deploy_app(~3 superstep)
# 必撞 25 上限崩。
#
# 修:把 recursion_limit 同时放在两处(belt-and-suspenders,两条路径都不漏):
#   1) `build_agent` 用 `with_config` 给 graph 本身绑默认(覆盖 create_agent 的 9999
#      → 统一为 100;直接调用方若未显式给 recursion_limit 即生效)。
#   2) `main.py` 的 `LangGraphAGUIAgent(config=...)` 显式传 100 → 写进 `self.config`,
#      `ensure_config` 保留它,不再回落到 25。**这一处才是 AG-UI 路径的关键修复。**
# 100 的预算:SOP ~20 + 回喂 3 轮×~15 ≈ 65 + deploy_app ~10 + 余量,共 ~95,提到 100。
RECURSION_LIMIT = 100


class CopilotKitMiddlewareNoContext(CopilotKitMiddleware):
    """CopilotKitMiddleware,但禁用 before_agent 的 App Context 注入。

    原版 `before_agent` 会把 `runtime.context`(AG-UI 端点路径下含 thread_id
    等)作为一条 SystemMessage 插入 messages;它跟 `create_agent(system_prompt=...)`
    通过 `request.system_message` 单独传的 SOP_PROMPT,在 langchain-anthropic 的
    `_format_messages` 里会形成"multiple non-consecutive system messages"报错。

    本项目不需要把前端 context 注入 LLM prompt,所以覆盖 before_agent 为 no-op。
    保留 CopilotKitMiddleware 其他能力(AG-UI 协议、CopilotKitState 同步、HITL 的
    OnInterrupt 发射、generative UI tool 拦截等)。
    """

    def before_agent(self, state, runtime):  # type: ignore[override]
        return None

    async def abefore_agent(self, state, runtime):  # type: ignore[override]
        return None


def build_agent(checkpointer=None):
    """构造编译后的 LangGraph agent(CompiledStateGraph)。

    返回值用 `with_config({"recursion_limit": RECURSION_LIMIT})` 绑了默认 recursion
    预算。直接调 ainvoke/astream 的路径(测试、`langgraph dev`)即生效;AG-UI 服务
    路径需 `main.py` 里 `LangGraphAGUIAgent(config=...)` 再传一次(见模块顶部
    RECURSION_LIMIT 注释),因为 AGUI 层会重建 config、忽略 graph.config。

    checkpointer:可选,会话状态持久化层。None → 内存 saver(进程重启即清空,
    供 `langgraph dev`/测试/本地兜底);生产由 main.py 注入 AsyncPostgresSaver(连
    Supabase)让状态跨刷新与容器重启存活。
    """
    model = build_model()
    agent_compiled = create_agent(
        model=model,
        tools=[write_prd, approve_prd, write_design, write_code, update_code, validate_build, deploy_app],
        middleware=[CopilotKitMiddlewareNoContext()],
        state_schema=GraphState,
        system_prompt=SOP_SYSTEM_PROMPT,
        name=settings.agent_name,
        # add_langgraph_fastapi_endpoint 内部会 aget_state,必须有 checkpointer;
        # HITL interrupt 也依赖 checkpointer 持久化暂停点。
        checkpointer=checkpointer or InMemorySaver(),
    )
    # 绑默认 recursion_limit(覆盖 create_agent 自带的 9999,统一预算为 100)。
    return agent_compiled.with_config({"recursion_limit": RECURSION_LIMIT})


# 模块级单例(main.py 与 langgraph.json 都引用它)
agent = build_agent()
# langgraph.json 期望的入口名:./app/agent.py:graph
graph = agent
