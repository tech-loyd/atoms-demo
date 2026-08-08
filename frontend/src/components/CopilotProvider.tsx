"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
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
  // 依赖是模块常量,等价于 [];useMemo 保留"组件生命周期内单例"语义。
  const agent = useMemo(
    () => new HttpAgent({ agentId: AGENT_NAME, url: RUNTIME_URL }),
    [],
  );

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
