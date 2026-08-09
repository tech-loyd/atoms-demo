"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * DeployBar · 部署按钮 + 分享 URL。
 *
 * 五态视图(由 canDeploy + deployStatus + deploying + deploySyncLost 决定):
 *   idle     —— 可部署(files + build passed,未部署过):accent 主按钮"部署"。
 *   building —— Vercel 构建中(state.deploy_status="building" 或本地 deploying):灰底 loading。
 *   ready    —— 部署完成(state.deployment_url 可用):vercel.app URL 链接(新标签打开)+ "分享"(复制)。
 *   failed   —— 部署失败(state.deploy_status="failed"):红色"重试"。
 *   syncLost —— 部署结果未能同步(runAgent resolve 后 state 仍 null):
 *               琥珀色提示"请刷新或到 Vercel 控制台查看" + 重试 + 知道了。
 *
 * 触发:点"部署"/"重试" → onDeploy(useDeploy.deploy = 对 agent 实例调 runAgent,
 *       发 forwardedProps.action="deploy" → 后端调 deploy_app tool → state 回流)。
 *
 * 视觉沿用 atoms 浅色风格(#f6f6f6 / #4267ff / IBM Plex Sans)+ 三圆点分享图标。
 */
export function DeployBar({
  canDeploy,
  deployStatus,
  deploymentUrl,
  deploying,
  deploySyncLost,
  onDeploy,
  onDismissSyncLost,
}: {
  /** files + build_status="passed"(是否具备部署条件) */
  canDeploy: boolean;
  deployStatus: "building" | "ready" | "failed" | null;
  deploymentUrl: string | null;
  /** 本地 loading(点击 → state 回流之间的瞬间) */
  deploying: boolean;
  /** runAgent resolve 后 state 仍未回流(SSE 中断 / checkpoint 未落) */
  deploySyncLost: boolean;
  onDeploy: () => void;
  /** 用户点"知道了"关闭同步丢失提示 */
  onDismissSyncLost: () => void;
}) {
  // 部署按钮常驻右上角:build 未就绪(!canDeploy)时显示禁用态(可见但不可点),就绪后可部署。
  const building = deploying || deployStatus === "building";

  return (
    <div className="ml-auto flex items-center gap-2 animate-fadeUp">
      {building ? (
        <BuildingState />
      ) : deployStatus === "ready" && deploymentUrl ? (
        <ReadyState url={deploymentUrl} onDeploy={onDeploy} />
      ) : deployStatus === "failed" ? (
        <FailedState onRetry={onDeploy} />
      ) : deploySyncLost ? (
        <SyncLostState onRetry={onDeploy} onDismiss={onDismissSyncLost} />
      ) : !canDeploy ? (
        <DisabledState />
      ) : (
        <IdleState onDeploy={onDeploy} />
      )}
    </div>
  );
}

/** disabled:代码还没生成或 build 未通过 —— 灰按钮占位(常驻可见,不可点 + tooltip 提示先完成构建)。 */
function DisabledState() {
  return (
    <button
      disabled
      className="inline-flex items-center gap-1.5 h-[28px] px-3.5 rounded-lg bg-atoms-surface-2 border border-atoms-border text-atoms-text-3 text-[12px] font-semibold cursor-not-allowed"
      title="先完成代码生成与构建校验,即可部署"
    >
      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2}>
        <path d="M4.5 16.5L16.5 4.5M4.5 16.5H9M4.5 16.5V12M16.5 4.5H12M16.5 4.5V9" />
        <path d="M5 21h14" />
      </svg>
      部署
    </button>
  );
}

