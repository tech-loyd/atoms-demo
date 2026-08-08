"use client";

/**
 * ApproveBar · HITL 批准入口。
 * PRD 产完、等用户批准时显示"批准方案"按钮 + 次要"再改改"(回 chat 迭代)提示。
 *
 * 点"批准方案" → 调 useApproval.approve()(对 agent 实例调 runAgent,发 resume payload)。
 * 视觉:atoms accent 主按钮 + 浅色虚线容器呼应"等待人为决策"。
 *
 * 死锁逃生口:若批准后较久仍无 design/files(useApproval.stalled),底部追加
 * 一段警示 + [重试批准](重发 resume)/ [重新描述需求](聚焦左侧 chat 输入框),
 * 避免 resume 后 write_design/write_code 失败时 ApproveBar 恒显、用户无路可走。
 */
export function ApproveBar({
  approving,
  hasInterrupt,
  stalled,
  onApprove,
  onRetry,
  onRedescribe,
}: {
  approving: boolean;
  /** 是否有待处理 LangGraph Interrupt(影响按钮副文案) */
  hasInterrupt: boolean;
  /** 批准后疑似死锁(超时且无进展)——显示重试/重新描述出口 */
  stalled?: boolean;
  onApprove: () => void;
  /** 重试批准:再发一次 resume(useApproval.approve) */
  onRetry: () => void;
  /** 重新描述需求:聚焦左侧 chat 输入框,引导用户调整后重发 */
  onRedescribe: () => void;
}) {
  return (
    <div className="mt-3 rounded-2xl border border-dashed border-atoms-accent-line bg-atoms-accent-soft/40 p-4 flex flex-col gap-3 animate-fadeUp">
      <div className="flex items-start gap-2.5">
        <span className="flex-shrink-0 w-6 h-6 rounded-full bg-atoms-accent text-white flex items-center justify-center mt-px">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.6}>
            <path d="M9 11l3 3L22 4" />
            <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
          </svg>
        </span>
        <div className="flex-1 min-w-0">
          <div className="text-[13.5px] font-semibold text-atoms-text">
            批准这份方案,开始生成
          </div>
          <p className="text-[12px] text-atoms-text-2 mt-0.5">
            确认后,Bob 将产出数据模型,Alex 将生成代码。
            <span className="text-atoms-text-3">
              {" "}
              {hasInterrupt
                ? "（agent 已暂停等待确认）"
                : "（可在左侧继续追问以调整 PRD）"}
            </span>
          </p>
        </div>
      </div>

      <div className="flex items-center gap-2 pl-8">
        <button
          onClick={onApprove}
          disabled={approving}
          className={`inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-[13px] font-semibold text-white shadow-sm transition-all ${
            approving
              ? "bg-atoms-accent/70 cursor-wait"
              : "bg-atoms-accent hover:bg-atoms-accent/90 active:scale-[0.98]"
          }`}
        >
          {approving ? (
            <>
              <span className="w-3.5 h-3.5 rounded-full border-[1.5px] border-white/70 border-t-transparent animate-spin" />
              提交中…
            </>
          ) : (
            <>
              批准方案
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.6}>
                <path d="M5 12h14M13 6l6 6-6 6" />
              </svg>
            </>
          )}
        </button>
        <span className="font-mono text-[11px] text-atoms-text-3">
          ⏎ 批准 = resume agent
        </span>
      </div>

      {stalled && (
        <div className="ml-8 mt-1 rounded-xl border border-red-200 bg-red-50/80 px-3.5 py-3 flex flex-col gap-2.5 animate-fadeUp">
          <div className="flex items-start gap-2">
            <span className="flex-shrink-0 w-5 h-5 rounded-full bg-red-500 text-white flex items-center justify-center text-[11px] font-semibold mt-px">
              !
            </span>
            <p className="text-[12px] text-red-700 leading-relaxed">
              批准后较久未见进展,可能是后端生成失败或连接中断。
              可重试批准,或回到左侧对话调整需求后重新提交。
            </p>
          </div>
          <div className="flex items-center gap-2 pl-7">
            <button
              onClick={onRetry}
              disabled={approving}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-semibold text-white bg-red-500 hover:bg-red-600 active:scale-[0.98] disabled:opacity-60 transition-all"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.6}>
                <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
                <path d="M3 3v5h5" />
              </svg>
              重试批准
            </button>
            <button
              onClick={onRedescribe}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12px] font-medium text-red-700 bg-white border border-red-200 hover:bg-red-50 active:scale-[0.98] transition-all"
            >
              重新描述需求
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.4}>
                <path d="M5 12h14M13 6l6 6-6 6" />
              </svg>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
