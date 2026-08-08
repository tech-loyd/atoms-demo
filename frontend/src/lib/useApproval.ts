"use client";

import { useCallback, useEffect, useState } from "react";
import type { AbstractAgent } from "@ag-ui/client";
import type { AgentState } from "./types";

/**
 * HITL 批准 hook(headless resume)。
 *
 * 后端流程:
 *   PM(Emma)产 PRD → approve_prd 调 copilotkit_interrupt → graph 在 checkpointer 暂停
 *   → ag-ui-langgraph 发 `on_interrupt` custom event
 *   → 前端"批准":对该 agent 发新一轮 run,参数 forwardedProps.command.resume={approved:true}
 *   → ag-ui-langgraph 走 resume path(Command(resume=...)喂回 graph)
 *   → interrupt() 返回 {approved:true} → approve_prd 继续 → Bob(Architect)/Alex(Engineer)跑
 *   → 该 run 的 STATE_SNAPSHOT(design / files)回流进同一 agent 实例 → useCoAgent state 更新。
 *
 * 为什么直接调 agent.runAgent,而不是 useCoAgent().run / useCopilotContext.resolveInterruptEvent:
 *  ① useCoAgent().run 在 v1.66.2 的实现是 `run: agent.runAgent`(方法引用,未 bind),
 *     调用即丢 `this`,HttpAgent 子类首行 `this.abortController = ...` 崩(实测 PM 的
 *     `Cannot set properties of undefined (setting 'abortController')`)。
 *  ② useCopilotContext().interruptEventQueue 在 legacy flow 下不会被 `on_interrupt` 填充
 *     (ag-ui-langgraph 发的是 custom event,不是标准 RUN_FINISHED interrupt),故
 *     resolveInterruptEvent 路径也无效。
 *  ③ CopilotKit v1.66 的主入口(v1)<-> v2/headless 子路径 存在双 Context 单例
 *     (DnlgZWST 内联 CopilotKitContext vs dist/v2/context.mjs),v2 headless hook 与 v1
 *     provider 混用会抛 "must be used within CopilotKitProvider"。故不走 useInterrupt(v2)。
 *
 * 直接对 agent 实例调 `agent.runAgent(params)`(方法调用,`this` 正确):走 AG-UI 协议直发
 * `forwardedProps`(camelCase),后端 ag_ui Pydantic model(to_camel alias + populate_by_name)
 * 同收驼峰/蛇形。ag-ui-langgraph 读 input.forwarded_props['command']['resume'](无驼峰 key,
 * camel_to_snake 不改),resume payload 原样进 interrupt() 返回值。
 */
export const APPROVE_PAYLOAD = { approved: true } as const;

/** 后端 ag-ui-langgraph 发的 legacy interrupt 事件名(copilotkit_interrupt 包装)。 */
const INTERRUPT_EVENT_NAME = "on_interrupt";

export interface UseApprovalArgs {
  /** 来自 useCoAgent 的 state(用于判断 awaitingApproval) */
  state: AgentState | undefined;
  /**
   * 与 useCoAgent 同源的 HttpAgent 实例(由 CopilotProvider 透传,即注册进 CopilotKit
   * agents__unsafe_dev_only 的那个)。直接对它调 runAgent,保证 resume 的 SSE 事件
   * 回流到 useCoAgent 订阅的同一实例,从而 state.design/state.files 自动更新。
   */
  agent: AbstractAgent | undefined;
  /** useCoAgent 的 running:agent 仍在跑时不判 stall(避免正常生成中误报)。 */
  running?: boolean;
}

export interface UseApprovalReturn {
  /** 是否处于"PRD 已产、等待用户批准"态:prd 有 + design/files 都无 */
  awaitingApproval: boolean;
  /** 是否捕获到后端 on_interrupt 暂停信号(影响按钮副文案) */
  hasInterrupt: boolean;
  /** 批准动作进行中(按钮 loading) */
  approving: boolean;
  /** 批准后较久仍无 design/files(agent 不在跑)——疑似 resume 后生成失败/死锁 */
  stalled: boolean;
  /** 触发批准 resume */
  approve: () => Promise<void>;
}

