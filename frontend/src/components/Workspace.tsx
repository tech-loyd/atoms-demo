"use client";

import { useCallback, useEffect, useState } from "react";
import { ChatPanel } from "./ChatPanel";
import { Canvas } from "./Canvas";
import { SessionSidebar } from "./SessionSidebar";
import { StatusBar } from "./StatusBar";

/**
 * 工作区 · 顶栏 + 左 Chat + 右 Canvas(对齐原型布局)。
 * 这一层是 client component,因为子组件用了 useCoAgent / useBackendStatus。
 */
export function Workspace() {
  // 左侧会话栏的展开/收起(localStorage 记偏好,默认展开)。
  const [sidebarOpen, setSidebarOpen] = useState(true);
  useEffect(() => {
    try {
      if (window.localStorage.getItem("atoms_sidebar") === "0") setSidebarOpen(false);
    } catch {
      /* localStorage 不可用 —— 沿用默认展开 */
    }
  }, []);
  const toggleSidebar = useCallback(() => {
    setSidebarOpen((v) => {
      const nv = !v;
      try {
        window.localStorage.setItem("atoms_sidebar", nv ? "1" : "0");
      } catch {
        /* ignore */
      }
      return nv;
    });
  }, []);

  return (
    <div className="relative h-screen w-screen overflow-hidden">
      {/* 背景层 */}
      <div className="pointer-events-none fixed inset-0 bg-grid" />
      <div className="pointer-events-none fixed inset-0 bg-glow" />

      <div className="relative z-10 flex flex-col h-full">
        <TopBar sidebarOpen={sidebarOpen} onToggleSidebar={toggleSidebar} />
        <StatusBar />
        <main className="flex flex-1 min-h-0">
          {sidebarOpen && <SessionSidebar />}
          <ChatPanel />
          <Canvas />
        </main>
      </div>
    </div>
  );
}

function TopBar({ sidebarOpen, onToggleSidebar }: { sidebarOpen: boolean; onToggleSidebar: () => void }) {
  return (
    <header className="h-14 flex items-center gap-4 px-4 border-b border-atoms-border bg-[rgba(246,246,246,0.78)] backdrop-blur-md animate-fadeDown">
      <button
        onClick={onToggleSidebar}
        title={sidebarOpen ? "收起会话栏" : "展开会话栏"}
        className="w-8 h-8 -ml-0.5 rounded-md flex items-center justify-center text-atoms-text-2 hover:bg-atoms-surface-2 transition-colors"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2}>
          <path d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      </button>
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
