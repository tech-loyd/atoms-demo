"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { AbstractAgent } from "@ag-ui/client";
import type { AgentState } from "./types";

/**
 * 部署 hook(触发后端 deploy_app → state.deployment_url / deploy_status 回流)。
 *
 * 触发方式:对 agent 实例调 `agent.runAgent({ forwardedProps: { action: "deploy" } })`
 *   (与 useApproval 同模式 —— 直接方法调用,保留 `this`,绕开 useCoAgent().run 的 unbind 问题)。
 *   AG-UI 协议把 forwardedProps 透传给后端,后端 ag-ui-langgraph 在 graph 入口检测
 *   `input.forwarded_props.action == "deploy"` → 调 deploy_app tool(Vercel API inlined
 *   files 部署)→ 写 state.deployment_url / deploy_status → 该 run 的 STATE_SNAPSHOT
 *   回流进同一 agent 实例 → useCoAgent state 自动更新(与 useApproval 同源)。
 *
 * 为什么选 forwardedProps 而非 chat 发"部署"消息:
 *   ① 确定性强:后端按 forwarded_props.action 直接路由到部署分支,不依赖 LLM 解析
 *      "部署"自然语言意图(避免 LLM 误判 / 漏调 deploy_app)。
 *   ② 类型安全:AG-UI RunAgentParameters.forwardedProps 是 unknown,无需碰 CopilotKit
 *      内部 Message(GraphQL)复杂类型(appendMessage 的 Message 类型字段多且未导出)。
 *   ③ 复用既有路径:useApproval 用同一路径(forwardedProps.command.resume)跑通 HITL resume;
 *      AG-UI HttpAgent.runAgent 直接方法调用,this 正确,STATE_SNAPSHOT 回流到 useCoAgent。
 *
 * 前后端契约:
 *   - 前端发 `forwardedProps: { action: "deploy" }`(固定 key/value)。
 *   - 后端在 graph 入口节点 / ag-ui-langgraph wrapper 检测 `forwarded_props.action == "deploy"`
 *     → 调 deploy_app tool(或直接进 deploy 节点),不跑 PRD/Design/Code 重生成。
 *   - state.deploy_status ∈ "building"(Vercel 构建中)/ "ready"(URL 可用)/ "failed" / null。
 *   - state.deployment_url 形如 "https://xxx.vercel.app"(ready 时非空)。
 */

export interface UseDeployArgs {
  /** 来自 useCoAgent 的 state(读 deployment_url / deploy_status)。 */
  state: AgentState | undefined;
  /**
   * 与 useCoAgent 同源的 HttpAgent 实例(CopilotProvider 透传)。直接对它调 runAgent,
   * 保证 STATE_SNAPSHOT 回流到 useCoAgent 订阅的同一实例,state 自动更新(同 useApproval)。
   */
  agent: AbstractAgent | undefined;
}

export interface UseDeployReturn {
  /** 后端写回的 vercel.app URL(ready 时非空) */
  deploymentUrl: string | null;
  /** 后端写回的部署状态(building/ready/failed/null) */
  deployStatus: "building" | "ready" | "failed" | null;
  /**
   * 部署进行中(本地视图态):覆盖"点击 → state.deploy_status='building' 回流"之间的瞬间,
   * 以及 state 尚未回流但 agent 已在跑的窗口。state.deploy_status 到位后以 state 为准。
   */
  deploying: boolean;
  /**
   * 部署结果同步丢失:runAgent resolve 后 state.deploy_status 仍为 null
   * (典型:中间代理 idle timeout 掐断 SSE,deploy_app 的 Command(update) 未回流到本实例)。
   * true 时 DeployBar 显示"部署结果未能同步"提示 + 重试,而非静默回 idle("点了没反应")。
   */
  deploySyncLost: boolean;
  /** 触发部署:对 agent 实例调 runAgent,发 forwardedProps.action="deploy" */
  deploy: () => Promise<void>;
  /** 清除 deploySyncLost 提示(用户点"知道了" / 重新部署时调用)。 */
  clearSyncLost: () => void;
}

export function useDeploy({ state, agent }: UseDeployArgs): UseDeployReturn {
  const [deploying, setDeploying] = useState(false);
  const [deploySyncLost, setDeploySyncLost] = useState(false);

  const deploymentUrl = state?.deployment_url ?? null;
  const deployStatus = state?.deploy_status ?? null;

  // 用 ref 持有最新 state:runAgent resolve 时读的是"resolve 那一刻"的最新 deploy_status,
  // 而不是 useCallback 闭包固化在点击瞬间的旧值(stale closure,会导致判定永远为 None)。
  const stateRef = useRef(state);
  stateRef.current = state;

  // 状态回流了就清掉"同步丢失"提示(网络恢复 / SSE 重连后 state 终于到位)。
  useEffect(() => {
    if (deployStatus) setDeploySyncLost(false);
  }, [deployStatus]);

  const deploy = useCallback(async () => {
    if (deploying || !agent) return;
    setDeploying(true);
    setDeploySyncLost(false); // 新一轮部署,清掉上次的同步丢失提示
    try {
      // 方法调用(同 useApproval):保留 this,AG-UI 协议直发 forwardedProps。
      // agent.threadId 已由首轮 run 设置,本轮 POST 落到同一线程;deploy_app 写回的
      // state(deployment_url / deploy_status)通过订阅回流,useCoAgent state 随之更新。
      await agent.runAgent({ forwardedProps: { action: "deploy" } });

      // runAgent resolve 后给 SSE 一个回流窗口(STATE_SNAPSHOT 异步推)。
      // 仍为 None → deploy_app 的 Command(update) 没回流到本实例(中间代理 idle timeout
      // 掐断长连接、checkpoint 没落地等)→ 标记 deploySyncLost,让 DeployBar 显示友好提示,
      // 而不是静默回 idle 按钮("点了没反应")。
      await new Promise<void>((r) => setTimeout(r, 1200));
      const latest = stateRef.current?.deploy_status ?? null;
      if (!latest) {
        setDeploySyncLost(true);
      }
    } catch (err) {
      // 不抛:保持 UI 稳定;后端 RUN_FAILED 通过 SSE 单独反映(state.deploy_status="failed")。
      console.error("[useDeploy] agent.runAgent 触发部署失败:", err);
    } finally {
      setDeploying(false);
    }
  }, [deploying, agent]);

  const clearSyncLost = useCallback(() => setDeploySyncLost(false), []);

  return {
    deploymentUrl,
    deployStatus,
    deploying,
    deploySyncLost,
    deploy,
    clearSyncLost,
  };
}