/** 批准后多久仍无进展视为"死锁"(毫秒)。LLM 生成正常会更早出 design;超时给逃生出口。 */
const STALL_MS = 20000;

export function useApproval({ state, agent, running }: UseApprovalArgs): UseApprovalReturn {
  const [approving, setApproving] = useState(false);
  const [interrupted, setInterrupted] = useState(false);
  // 最近一次点击"批准方案"的时间戳;用于检测 resume 后是否陷入死锁
  // (write_design/write_code 失败 → 既无 design/files,agent 又不再 running)。
  const [approvedAt, setApprovedAt] = useState<number | null>(null);
  const [stalled, setStalled] = useState(false);

  const prdReady = !!state?.prd;
  const designReady = !!state?.design;
  const filesReady = !!(state?.files && state.files.length > 0);
  // PRD 产完、下一阶段(设计/代码)还没产出 → 等待批准。
  // interrupt 暂停时 running 也为 false,故以产出物判断为主。
  const awaitingApproval = prdReady && !designReady && !filesReady;

  // 订阅 agent 事件,跟踪 on_interrupt 暂停态(仅用于按钮副文案准确性)。
  // 复刻 CopilotKit useInterrupt 的 legacy 检测:on_interrupt 在 RUN_FINISHED 前到达,
  // 于 run finalizes 时落定 pending;新一轮 RUN_STARTED/RUN_FAILED 清除。
  useEffect(() => {
    if (!agent) return;
    let legacy = false;
    const subscription = agent.subscribe({
      onCustomEvent: ({ event }) => {
        if (event.name === INTERRUPT_EVENT_NAME) legacy = true;
      },
      onRunStartedEvent: () => {
        legacy = false;
        setInterrupted(false);
      },
      onRunFinalized: () => {
        if (legacy) setInterrupted(true);
        legacy = false;
      },
      onRunFailed: () => {
        legacy = false;
        setInterrupted(false);
      },
    });
    return () => subscription.unsubscribe();
  }, [agent]);

  // 死锁检测:一旦 design/files 到位(或 PRD 被清空),立即撤销 stall 标记。
  useEffect(() => {
    if (designReady || filesReady || !prdReady) setStalled(false);
  }, [designReady, filesReady, prdReady]);

  // 批准后若 STALL_MS 内仍无 design/files、且 agent 不在跑(approving 也已结束),
  // 视为 resume 后生成失败/死锁 —— 提示用户重试或重新描述需求。
  useEffect(() => {
    if (approvedAt == null) return;
    const id = window.setInterval(() => {
      const stillWaiting = prdReady && !designReady && !filesReady;
      if (
        stillWaiting &&
        !approving &&
        !running &&
        Date.now() - approvedAt > STALL_MS
      ) {
        setStalled(true);
      }
    }, 1000);
    return () => window.clearInterval(id);
  }, [approvedAt, prdReady, designReady, filesReady, approving, running]);

  const approve = useCallback(async () => {
    if (approving || !agent) return;
    setApproving(true);
    setStalled(false);
    setApprovedAt(Date.now());
    try {
      // 方法调用(保留 this),发 forwardedProps.command.resume={approved:true}。
      // agent.threadId 已由首轮 PM run 设置,resume POST 自动落到同一线程;该 run 的
      // STATE_SNAPSHOT(design/files)会通过订阅回流,useCoAgent state 随之更新。
      await agent.runAgent({
        forwardedProps: { command: { resume: { ...APPROVE_PAYLOAD } } },
      });
    } catch (err) {
      // 不抛:保持 UI 稳定;后端 RUN_FAILED 已通过 SSE 单独反映。
      console.error("[useApproval] agent.runAgent resume 失败:", err);
    } finally {
      // 短暂保持 loading;awaitingApproval 会随 design/files 到位自动消失。
      setTimeout(() => setApproving(false), 600);
    }
  }, [approving, agent]);

  return {
    awaitingApproval,
    hasInterrupt: interrupted,
    approving,
    stalled,
    approve,
  };
}