/** idle:可部署 —— accent 主按钮(对齐原型 btn-primary)。 */
function IdleState({ onDeploy }: { onDeploy: () => void }) {
  return (
    <button
      onClick={onDeploy}
      className="inline-flex items-center gap-1.5 h-[28px] px-3.5 rounded-lg bg-atoms-accent text-white text-[12px] font-semibold shadow-sm hover:bg-atoms-accent/90 active:scale-[0.98] transition-all"
      title="部署到 Vercel 并生成分享链接"
    >
      <svg
        width="13"
        height="13"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={2.2}
      >
        <path d="M4.5 16.5L16.5 4.5M4.5 16.5H9M4.5 16.5V12M16.5 4.5H12M16.5 4.5V9" />
        <path d="M5 21h14" />
      </svg>
      部署
    </button>
  );
}

/**
 * syncLost:部署结果未能同步。
 * runAgent resolve 后 state.deploy_status 仍为 null(SSE 被中间代理掐断 / checkpoint 未落)。
 * 友好提示 + 重试 + 知道了(关提示回 idle)—— 不静默回 idle 按钮("点了没反应")。
 */
function SyncLostState({
  onRetry,
  onDismiss,
}: {
  onRetry: () => void;
  onDismiss: () => void;
}) {
  return (
    <div className="flex items-center gap-1.5">
      <span
        className="inline-flex items-center gap-1.5 h-[28px] px-2.5 rounded-lg bg-amber-50 border border-amber-200 text-amber-700 text-[11px]"
        title="部署请求已发出,但结果未能同步回前端。可能是网络抖动或代理超时。"
      >
        <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
        部署结果未能同步,请刷新或到 Vercel 控制台查看
      </span>
      <button
        onClick={onRetry}
        className="inline-flex items-center gap-1.5 h-[28px] px-3 rounded-lg bg-atoms-accent text-white text-[12px] font-semibold shadow-sm hover:bg-atoms-accent/90 active:scale-[0.98] transition-all"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.6}>
          <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
          <path d="M3 3v5h5" />
        </svg>
        重试部署
      </button>
      <button
        onClick={onDismiss}
        className="inline-flex items-center h-[28px] px-2.5 rounded-lg text-atoms-text-2 text-[12px] font-medium border border-atoms-border hover:bg-atoms-surface-2 transition-all"
        title="关闭提示,回到可部署状态"
      >
        知道了
      </button>
    </div>
  );
}

/** building:Vercel 构建中 —— 灰底 loading(disabled)。 */
function BuildingState() {
  return (
    <div
      className="inline-flex items-center gap-2 h-[28px] px-3.5 rounded-lg bg-atoms-surface-2 border border-atoms-border text-atoms-text-2 text-[12px] font-medium"
      title="Vercel 正在构建,通常 30-90s"
    >
      <span className="w-3.5 h-3.5 rounded-full border-[1.5px] border-atoms-accent border-t-transparent animate-spin" />
      <span>部署中…</span>
      <span className="font-mono text-[10.5px] text-atoms-text-3">Vercel</span>
    </div>
  );
}

