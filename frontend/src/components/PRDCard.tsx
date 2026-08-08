"use client";

import type { PRD } from "@/lib/types";

/**
 * PRDCard · 渲染后端 LangGraph PM 节点产出的 PRD(标题/摘要/功能 tag/验收 ✓ 列表)。
 * 视觉沿用 atoms 浅色卡片容器。
 */
export function PRDCard({ prd }: { prd: PRD }) {
  return (
    <div
      data-agent="emma"
      className="relative bg-atoms-surface border border-atoms-border rounded-2xl shadow-sm animate-fadeUp"
    >
      {/* 卡片头:Emma · 产品 · 完成态 */}
      <div className="flex items-center gap-2.5 px-[15px] pt-[13px] pb-[11px]">
        <span className="w-6 h-6 rounded-full bg-atoms-bg border-2 border-atoms-bg flex items-center justify-center font-mono text-[11px] font-semibold text-atoms-accent ring-1 ring-atoms-accent">
          E
        </span>
        <span className="text-[14px] font-semibold">Emma</span>
        <span className="font-mono text-[10.5px] text-atoms-text-3 px-[7px] py-0.5 rounded bg-atoms-surface-2">
          产品
        </span>
        <span className="ml-auto flex items-center gap-1.5 font-mono text-[10.5px] text-atoms-accent">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3}>
            <path d="M5 13l4 4L19 7" />
          </svg>
          PRD 已生成
        </span>
      </div>

      {/* 卡片正文 */}
      <div className="px-[15px] pb-[15px] border-t border-atoms-border">
        <h3 className="text-[22px] font-semibold tracking-[-0.015em] mt-3.5 mb-1">
          {prd.title}
        </h3>
        <p className="text-[13px] text-atoms-text-2 mb-3">{prd.summary}</p>

        {prd.features?.length > 0 && (
          <>
            <div className="font-mono text-[10px] tracking-[0.1em] uppercase text-atoms-text-3 mt-3 mb-1.5">
              核心功能
            </div>
            <div className="flex flex-wrap gap-1.5">
              {prd.features.map((f, i) => (
                <span
                  key={f.slice(0, 16) + "-" + i}
                  className="text-[11.5px] px-[9px] py-1 rounded-full bg-atoms-surface-2 border border-atoms-border text-atoms-text-2"
                >
                  {f}
                </span>
              ))}
            </div>
          </>
        )}

        {prd.acceptanceChecks?.length > 0 && (
          <>
            <div className="font-mono text-[10px] tracking-[0.1em] uppercase text-atoms-text-3 mt-3 mb-1.5">
              验收标准
            </div>
            <div className="flex flex-col gap-[5px]">
              {prd.acceptanceChecks.map((a, i) => (
                <div key={a.slice(0, 16) + "-" + i} className="flex items-start gap-2 text-[12.5px] text-atoms-text-2">
                  <span className="flex-shrink-0 w-[15px] h-[15px] rounded-[4px] bg-atoms-accent-soft text-atoms-accent flex items-center justify-center text-[10px] mt-px">
                    ✓
                  </span>
                  <span>{a}</span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
