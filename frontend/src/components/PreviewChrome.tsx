"use client";

import { useState, type ReactNode } from "react";

/**
 * 预览外壳共享组件 · atoms 浏览器 chrome。
 *
 * 统一 Sandpack 预览(内存 stub)与部署后 Vercel 真站点预览的视觉外壳,
 * 保持 atoms 浅色风格一致(三色圆点 + 地址栏 + build 徽标 + 刷新 + Supabase 明示条 +
 * 按 viewport 桌面/平板/手机尺寸化的舞台)。内部 iframe / overlay 由各预览组件以
 * `children` 注入(Sandpack 的编译 overlay、部署站点的原生 iframe 各自管理)。
 *
 * 仅工作在 frontend/。client-only(随消费它的预览组件动态加载)。
 */

export type Viewport = "desktop" | "tablet" | "mobile";

/** viewport → 尺寸(对齐原型 .preview-frame[data-vp=…]) */
export const VIEWPORT_SIZE: Record<Viewport, { width: string; height: string }> = {
  desktop: { width: "100%", height: "100%" },
  tablet: { width: "600px", height: "720px" },
  mobile: { width: "360px", height: "640px" },
};

export interface PreviewChromeProps {
  /** 地址栏文案(Sandpack: atoms.dev/preview · sandbox;部署站点: vercel.app host) */
  addressLabel: string;
  /** build 徽标状态(后端 Validator 结果;部署站点恒为 "passed") */
  buildStatus?: "passed" | "failed" | null;
  /** build 错误日志(展开时显示;仅 Sandpack 预览可能非空) */
  buildErrors?: string | null;
  /** build 徽标 hover title(默认按 passed/failed 给中文) */
  buildBadgeTitle?: string;
  /** Supabase 明示条内容(Sandpack: 内存 stub 提示;部署站点: 真后端提示) */
  supabaseNote: ReactNode;
  /** 刷新回调(Sandpack: 重载 bundler iframe;部署站点: 重载 vercel.app iframe) */
  onRefresh: () => void;
  /** 刷新按钮 title */
  refreshTitle?: string;
  /** iframe 尺寸预设(桌面/平板/手机) */
  viewport?: Viewport;
  /** 舞台内容(Sandpack iframe + overlay / 部署站点原生 iframe) */
  children: ReactNode;
}

export function PreviewChrome({
  addressLabel,
  buildStatus = null,
  buildErrors = null,
  buildBadgeTitle,
  supabaseNote,
  onRefresh,
  refreshTitle = "刷新预览",
  viewport = "desktop",
  children,
}: PreviewChromeProps) {
  const [showBuildLog, setShowBuildLog] = useState(false);
  const size = VIEWPORT_SIZE[viewport];

  const resolvedBuildTitle =
    buildBadgeTitle ??
    (buildStatus === "passed" ? "后端 vite build 通过" : "后端 vite build 失败");

  return (
    <div className="flex-1 min-h-0 flex flex-col bg-atoms-bg">
      {/* 浏览器 chrome(对齐原型 .frame-chrome) */}
      <div className="h-9 flex-shrink-0 flex items-center gap-2 px-3 border-b border-atoms-border bg-atoms-surface">
        <div className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-[#ff5f56]" />
          <span className="w-2.5 h-2.5 rounded-full bg-[#febc2e]" />
          <span className="w-2.5 h-2.5 rounded-full bg-[#28c840]" />
        </div>
        <div className="ml-2 flex-1 min-w-0 flex items-center justify-center">
          <div className="flex items-center gap-1.5 px-3 py-1 rounded-md bg-atoms-surface-2 border border-atoms-border font-mono text-[11px] text-atoms-text-2 max-w-[420px]">
            <svg
              width="10"
              height="10"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={2.4}
              className="text-atoms-accent flex-shrink-0"
            >
              <rect x="5" y="11" width="14" height="9" rx="2" />
              <path d="M8 11V8a4 4 0 018 0v3" />
            </svg>
            <span className="truncate">{addressLabel}</span>
          </div>
        </div>
        {/* 后端 build 徽标(点击展开/收起错误日志) */}
        {buildStatus && (
          <button
            onClick={() => setShowBuildLog((v) => !v)}
            className={`flex items-center gap-1 px-2 py-1 rounded-md font-mono text-[10.5px] border transition-colors ${
              buildStatus === "passed"
                ? "text-atoms-accent bg-atoms-accent-soft border-atoms-accent-line"
                : "text-red-600 bg-red-50 border-red-200"
            }`}
            title={resolvedBuildTitle}
          >
            <span
              className={`w-1.5 h-1.5 rounded-full ${
                buildStatus === "passed" ? "bg-atoms-accent" : "bg-red-500"
              }`}
            />
            build · {buildStatus === "passed" ? "passed" : "failed"}
          </button>
        )}
        <button
          onClick={onRefresh}
          className="w-7 h-7 flex items-center justify-center rounded-md text-atoms-text-3 hover:text-atoms-text hover:bg-atoms-surface-2 transition-colors"
          title={refreshTitle}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2}>
            <path d="M3 12a9 9 0 019-9 9 9 0 016.7 3M21 4v5h-5" />
            <path d="M21 12a9 9 0 01-9 9 9 9 0 01-6.7-3M3 20v-5h5" />
          </svg>
        </button>
      </div>

      {/* Supabase 明示条:Sandpack 预览跑内存 stub / 部署站点接真后端 */}
      <div className="flex-shrink-0 flex items-center gap-2 px-3 py-1.5 border-b border-atoms-border bg-atoms-accent-soft/40 font-mono text-[10.5px] leading-tight text-atoms-text-2">
        <svg
          width="11"
          height="11"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2.2}
          className="text-atoms-accent flex-shrink-0"
        >
          <circle cx="12" cy="12" r="10" />
          <path d="M12 16v-4M12 8h.01" />
        </svg>
        <span className="min-w-0">{supabaseNote}</span>
      </div>

      {/* 后端 build 错误日志(展开时回喂可视化) */}
      {showBuildLog && buildErrors && (
        <pre className="flex-shrink-0 max-h-32 overflow-auto scroll-atoms px-3 py-2 bg-red-50/60 border-b border-red-200 font-mono text-[11px] text-red-700 whitespace-pre-wrap">
          {buildErrors}
        </pre>
      )}

      {/* 预览舞台:居中 + 按 viewport 尺寸化 iframe 容器 */}
      <div className="flex-1 min-h-0 overflow-auto scroll-atoms p-6 flex items-start justify-center">
        <div
          className="relative bg-white border border-atoms-border rounded-xl shadow-md overflow-hidden transition-all duration-300"
          style={{
            width: size.width,
            height: size.height,
            maxWidth: "100%",
          }}
        >
          {children}
        </div>
      </div>
    </div>
  );
}
