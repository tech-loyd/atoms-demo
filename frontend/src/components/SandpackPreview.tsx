"use client";

import { useEffect, useMemo, useRef } from "react";
import {
  SandpackProvider,
  SandpackPreview as SandpackPreviewIframe,
  useSandpack,
  type SandpackFiles,
  type SandpackPreviewRef,
} from "@codesandbox/sandpack-react";
import type { ProjectFile } from "@/lib/types";
import { buildSandpackFiles, SANDBOX_DEPENDENCIES } from "@/lib/starterTemplate";
// Viewport 类型 + atoms 浏览器 chrome 抽到共享 PreviewChrome(部署后真站点预览复用)。
import { PreviewChrome, type Viewport } from "./PreviewChrome";

// 向后兼容:Canvas 已 `import type { Viewport } from "./SandpackPreview"`,这里 re-export 保持其导入不变。
export type { Viewport };

/**
 * Canvas 应用预览(Sandpack 真实时编译运行)。
 *
 * 把 Alex 产的 `state.files` + `STARTER_TEMPLATE`(运行壳)+ `SANDPACK_OVERRIDES`
 * (Supabase 内存 stub)交给 Sandpack,在浏览器内 vite 环境 iframe 里实时编译运行
 * 生成的 React 应用,用户可点、可交互(如打卡 toggle)。
 *
 * 视图:外层 atoms 浏览器 chrome(共享 `PreviewChrome`:三色圆点 + 地址栏 +
 *      build 徽标 + 刷新 + Supabase 明示条 + viewport 尺寸化舞台)+
 *      内层 SandpackPreview iframe + 状态/错误 overlay(loading 旋转、编译失败提示)。
 *      部署 ready 后 Canvas 改用 `DeployedPreview`(vercel.app 真站点)。
 *
 * 仅工作在 frontend/。组件需 client-side(iframe),在 Canvas 里以
 * `dynamic(() => import("./SandpackPreview"), { ssr: false })` 加载,规避 Next SSR。
 */

export interface SandpackPreviewProps {
  /** Alex 产的 src/*(为空时给空态) */
  files: ProjectFile[];
  /** agent 正在写的文件路径(标记 active,目前不渲染编辑器,仅元数据) */
  activePath?: string;
  /** iframe 尺寸预设 */
  viewport?: Viewport;
  /** 后端 Validator 的 build 结果(显示在地址栏右侧徽标) */
  buildStatus?: "passed" | "failed" | null;
  /** 后端回喂的 build 错误日志(展开时给用户看) */
  buildErrors?: string | null;
  /**
   * Sandpack 自身编译失败 / 超时回调(运行时编译态)。
   * Canvas 用它把"自动切 Preview"撤回到 Design 视图,让用户看到规划上下文。
   */
  onCompileError?: () => void;
}

export function SandpackPreview(props: SandpackPreviewProps) {
  const { files, activePath, viewport = "desktop", buildStatus, buildErrors, onCompileError } = props;

  // files → Sandpack files(随 files 引用变化重算;SandpackProvider 内部会 diff 重新编译)
  const sandpackFiles: SandpackFiles = useMemo(
    () => buildSandpackFiles(files, activePath),
    [files, activePath],
  );

  if (files.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="text-center">
          <div className="w-10 h-10 rounded-xl bg-atoms-surface-2 border border-atoms-border flex items-center justify-center mb-3 mx-auto">
            <span className="text-atoms-text-3 text-lg">⛏</span>
          </div>
          <div className="text-[14px] font-semibold mb-1">等待 Alex 产出代码</div>
          <p className="text-[12.5px] text-atoms-text-2 max-w-sm">
            代码生成完成后,这里会实时运行生成的应用(Sandpack 浏览器内编译)。
          </p>
        </div>
      </div>
    );
  }

  return (
    <SandpackProvider
      template="react-ts"
      files={sandpackFiles}
      customSetup={{ dependencies: SANDBOX_DEPENDENCIES }}
      options={{
        // 立即起 bundler(预览默认可见,不走 lazy)
        initMode: "immediate",
        autorun: true,
        recompileMode: "delayed",
        recompileDelay: 300,
      }}
      theme="light"
    >
      <PreviewBody
        viewport={viewport}
        buildStatus={buildStatus ?? null}
        buildErrors={buildErrors ?? null}
        onCompileError={onCompileError}
      />
    </SandpackProvider>
  );
}

/**
 * 预览主体:必须在 `<SandpackProvider>` 内(消费 useSandpack)。
 * 负责:浏览器 chrome + 尺寸化 iframe + 状态/错误 overlay + 手动刷新。
 */
