"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

const HINTS = ["看板待办", "迷你商城", "咖啡官网", "SaaS 仪表盘"];

/**
 * 欢迎页(/)—— landing:hero + composer + hint chips + footer。
 * CTA / composer / hint 点击都跳 /workspace(带 ?q= 预填需求,工作区 ChatPanel 消费)。
 * 视觉沿用 atoms 浅色语言(网格背景 + accent 主色 + IBM Plex Sans)。
 */
export default function Home() {
  const router = useRouter();
  const [idea, setIdea] = useState("");
  const go = (q?: string) => {
    const v = (q ?? idea).trim();
    router.push(v ? `/workspace?q=${encodeURIComponent(v)}` : "/workspace");
  };

  return (
    <main className="relative min-h-screen">
      <div className="pointer-events-none fixed inset-0 bg-grid" />
      <div className="pointer-events-none fixed inset-0 bg-glow" />

      {/* nav */}
      <nav className="relative z-10 flex items-center gap-5 px-7 py-[18px] max-w-[1240px] mx-auto animate-fadeDown">
        <Link href="/" className="flex items-center gap-2.5">
          <span className="w-[22px] h-[22px] rounded-md bg-atoms-accent shadow-[0_2px_8px_rgba(66,103,255,0.35)] flex items-center justify-center">
            <span className="w-2 h-2 rounded-[2px] bg-white/95" />
          </span>
          <span className="text-[19px] font-semibold tracking-[-0.02em]">atoms</span>
        </Link>
        <Link
          href="/workspace"
          className="ml-auto text-[13.5px] font-medium bg-atoms-text text-white px-3.5 py-2 rounded-lg hover:bg-black transition-colors"
        >
          进入工作台
        </Link>
      </nav>

      {/* hero */}
      <section className="relative z-[5] max-w-[760px] mx-auto px-7 pt-20 pb-10 text-center">
        <div className="inline-flex items-center gap-2 font-mono text-[11.5px] tracking-[0.12em] uppercase text-atoms-accent bg-atoms-accent-soft px-3 py-1.5 rounded-full mb-7 animate-fadeUp">
          <span className="w-1.5 h-1.5 rounded-full bg-atoms-accent animate-pulse" />
          ATOMS · AI 创业团队
        </div>
        <h1
          className="text-[60px] font-semibold leading-[1.05] tracking-[-0.035em] mb-5 animate-fadeUp"
          style={{ animationDelay: "0.08s" }}
        >
          把想法变成
          <br />
          <em className="not-italic text-atoms-accent">可运行的应用</em>
        </h1>
        <p
          className="text-[18px] text-atoms-text-2 leading-[1.55] max-w-[560px] mx-auto mb-9 animate-fadeUp"
          style={{ animationDelay: "0.16s" }}
        >
          描述你的想法,
          <b className="text-atoms-text font-medium">Emma 规划 → Bob 设计 → Alex 生成</b>
          。几分钟后拿到能登录、能分享的真实全栈应用。
        </p>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            go();
          }}
          className="flex items-center gap-2 bg-atoms-surface border border-atoms-border-strong rounded-[14px] pl-[18px] pr-2 py-2 shadow-lg focus-within:border-atoms-accent/40 transition-colors animate-fadeUp"
          style={{ animationDelay: "0.24s" }}
        >
          <input
            value={idea}
            onChange={(e) => setIdea(e.target.value)}
            placeholder="想做点什么?比如:一个带登录的习惯打卡应用"
            className="flex-1 bg-transparent border-none outline-none text-[15.5px] py-2.5 placeholder:text-atoms-text-3"
          />
          <button
            type="submit"
            className="bg-atoms-accent text-white px-5 py-[11px] rounded-[10px] text-[14px] font-semibold flex items-center gap-1.5 hover:bg-[#3457ee] active:scale-95 transition-all whitespace-nowrap"
          >
            开始构建
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.4}>
              <path d="M5 12h14M13 6l6 6-6 6" />
            </svg>
          </button>
        </form>

        <div
          className="flex gap-2 justify-center mt-3.5 flex-wrap animate-fadeUp"
          style={{ animationDelay: "0.32s" }}
        >
          {HINTS.map((h) => (
            <button
              key={h}
              onClick={() => go(h)}
              className="font-mono text-[11.5px] text-atoms-text-2 px-3 py-1.5 bg-atoms-surface border border-atoms-border rounded-full hover:text-atoms-accent hover:border-atoms-accent hover:bg-atoms-accent-soft transition-all"
            >
              + {h}
            </button>
          ))}
        </div>
      </section>

      {/* footer */}
      <footer className="relative z-[5] text-center pt-7 pb-12 font-mono text-[11.5px] text-atoms-text-3">
        ⚡ 由 <span className="text-atoms-accent">atoms</span> 生成 · 一支 AI 团队,为你打工
      </footer>
    </main>
  );
}
