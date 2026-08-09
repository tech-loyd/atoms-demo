"use client";

import { useEffect, useRef, useState } from "react";
import { PreviewChrome, type Viewport } from "./PreviewChrome";

/**
 * 部署后真站点预览:Canvas 预览 = iframe vercel.app。
 *
 * Sandpack in-browser bundler 依赖 CodeSandbox CDN,受限网络全不可达 → "一直编译中"/白屏。
 * 但 Vercel 部署的真站点(vercel.app)走 Vercel CDN,不受影响。`deploy_status="ready"` 后
 * Canvas 预览区从 `SandpackPreview`(CDN bundler)切换到本组件 —— 直接 `<iframe src={deployment_url}>`
 * 嵌入 Vercel 真站点,绕过 CodeSandbox CDN。
 *
 * 视觉:复用共享 `PreviewChrome`(Sandpack 同款 atoms 浏览器 chrome:三色圆点 + 地址栏显
 *      vercel.app + build passed 徽标 + 刷新 + Supabase 真后端明示条 + viewport 尺寸化舞台)。
 *      内层原生 iframe 接 deployment_url,带 referrerPolicy="no-referrer"(不把本页地址泄露给 Vercel)。
 *
 * 刷新:跨源 iframe 不能可靠读 contentWindow.location,故用 `key` 自增触发 iframe 重挂载
 *      (等价于完整重新加载 URL),比 `location.reload()` 在跨源下更稳。
 *
 * 仅工作在 frontend/。client-only(iframe),在 Canvas 里以
 * `dynamic(() => import("./DeployedPreview"), { ssr: false })` 加载,规避 Next SSR。
 */

export interface DeployedPreviewProps {
  /** 后端 deploy_app 写回的 vercel.app URL(形如 https://xxx.vercel.app);未部署时传 preview_url */
  deploymentUrl: string;
  /** iframe 尺寸预设(桌面/平板/手机,同 SandpackPreview) */
  viewport?: Viewport;
  /**
   * 外部驱动的刷新令牌(如 Canvas 的 build_seq)。变化 → remount iframe,重新请求 URL。
   * 用于迭代修改后:Validator 重建的 build 产物 dist/ 覆盖同 preview_url,需 remount 才能拉到最新
   * (配合后端 /preview no-cache)。部署后 vercel.app 场景不传(保持固定)。
   */
  changeToken?: number;
}

export function DeployedPreview({ deploymentUrl, viewport = "desktop", changeToken }: DeployedPreviewProps) {
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  // iframeKey:点刷新自增 → React remount iframe → 重新请求 vercel.app(跨源下比 reload() 稳)。
  const [iframeKey, setIframeKey] = useState(0);
  // loaded:首次加载完前显示 atoms loading overlay(onLoad 触发;切 URL / 刷新时重置)。
  const [loaded, setLoaded] = useState(false);

  // URL 变化(理论不会,部署后固定)/ 刷新 → 重新进入 loading。
  useEffect(() => {
    setLoaded(false);
  }, [deploymentUrl, iframeKey]);

  // 外部 changeToken(如 build_seq)变化 → remount iframe(拉最新 build 产物,迭代后预览刷新)。
  useEffect(() => {
    if (changeToken === undefined) return;
    setIframeKey((k) => k + 1);
  }, [changeToken]);

  const handleRefresh = () => {
    // 先尝试同源路径 reload(若 vercel.app 与本应用恰好同源,直接重载最快);
    // 跨源会抛错,catch 后走 key 自增重挂载。
    try {
      const cw = iframeRef.current?.contentWindow;
      if (cw) {
        cw.location.reload();
        return;
      }
    } catch {
      /* 跨源:走 key 自增 */
    }
    setIframeKey((k) => k + 1);
  };

  // 地址栏显示 host(去掉 https://);deploy ready 时 build 已通过(后端 Validator 在部署前跑)。
  const host = deploymentUrl.replace(/^https?:\/\//, "").replace(/\/$/, "");

  return (
    <PreviewChrome
      addressLabel={host || "vercel.app"}
      buildStatus="passed"
      buildBadgeTitle="部署成功 · Vercel 构建通过"
      supabaseNote={
        <span className="min-w-0">
          这是部署后的<span className="text-atoms-text font-semibold"> Vercel 真站点</span>
          ,接<span className="text-atoms-text"> 真实 Supabase 后端</span>
          (真注册 / 登录 / 持久化);预览区下方可切回 Sandpack 看 Alex 的源码改动。
        </span>
      }
      onRefresh={handleRefresh}
      refreshTitle="刷新 Vercel 站点"
      viewport={viewport}
    >
      <iframe
        key={iframeKey}
        ref={iframeRef}
        src={deploymentUrl}
        title="部署的应用预览"
        onLoad={() => setLoaded(true)}
        // 不加 sandbox:vercel.app 站点需要正常跑 JS / 表单 / cookie 才能真登录与 CRUD;
        // 站点自身 CSP 已约束。仅加 referrerPolicy 不把本页地址泄露给 Vercel。
        referrerPolicy="no-referrer"
        className="!w-full !h-full"
        style={{ width: "100%", height: "100%", border: "none", display: "block" }}
      />

      {/* loading overlay(首次加载 / 刷新中) */}
      {!loaded && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-white/85 backdrop-blur-sm animate-fadeUp">
          <span className="w-6 h-6 rounded-full border-[2px] border-atoms-accent border-t-transparent animate-spin mb-3" />
          <div className="text-[12.5px] font-semibold text-atoms-text">正在加载 Vercel 站点…</div>
          <div className="text-[11px] text-atoms-text-3 mt-1 font-mono truncate max-w-[260px]">{host}</div>
        </div>
      )}
    </PreviewChrome>
  );
}