function PreviewBody({
  viewport,
  buildStatus,
  buildErrors,
  onCompileError,
}: {
  viewport: Viewport;
  buildStatus: "passed" | "failed" | null;
  buildErrors: string | null;
  onCompileError?: () => void;
}) {
  const { sandpack } = useSandpack();
  const iframeRef = useRef<SandpackPreviewRef | null>(null);

  // status:initial/running → loading;timeout/error → 错误态;done/idle → 内容态。
  const status = sandpack.status;
  const compiling = status === "initial" || status === "running";
  const timedOut = status === "timeout";
  const compileError = sandpack.error;
  const showError = timedOut || !!compileError;

  // Sandpack 编译错 / 超时 → 上报 Canvas,让其撤回"自动切 Preview"到 Design 视图。
  useEffect(() => {
    if (showError) onCompileError?.();
  }, [showError, onCompileError]);

  const handleRefresh = () => {
    try {
      // SandpackClient 没暴露 refresh 方法,但暴露了它管理的 iframe 元素;
      // 直接 reload contentWindow 即可让最新 bundle 重新执行。
      const client = iframeRef.current?.getClient();
      const contentWindow = client?.iframe?.contentWindow;
      if (contentWindow) contentWindow.location.reload();
    } catch {
      /* ignore */
    }
  };

  return (
    <PreviewChrome
      addressLabel="atoms.dev/preview · sandbox"
      buildStatus={buildStatus}
      buildErrors={buildErrors}
      supabaseNote={
        <span className="min-w-0">
          预览跑的是<span className="text-atoms-text font-semibold"> 内存版 Supabase stub</span>
          (登录态 / 数据均为 demo);Code 视图见 Alex 的真实产出,真实登录与持久化在部署后的
          <span className="text-atoms-text"> Vercel 站点</span>。
        </span>
      }
      onRefresh={handleRefresh}
      viewport={viewport}
    >
      <SandpackPreviewIframe
        ref={iframeRef}
        showNavigator={false}
        showOpenInCodeSandbox={false}
        showRefreshButton={false}
        showSandpackErrorOverlay={false}
        className="!w-full !h-full"
        style={{ width: "100%", height: "100%", border: "none" }}
      />

      {/* loading overlay(编译中) */}
      {compiling && !showError && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-white/85 backdrop-blur-sm animate-fadeUp">
          <span className="w-6 h-6 rounded-full border-[2px] border-atoms-accent border-t-transparent animate-spin mb-3" />
          <div className="text-[12.5px] font-semibold text-atoms-text">
            {status === "initial" ? "启动 Sandpack bundler…" : "编译中…"}
          </div>
          <div className="text-[11px] text-atoms-text-3 mt-1 font-mono">
            react-ts · in-browser build
          </div>
          <div className="text-[10.5px] text-atoms-text-3 mt-3 max-w-[260px] text-center leading-relaxed">
            首次编译需在浏览器内 transpile react-dom,约 10-30s;后续改动增量重编译。
          </div>
        </div>
      )}

      {/* 错误 overlay(编译失败 / 超时) */}
      {showError && (
        <div className="absolute inset-0 overflow-auto scroll-atoms bg-white/95 backdrop-blur-sm p-5 animate-fadeUp">
          <div className="flex items-start gap-2.5 mb-2.5">
            <div className="w-7 h-7 rounded-full bg-red-50 text-red-500 flex items-center justify-center flex-shrink-0 text-sm font-semibold">
              !
            </div>
            <div className="min-w-0">
              <div className="text-[13px] font-semibold text-atoms-text">
                {timedOut ? "bundler 启动超时" : "编译错误"}
              </div>
              <div className="text-[11.5px] text-atoms-text-2 mt-0.5">
                {timedOut
                  ? "Sandpack bundler 较久未就绪,可点右上角刷新重试。"
                  : "生成的代码有错,Sandpack 编译失败(后端 Validator 会回喂 Alex 修复)。"}
              </div>
            </div>
          </div>
          {compileError && (
            <pre className="mt-2 p-3 rounded-lg bg-[#0c0d12] text-[11.5px] leading-[1.6] text-red-300 font-mono overflow-auto scroll-atoms whitespace-pre-wrap break-words">
              {compileError.title ? `${compileError.title}\n` : ""}
              {compileError.path ? `(${compileError.path}${compileError.line ? `:${compileError.line}` : ""})\n` : ""}
              {compileError.message}
            </pre>
          )}
          <button
            onClick={handleRefresh}
            className="mt-3 px-3 py-1.5 rounded-md bg-atoms-accent text-white text-[12px] font-medium hover:opacity-90 transition-opacity"
          >
            重新编译
          </button>
        </div>
      )}
    </PreviewChrome>
  );
}
