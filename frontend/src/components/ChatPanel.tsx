"use client";

import { useEffect, useRef } from "react";
import { CopilotChat } from "@copilotkit/react-ui";
import "@copilotkit/react-ui/styles.css";
import { useBackendStatus } from "./CopilotProvider";

/**
 * 左侧 Chat 面板。CopilotChat(V1,inline)自带输入框,撑满容器;
 * 发消息触发后端 LangGraph agent,state.prd/design/files 更新后右侧 Canvas 自动渲染。
 *
 * 欢迎页带 ?q= 进来:后端就绪(online)后对 agent 发首轮 runAgent({forwardedProps:{message:q}})
 * —— 直接走 AG-UI 协议触发后端 Emma 产 PRD。绕开了 CopilotKit 1.66 程序化发消息的限制:
 * ag-ui 的 RunAgentParameters 不含 message 字段(只允许 forwardedProps/tools/context/resume),
 * 标准 useCopilotChat 又 Omit 了 sendMessage、headless 版 sendMessage 是 premium(无 license 不发)。
 * 所以走 forwardedProps.message(同 useApproval 的 resume / useDeploy 的 action 模式),后端
 * DeployAwareLangGraphAGUIAgent 在 langgraph_default_merge_state 检测 forwarded_props.message
 * → 注入 HumanMessage 触发首轮。STATE_SNAPSHOT 回流到 useCoAgent,state 自动更新。发完清 URL 防重发。
 */
export function ChatPanel() {
  const { status, agent } = useBackendStatus();
  const sentRef = useRef(false);

  useEffect(() => {
    if (sentRef.current) return;
    if (status !== "online" || !agent) return; // 等后端就绪,否则首轮连不上
    const q = new URLSearchParams(window.location.search).get("q")?.trim();
    sentRef.current = true;
    if (!q) return;
    agent
      .runAgent({ forwardedProps: { message: q } })
      .catch((e) => console.error("[ChatPanel] runAgent 首轮失败:", e));
    // 清掉 ?q 防止刷新/返回时重复发送
    window.history.replaceState({}, "", window.location.pathname);
  }, [status, agent]);

  return (
    <aside className="w-[42%] min-w-[420px] max-w-[560px] flex flex-col border-r border-atoms-border">
      <div className="h-12 flex-shrink-0 flex items-center px-[22px] border-b border-atoms-border">
        <span className="font-mono text-[11.5px] text-atoms-text-3 uppercase tracking-wider">
          chat · 描述需求
        </span>
      </div>

      <div className="flex-1 copilot-chat-shell overflow-hidden">
        <CopilotChat
          className="h-full"
          labels={{
            title: "atoms",
            placeholder:
              "描述你想构建的应用,例如:做一个带登录的习惯打卡应用",
          }}
        />
      </div>
    </aside>
  );
}