/** ready:URL 链接(新标签打开)+ 分享(复制链接)。 */
function ReadyState({ url, onDeploy }: { url: string; onDeploy: () => void }) {
  const { copied, copy } = useCopyLink(url);
  // 展示用 host(去掉 https://),更紧凑;title 给完整 URL。
  const host = url.replace(/^https?:\/\//, "").replace(/\/$/, "");

  return (
    <div className="flex items-center gap-1.5">
      {/* vercel.app URL:可点新标签打开 */}
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="group inline-flex items-center gap-1.5 h-[28px] pl-2.5 pr-3 rounded-lg bg-atoms-surface border border-atoms-border-strong text-atoms-text-2 hover:border-atoms-accent-line hover:bg-atoms-accent-soft transition-all max-w-[260px]"
        title={`在新标签打开:${url}`}
      >
        <svg
          width="11"
          height="11"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2.4}
          className="text-atoms-accent flex-shrink-0"
        >
          <path d="M10 13a5 5 0 007.5.5l3-3a5 5 0 00-7-7l-1.5 1.5" />
          <path d="M14 11a5 5 0 00-7.5-.5l-3 3a5 5 0 007 7l1.5-1.5" />
        </svg>
        <span className="font-mono text-[11.5px] text-atoms-text truncate group-hover:text-atoms-accent transition-colors">
          {host}
        </span>
        <svg
          width="10"
          height="10"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2.4}
          className="text-atoms-text-3 group-hover:text-atoms-accent flex-shrink-0 transition-colors"
        >
          <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" />
          <path d="M15 3h6v6M10 14L21 3" />
        </svg>
      </a>
      {/* 分享按钮:复制链接到剪贴板(对齐原型分享图标) */}
      <button
        onClick={copy}
        className={`inline-flex items-center gap-1.5 h-[28px] px-3 rounded-lg text-[12px] font-semibold border transition-all active:scale-[0.98] ${
          copied
            ? "bg-atoms-accent-soft border-atoms-accent-line text-atoms-accent"
            : "bg-atoms-accent border-transparent text-white hover:bg-atoms-accent/90"
        }`}
        title={copied ? "已复制到剪贴板" : "复制链接分享"}
      >
        {copied ? (
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.6}>
            <path d="M5 13l4 4L19 7" />
          </svg>
        ) : (
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2}>
            <circle cx="18" cy="5" r="3" />
            <circle cx="6" cy="12" r="3" />
            <circle cx="18" cy="19" r="3" />
            <path d="M8.6 13.5l6.8 4M15.4 6.5l-6.8 4" />
          </svg>
        )}
        {copied ? "已复制" : "分享"}
      </button>
      {/* 重新部署:固定链接,同 URL,更新线上站点为最新代码 */}
      <button
        onClick={onDeploy}
        className="inline-flex items-center gap-1.5 h-[28px] px-3 rounded-lg text-[12px] font-medium border border-atoms-border bg-atoms-surface text-atoms-text-2 hover:bg-atoms-surface-2 hover:text-atoms-text transition-all active:scale-[0.98]"
        title="重新部署(同链接,更新线上站点为最新代码)"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.4}>
          <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
          <path d="M3 3v5h5" />
        </svg>
        重新部署
      </button>
    </div>
  );
}

/** failed:错误 + 重试。 */
function FailedState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="flex items-center gap-1.5">
      <span
        className="inline-flex items-center gap-1.5 h-[28px] px-2.5 rounded-lg bg-red-50 border border-red-200 text-red-600 font-mono text-[11px]"
        title="Vercel 部署失败,可重试"
      >
        <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
        deploy · failed
      </span>
      <button
        onClick={onRetry}
        className="inline-flex items-center gap-1.5 h-[28px] px-3 rounded-lg bg-atoms-accent text-white text-[12px] font-semibold shadow-sm hover:bg-atoms-accent/90 active:scale-[0.98] transition-all"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.6}>
          <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
          <path d="M3 3v5h5" />
        </svg>
        重试部署
      </button>
    </div>
  );
}

/**
 * 复制链接到剪贴板,带 2s ✓ 反馈。
 * navigator.clipboard 优先(HTTPS / localhost);不可用或拒绝时降级 execCommand 兜底。
 */
function useCopyLink(url: string) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const id = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(id);
  }, [copied]);

  const copy = useCallback(async () => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(url);
        setCopied(true);
        return;
      }
    } catch {
      /* 走兜底 */
    }
    // 降级:临时 textarea + execCommand(老浏览器 / 非 HTTPS)
    try {
      const ta = window.document.createElement("textarea");
      ta.value = url;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      window.document.body.appendChild(ta);
      ta.select();
      window.document.execCommand("copy");
      window.document.body.removeChild(ta);
      setCopied(true);
    } catch {
      /* 剪贴板完全不可用:静默,不阻断 UI(URL 链接仍可手动复制 / 新标签打开) */
    }
  }, [url]);

  return { copied, copy };
}
