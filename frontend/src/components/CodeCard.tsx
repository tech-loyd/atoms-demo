"use client";

import type { ProjectFile } from "@/lib/types";

/**
 * CodeCard · Alex(Engineer)产出的精简卡片 · Preview 内的进度概览。
 * 订阅 `state.files`,显示文件进度 + 状态(done/active/queued),不展开全部代码。
 *
 * 完整代码浏览走 Canvas 的 Code 视图(CodeView:文件树 + prism 高亮)。
 * 本卡片只做"产出可见性":file-tree + 进度条 + 流式生成意图,
 * 引导用户切到 Code 视图看完整代码。
 *
 * 视觉复用 atoms 浅色卡片容器。
 */
export function CodeCard({
  files,
  running,
  onViewCode,
}: {
  files: ProjectFile[];
  /** agent 是否仍在跑(决定状态:running=true → "生成代码中",否则 "代码已生成") */
  running?: boolean;
  /** 点击"查看完整代码"回调(Canvas 切到 Code 视图) */
  onViewCode?: () => void;
}) {
  const total = files.length;
  const done = files.filter((f) => (f.status ?? "done") === "done").length;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;
  const hasActive = files.some((f) => f.status === "active");

  // 头部状态:有 active 文件 或 agent 在跑 → 生成中;否则完成。
  const inProgress = running || hasActive;

  return (
    <div
      data-agent="alex"
      className="relative bg-atoms-surface border border-atoms-border rounded-2xl shadow-sm animate-fadeUp"
    >
      {/* 卡片头:Alex · 工程 · 状态 */}
      <div className="flex items-center gap-2.5 px-[15px] pt-[13px] pb-[11px]">
        <span className="w-6 h-6 rounded-full bg-atoms-bg border-2 border-atoms-bg flex items-center justify-center font-mono text-[11px] font-semibold text-atoms-alex ring-1 ring-atoms-border-strong">
          A
        </span>
        <span className="text-[14px] font-semibold">Alex</span>
        <span className="font-mono text-[10.5px] text-atoms-text-3 px-[7px] py-0.5 rounded bg-atoms-surface-2">
          工程
        </span>
        <span
          className={`ml-auto flex items-center gap-1.5 font-mono text-[10.5px] ${
            inProgress ? "text-atoms-bob" : "text-atoms-accent"
          }`}
        >
          {inProgress ? (
            <>
              <span className="w-[9px] h-[9px] rounded-full border-[1.5px] border-atoms-bob border-t-transparent animate-spin" />
              生成代码中
            </>
          ) : (
            <>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3}>
                <path d="M5 13l4 4L19 7" />
              </svg>
              代码已生成
            </>
          )}
        </span>
      </div>

      {/* 卡片正文 */}
      <div className="px-[15px] pb-[15px] border-t border-atoms-border">
        {/* 进度条 */}
        <div className="flex items-center gap-2.5 mt-3.5 mb-3">
          <div className="flex-1 h-1 rounded-full bg-atoms-surface-3 overflow-hidden">
            <div
              className="h-full rounded-full bg-gradient-to-r from-atoms-accent to-atoms-accent-2 transition-[width] duration-500"
              style={{ width: `${inProgress ? Math.max(pct, 8) : 100}%` }}
            />
          </div>
          <span className="font-mono text-[11.5px] text-atoms-accent flex-shrink-0">
            {inProgress ? `${pct}%` : "100%"}
          </span>
        </div>

        {/* 文件列表(done/active/pending) */}
        <div className="font-mono text-[12px] flex flex-col gap-[3px]">
          {files.map((f) => {
            const name = f.path.split("/").pop() ?? f.path;
            const st = f.status ?? "done";
            return (
              <div
                key={f.path}
                className={`flex items-center gap-2 py-[3px] rounded ${
                  st === "active"
                    ? "bg-atoms-accent-soft px-1.5 -mx-1.5"
                    : "px-1.5 -mx-1.5"
                }`}
              >
                <span className="text-[11px] text-atoms-text-3 w-3 text-center flex-shrink-0">
                  {f.language === "css" ? "🎨" : f.language === "json" ? "{}" : f.language === "ts" ? "TS" : "⚛"}
                </span>
                <span
                  className={`truncate flex-1 ${
                    st === "done"
                      ? "text-atoms-text"
                      : st === "active"
                        ? "text-atoms-accent"
                        : "text-atoms-text-3"
                  }`}
                >
                  {f.path}
                </span>
                {st === "done" && (
                  <span className="text-atoms-accent text-[10px] flex-shrink-0">
                    ✓ done
                  </span>
                )}
                {st === "active" && (
                  <span className="text-atoms-accent text-[10px] flex-shrink-0 animate-pulse">
                    ▍
                  </span>
                )}
                {st === "queued" && (
                  <span className="text-atoms-text-3 text-[10px] flex-shrink-0">
                    queued
                  </span>
                )}
              </div>
            );
          })}
        </div>

        {/* 引导切 Code 视图 */}
        {onViewCode && (
          <button
            onClick={onViewCode}
            className="mt-3.5 w-full flex items-center justify-center gap-1.5 py-2 rounded-lg bg-atoms-surface-2 border border-atoms-border hover:border-atoms-border-strong hover:bg-atoms-surface-3 transition-colors text-[12px] text-atoms-text-2"
          >
            查看完整代码
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.4}>
              <path d="M5 12h14M13 6l6 6-6 6" />
            </svg>
          </button>
        )}
      </div>
    </div>
  );
}
