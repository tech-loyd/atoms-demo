"use client";

import { ChatPanel } from "./ChatPanel";
import { Canvas } from "./Canvas";
import { StatusBar } from "./StatusBar";

/**
 * 工作区 · 顶栏 + 左 Chat + 右 Canvas(对齐原型布局)。
 * 这一层是 client component,因为子组件用了 useCoAgent / useBackendStatus。
 */
export function Workspace() {
  return (
    <div className="relative h-screen w-screen overflow-hidden">
      {/* 背景层 */}
      <div className="pointer-events-none fixed inset-0 bg-grid" />
      <div className="pointer-events-none fixed inset-0 bg-glow" />

      <div className="relative z-10 flex flex-col h-full">
        <TopBar />
        <StatusBar />
        <main className="flex flex-1 min-h-0">
          <ChatPanel />
          <Canvas />
        </main>
      </div>
    </div>
  );
}

function TopBar() {
  return (
    <header className="h-14 flex items-center gap-5 px-5 border-b border-atoms-border bg-[rgba(246,246,246,0.78)] backdrop-blur-md animate-fadeDown">
      <div className="flex items-center gap-2.5">
        <div className="w-[22px] h-[22px] rounded-md bg-atoms-accent shadow-[0_2px_8px_rgba(66,103,255,0.35)] flex items-center justify-center">
          <span className="w-2 h-2 rounded-[2px] bg-white/95" />
        </div>
        <span className="text-[19px] font-semibold tracking-[-0.02em]">atoms</span>
      </div>
      <div className="font-mono text-[12px] text-atoms-text-3 flex items-center gap-2">
        <span className="text-atoms-text-2">workspace</span>
        <span className="opacity-50">/</span>
        <span>session</span>
        <span className="ml-1 px-[7px] py-0.5 border border-atoms-border-strong rounded text-[10.5px] text-atoms-text-2 bg-atoms-surface">
          main
        </span>
      </div>
    </header>
  );
}
