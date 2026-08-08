"use client";

import { useBackendStatus } from "./CopilotProvider";

/**
 * 后端连通性状态条。后端未起时显示醒目提示,不阻塞界面、不崩溃。
 */
export function StatusBar() {
  const { status, retry, lastChecked } = useBackendStatus();

  if (status === "online") {
    return (
      <div className="h-7 flex items-center gap-2 px-5 border-b border-atoms-border bg-atoms-surface text-[11.5px] font-mono text-atoms-text-3">
        <span className="w-1.5 h-1.5 rounded-full bg-green-500" />
        <span>后端已连接 · agent ready</span>
      </div>
    );
  }

  if (status === "checking") {
    return (
      <div className="h-7 flex items-center gap-2 px-5 border-b border-atoms-border bg-atoms-surface text-[11.5px] font-mono text-atoms-text-3">
        <span className="w-3 h-3 rounded-full border-[1.5px] border-atoms-text-3 border-t-transparent animate-spin" />
        <span>正在检查后端连接…</span>
      </div>
    );
  }

  // offline
  return (
    <div className="h-9 flex items-center gap-2 px-5 border-b border-amber-200 bg-amber-50 text-[11.5px] font-mono text-amber-700">
      <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
      <span>
        后端未连接(localhost:8000)—— chat 发消息会失败,但界面不会崩。启动后端后自动恢复。
      </span>
      <button
        onClick={() => retry()}
        className="ml-auto px-2 py-0.5 rounded border border-amber-300 bg-white text-amber-700 hover:bg-amber-100 transition-colors"
      >
        重试
      </button>
      {lastChecked && (
        <span className="opacity-60">
          上次检查 {new Date(lastChecked).toLocaleTimeString()}
        </span>
      )}
    </div>
  );
}
