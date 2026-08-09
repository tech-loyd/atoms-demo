"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { CopilotKit } from "@copilotkit/react-core";
import { HttpAgent, type AbstractAgent } from "@ag-ui/client";
import { AGENT_NAME, RUNTIME_URL } from "@/lib/constants";

// Direct Connection(v1 的 agents__unsafe_dev_only):用 HttpAgent 直连后端 AG-UI 端点。
// 后端 ag-ui-langgraph 暴露纯 AG-UI 协议,HttpAgent 直接消费,无需 CopilotKit Runtime 中间层。
// (官方说明:Direct Connection 仅开发/原型用;生产应改用 Runtime + selfManagedAgents。)
type BackendStatus = "checking" | "online" | "offline";

interface BackendCtxValue {
  status: BackendStatus;
  lastChecked: number | null;
  retry: () => void;
  /**
   * 与 useCoAgent 同源的 HttpAgent 实例(注册进 agents__unsafe_dev_only 的那个)。
   * HITL resume 需直接对它调 agent.runAgent({forwardedProps:{command:{resume:...}}}),
   * 绕开 useCoAgent().run 的 unbind 问题(详见 useApproval.ts 注释)。
   */
  agent: AbstractAgent | undefined;
}

const BackendCtx = createContext<BackendCtxValue>({
  status: "checking",
  lastChecked: null,
  retry: () => {},
  agent: undefined,
});

export function useBackendStatus(): BackendCtxValue {
  return useContext(BackendCtx);
}

// 会话线程 ID 的持久化 key(localStorage)+ URL 查询参数名。
const THREAD_ID_KEY = "atoms_thread_id";
const THREAD_ID_QUERY = "t";

/**
 * 读已保存的线程 ID:优先 URL ?t=(分享/书签入口)→ localStorage(刷新兜底);都没有返回 null(全新会话)。
 * SSR / localStorage 不可用时返回 null。决定 HttpAgent 复用哪条后端会话(checkpointer 据此恢复 state)。
 */
function readThreadId(): string | null {
  if (typeof window === "undefined") return null;
  const fromUrl = new URLSearchParams(window.location.search).get(THREAD_ID_QUERY);
  if (fromUrl) return fromUrl;
  try {
    return window.localStorage.getItem(THREAD_ID_KEY);
  } catch {
    return null;
  }
}

async function probeBackend(url: string, timeoutMs = 3000): Promise<boolean> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    // no-cors:后端端口活着则返回 opaque 响应(不 throw);端口没起则 throw TypeError
    await fetch(url, { mode: "no-cors", signal: ctrl.signal });
    return true;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

export function CopilotProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<BackendStatus>("checking");
  const [lastChecked, setLastChecked] = useState<number | null>(null);

  const retry = useCallback(async () => {
    setStatus("checking");
    // 探 /health(后端 GET 端点),避免探主端点 POST /api/copilotkit 产生 405 噪音
    const ok = await probeBackend(`${RUNTIME_URL}/health`);
    setStatus(ok ? "online" : "offline");
    setLastChecked(Date.now());
  }, []);

  useEffect(() => {
    retry();
    const id = window.setInterval(retry, 15000);
    return () => window.clearInterval(id);
  }, [retry]);

  // HttpAgent 直连后端 AG-UI agent。agentId 对齐后端 agent_name("default"),
  // useCoAgent({ name: AGENT_NAME }) 据此匹配。
  // 线程 ID:复用已保存的(刷新/分享恢复),否则新建。HttpAgent 把 threadId 随每次 runAgent
  // 发给后端,后端 checkpointer 据此命中历史 state —— 这是刷新不丢会话的关键。
  // isRestore 标记"是否在恢复已有线程"(决定 mount 后是否发 restore 拉回 state)。
  const { instance: agent, isRestore } = useMemo(() => {
    const saved = readThreadId();
    const threadId = saved ?? crypto.randomUUID();
    return {
      instance: new HttpAgent({ agentId: AGENT_NAME, url: RUNTIME_URL, threadId }),
      isRestore: saved !== null,
    };
  }, []);

  // 持久化线程 ID:写 localStorage + URL(供刷新/分享恢复)。URL 写入保留其它查询参数(如首轮 ?q=)。
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem(THREAD_ID_KEY, agent.threadId);
    } catch {
      /* localStorage 不可用(隐私模式)—— URL 仍兜底 */
    }
    const params = new URLSearchParams(window.location.search);
    if (params.get(THREAD_ID_QUERY) !== agent.threadId) {
      params.set(THREAD_ID_QUERY, agent.threadId);
      const qs = params.toString();
      window.history.replaceState({}, "", `${window.location.pathname}${qs ? `?${qs}` : ""}`);
    }
  }, [agent]);

  // 恢复:已有线程(非首次访问)且后端就绪时,主动发一轮 restore 拉回 state。
  // 后端 _handle_stream_events 检测到 action="restore" → 只回吐 STATE_SNAPSHOT +
  // MESSAGES_SNAPSHOT(+ HITL interrupt),不推进 graph。state 到位后 Canvas 自动渲染。
  const restoreSentRef = useRef(false);
  useEffect(() => {
    if (restoreSentRef.current || !isRestore) return;
    if (status !== "online" || !agent) return;
    restoreSentRef.current = true;
    agent
      .runAgent({ forwardedProps: { action: "restore" } })
      .catch((e) => console.error("[CopilotProvider] restore run 失败:", e));
  }, [isRestore, status, agent]);

  // Context value memo:避免每次 render 产生 new object 导致所有 useBackendStatus
  // 消费者(Canvas / StatusBar ...)无谓 re-render。retry / agent 均已稳定引用。
  const value = useMemo<BackendCtxValue>(
    () => ({ status, lastChecked, retry, agent }),
    [status, lastChecked, retry, agent],
  );

  return (
    <BackendCtx.Provider value={value}>
      {/* showDevConsole={false}:关闭 CopilotKit 自带错误浮窗,保持 demo 界面干净 */}
      <CopilotKit agents__unsafe_dev_only={{ [AGENT_NAME]: agent }} showDevConsole={false}>
        {children}
      </CopilotKit>
    </BackendCtx.Provider>
  );
}
