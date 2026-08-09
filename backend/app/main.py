"""FastAPI 入口:CORS + 把 LangGraph agent 暴露为 AG-UI 端点。

挂载方式遵循 LangChain 官方文档(LangChain × CopilotKit 集成页):
`add_langgraph_fastapi_endpoint`(来自 ag-ui-langgraph)把 graph 挂在
`/api/copilotkit` 上,前端 `<CopilotKit runtimeUrl="...">` 连过来。

启动:
    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
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
from langchain_core.runnables import ensure_config

from ag_ui.core import CustomEvent, EventType, RunFinishedEvent, RunStartedEvent
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .agent import RECURSION_LIMIT, agent, build_agent
from .config import settings

logger = logging.getLogger(__name__)

# 前端 useApproval/useDeploy 用的 AG-UI custom event 名(中断信号),restore 时复用。
_INTERRUPT_EVENT_NAME = "on_interrupt"

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
        # 注入 thread_id 到 state:validator(预览 session_id)+ deploy_app(固定 vercel 链接的
        # project_name)都依赖它。本 langgraph 版本无 InjectedConfig,改由 merge_state 把
        # input.thread_id 写进 state,tool 经 InjectedState 读到(线程池执行也安全)。
        tid = getattr(input, "thread_id", None)
        if tid:
            merged["thread_id"] = tid
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

    async def _handle_stream_events(self, input):  # type: ignore[override]
        """AG-UI 流处理入口,前置一个"刷新恢复"短路。

        前端刷新后用 savedThreadId 重建 agent,并主动发一轮 `forwardedProps:{action:
        "restore"}`。这里检测到该 action 时,**只把当前 thread 在 checkpointer 里的
        state + messages(+ HITL 中断)以快照事件回吐,不推进 graph**:
          RunStarted → STATE_SNAPSHOT + MESSAGES_SNAPSHOT →(若停在 approve_prd)on_interrupt → RunFinished

        收到后前端 useCoAgent 的 state 更新 → Canvas 自动渲染 PRD/代码/预览;
        useApproval 据 state.prd + on_interrupt 恢复"等待批准"入口。state 从持久化
        checkpointer(生产 Postgres)取,故跨浏览器刷新与容器重启都能恢复。

        非 restore(普通 chat / deploy / resume / 首轮)→ 原样走 super(),行为不变。
        """
        forwarded_props = getattr(input, "forwarded_props", None) or {}
        if forwarded_props.get("action") != "restore":
            async for ev in super()._handle_stream_events(input):
                yield ev
            return

        thread_id = input.thread_id or str(uuid.uuid4())
        # 对齐基类 _handle_stream_events 开头的 active_run 初始化(RunStarted/Finished 需要 run_id)。
        self.active_run = {
            "id": input.run_id,
            "thread_id": thread_id,
            "mode": "start",
            "reasoning_process": None,
            "node_name": None,
            "has_function_streaming": False,
            "streamed_tool_call_ids": set(),
            "model_made_tool_call": False,
            "state_reliable": True,
        }
        config = ensure_config(self.config.copy() if self.config else {})
        config["configurable"] = {**(config.get("configurable", {})), "thread_id": thread_id}
        try:
            yield self._dispatch_event(
                RunStartedEvent(
                    type=EventType.RUN_STARTED, thread_id=thread_id, run_id=self.active_run["id"]
                )
            )
            # 一次 aget_state,rebuild 判断 + interrupts 复用(省一次远程 aget_state —— 远程 Supabase
            # 下单次 aget_state 可能 1-3s,合并能显著减少切换会话的卡顿)。
            agent_state = await self.graph.aget_state(config)
            # 旧会话的预览可能还堆在 /preview/default/(thread_id 隔离是后加的,历史 build 全堆
            # default),导致多个旧会话打开预览都指向 default = 看到同一套。检测到就 rebuild 到该
            # 会话独立 session_id,让每个会话预览真正隔离(只 files 非空 + preview 指向 default/空
            # 时触发,已隔离的正常会话跳过;每个旧会话仅首次打开 rebuild 一次)。
            await self._maybe_rebuild_stale_preview(config, thread_id, agent_state)
            # 当前 checkpoint 的 state + messages 快照(基类方法,yield 已序列化的 SSE 串)
            async for ev in self.get_state_and_messages_snapshots(config):
                yield ev
            # 停在 HITL(approve_prd 中断)时补发 on_interrupt,前端 useApproval 据此恢复"批准"按钮。
            # 复用上面的 agent_state,不再单独 aget_state(省一次远程查询)。
            tasks = agent_state.tasks if agent_state.tasks else None
            interrupts = tasks[0].interrupts if tasks else []
            for interrupt in interrupts:
                yield self._dispatch_event(
                    CustomEvent(
                        type=EventType.CUSTOM,
                        name=_INTERRUPT_EVENT_NAME,
                        value=json.dumps(interrupt.value, default=str, ensure_ascii=False),
                        raw_event=interrupt,
                    )
                )
            yield self._dispatch_event(
                RunFinishedEvent(
                    type=EventType.RUN_FINISHED, thread_id=thread_id, run_id=self.active_run["id"]
                )
            )
        finally:
            self.active_run = None

    async def _maybe_rebuild_stale_preview(self, config, thread_id: str, snap) -> None:
        """restore 时若预览指向 /preview/default/ 或为空(旧会话,thread_id 隔离前的历史 build),
        rebuild 到该会话独立 session_id,让每个会话的预览真正隔离。

        触发条件:state.files 非空 + preview_url 为空或含 /preview/default/。已隔离的会话
        (preview 已是 /preview/{thread_hex}/)跳过。每个旧会话仅首次打开 rebuild 一次(之后
        preview_url 更新为独立 session,不再触发)。rebuild 失败不阻塞 restore(只警告)。

        snap 由调用方传入(restore 流程已 aget_state 一次,这里复用,避免重复远程查询)。
        """
        from .validator import run_build  # 延后 import 避免循环

        if not snap or not snap.values:
            return
        values = snap.values
        files = values.get("files")
        if not isinstance(files, list) or not files:
            return
        preview_url = str(values.get("preview_url") or "")
        if preview_url and "/preview/default/" not in preview_url:
            return  # 已是该会话独立 session 的预览,跳过
        tid_hex = (thread_id or "").replace("-", "")
        session_id = tid_hex[:16] or "default"
        if session_id == "default":
            return  # 拿不到 thread_id,无法隔离
        try:
            passed, _ = run_build(files, session_id=session_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("restore 重建预览:run_build 失败(thread=%s):%s", thread_id, exc)
            return
        if passed:
            new_url = f"{settings.preview_base_url}/{session_id}/dist/index.html"
            try:
                await self.graph.aupdate_state(config, {"preview_url": new_url})
            except Exception as exc:  # noqa: BLE001
                logger.warning("restore 重建预览:aupdate_state 失败(thread=%s):%s", thread_id, exc)


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
    """FastAPI 生命周期:startup 起后台预热 + 接 Postgres checkpointer,shutdown 清理。

    DATABASE_URL 非空 → 构造 AsyncPostgresSaver(连 Supabase)、setup 建表,把 agui_agent.graph
    替换为接了持久 checkpointer 的 agent(会话状态跨浏览器刷新与容器重启存活)。
    DATABASE_URL 为空 → 沿用模块级默认 agent(InMemorySaver):仅进程内,重启即清空(本地调试用)。
    """
    t = threading.Thread(target=_preheat_in_background, name="validator-preheat", daemon=True)
    t.start()

    if settings.database_url:
        # 用连接池,而非 from_conn_string 的单连接:Supabase(Postgres 前面是 pgbouncer + 网络
        # 负载均衡器)会主动关闭闲置的 TCP 连接(idle timeout 通常几十秒~几分钟)。单连接一旦被
        # 服务端踢掉,saver 下次 aget_state 就报 "SSL error: unexpected eof / connection is
        # closed",且不重连 → 永久坏到重启进程。连接池的 check=check_connection 在每次 checkout
        # 前检测连接健康,坏连接自动丢弃重建 → 闲置断连自愈;max_idle/max_lifetime 让池主动回收,
        # 抢先于服务端断连。AsyncPostgresSaver 原生支持 conn=AsyncConnectionPool(内部
        # get_connection 从池借连接,用完归还)。kwargs 对齐原 from_conn_string:autocommit +
        # prepare_threshold=0 绕 pgbouncer prepared statement 冲突;row_factory=dict_row 让 saver
        # 按列名取值。
        try:
            async with AsyncConnectionPool(
                conninfo=settings.database_url,
                min_size=1,
                max_size=5,
                max_idle=60,        # 连接闲置 60s 主动回收,抢在 Supabase 踢掉前
                max_lifetime=300,   # 连接最长活 5 分钟,强制轮换
                timeout=30.0,
                kwargs={
                    "autocommit": True,
                    "prepare_threshold": 0,
                    "row_factory": dict_row,
                },
                check=AsyncConnectionPool.check_connection,
            ) as pool:
                saver = AsyncPostgresSaver(conn=pool)
                await saver.setup()
                agui_agent.graph = build_agent(saver)
                logger.info("Postgres checkpointer 已启用(连接池,闲置断连自愈),会话状态将持久化。")
                yield
        except Exception as exc:  # noqa: BLE001
            # Postgres 连不上属运维问题:不阻断服务,降级到默认内存 agent(刷新恢复失效但不崩)。
            logger.warning("Postgres checkpointer 启用失败,降级内存 saver:%s", exc)
            yield
    else:
        logger.info("未配 DATABASE_URL,使用内存 checkpointer(刷新/重启会丢,仅本地调试)。")
        yield


app = FastAPI(
    title="atoms-backend",
    version="0.2.0",
    description="atoms 后端:LangGraph + CopilotKitMiddleware + GLM-5.2(三角色 SOP PM→Architect→Engineer + HITL 批准)",
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


# /api/threads 内存缓存:aget_state 远程 + 反序列化长对话 messages 慢(~3s/批),
# 列表频繁刷新命中缓存避免重复查。删会话 invalidate;新建会话最多 _THREADS_CACHE_TTL 后可见。
_threads_cache: dict = {"data": None, "ts": 0.0}
_THREADS_CACHE_TTL = 20.0


@app.get("/api/threads")
async def list_threads() -> dict:
    """历史会话列表(从 Postgres checkpointer 查,跨设备共享,无用户归属)。

    每条返回 thread_id + title(prd.title)+ summary + stage。DATABASE_URL 空
    (InMemory 兜底)→ 返回空列表(前端侧栏显空态,不崩)。20s 内存缓存(删会话 invalidate)。
    """
    import time
    if _threads_cache["data"] is not None and time.time() - _threads_cache["ts"] < _THREADS_CACHE_TTL:
        return _threads_cache["data"]
    if not settings.database_url:
        return {"threads": []}

    # 独立短连接查 thread_id 列表(不复用 saver.conn,避免与 checkpointer 读写抢锁)
    try:
        thread_ids = await _list_thread_ids(settings.database_url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("GET /threads 查询 thread_id 失败:%s", exc)
        return {"threads": []}

    # 并发 aget_state:串行会 N×远程查询,本地连生产 Supabase 单次 ~3s,N 多时列表卡很久;
    # 并发 gather 把 N 次压到 ~N/pool_size。单个 aget_state 慢/超时(>10s)则跳过该会话,不阻塞列表。
    async def _one(_tid: str) -> dict | None:
        try:
            snap = await asyncio.wait_for(
                agui_agent.graph.aget_state({"configurable": {"thread_id": _tid}}),
                timeout=10,
            )
        except Exception:  # noqa: BLE001
            return None
        if not snap or not snap.values:
            return None
        values = snap.values
        prd = values.get("prd") or {}
        return {
            "thread_id": _tid,
            "title": prd.get("title") or "未命名会话",
            "summary": prd.get("summary") or "",
            "stage": _derive_stage(values),
        }

    results = await asyncio.gather(*[_one(tid) for tid in thread_ids])
    items = [r for r in results if r]
    result = {"threads": items}
    _threads_cache["data"] = result
    _threads_cache["ts"] = time.time()
    return result


async def _list_thread_ids(database_url: str) -> list[str]:
    """独立短连接查 checkpoints 表的 distinct thread_id(最新活动优先,LIMIT 50)。"""
    from psycopg import AsyncConnection

    conn = await AsyncConnection.connect(database_url, connect_timeout=8)
    try:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT thread_id FROM checkpoints "
                "WHERE checkpoint_ns = '' "
                "GROUP BY thread_id "
                "ORDER BY MAX(checkpoint_id) DESC "
                "LIMIT 20"
            )
            rows = await cur.fetchall()
        return [r[0] for r in rows]
    finally:
        await conn.close()


def _derive_stage(values: dict) -> str:
    """state.values → 阶段(对齐前端 deriveStage:files > design > prd > empty)。"""
    files = values.get("files")
    if isinstance(files, list) and len(files) > 0:
        return "files"
    if values.get("design"):
        return "design"
    if values.get("prd"):
        return "prd"
    return "empty"


# thread_id 白名单(UUID 或自定义 id,防 SQL/路径注入;DELETE 路径参数校验用)。
_THREAD_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@app.delete("/api/threads/{thread_id}")
async def delete_thread(thread_id: str) -> dict:
    """删除一个历史会话(清 Postgres 的 checkpoints/blobs/writes 三表,幂等)。

    删的是当前 thread 时,前端会自行跳到新会话。无鉴权(demo)。
    """
    if not settings.database_url:
        return {"ok": False, "error": "InMemory 模式无持久化,无需删除"}
    if not _THREAD_ID_RE.match(thread_id):
        return {"ok": False, "error": "非法 thread_id"}
    try:
        await _delete_thread(settings.database_url, thread_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("删除 thread 失败(%s):%s", thread_id, exc)
        return {"ok": False, "error": str(exc)}
    _threads_cache["data"] = None  # 删除会话 invalidate 列表缓存
    return {"ok": True, "thread_id": thread_id}


async def _delete_thread(database_url: str, thread_id: str) -> None:
    """独立短连接删一个 thread 的全部 checkpoint 数据(三表)。"""
    from psycopg import AsyncConnection

    conn = await AsyncConnection.connect(database_url, connect_timeout=8)
    try:
        async with conn.cursor() as cur:
            for tbl in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
                await cur.execute(f"DELETE FROM {tbl} WHERE thread_id = %s", (thread_id,))
        await conn.commit()
    finally:
        await conn.close()


# Validator build 产物静态托管(替代 Sandpack CDN)。
# Validator build 成功后把 dist/ 复制到 static/previews/{session_id}/dist/,
# 这里用 StaticFiles 把它挂出去 → 前端 iframe 直接加载 /preview/{session_id}/dist/index.html。
# 不依赖 CodeSandbox CDN(Sandpack 在受限网络全不可达 → 一直编译中/白屏)。
_STATIC_PREVIEWS = Path(__file__).resolve().parent.parent / "static" / "previews"
_STATIC_PREVIEWS.mkdir(parents=True, exist_ok=True)
app.mount("/preview", StaticFiles(directory=str(_STATIC_PREVIEWS)), name="previews")


@app.middleware("http")
async def _no_cache_preview(request, call_next):
    """给 /preview/* 响应加 no-store:迭代修改后 Validator 重建的 dist/ 覆盖同 URL(session_id
    不变),iframe 必须每次拉新,否则浏览器/CDN 缓存旧 index.html → 用户改完代码在预览看不到效果。
    仅作用于 build 产物静态托管路径,不影响其它接口。
    """
    response = await call_next(request)
    if request.url.path.startswith("/preview/"):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response
