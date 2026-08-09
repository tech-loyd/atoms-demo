"use client";

import { useCallback, useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { useCoAgent } from "@copilotkit/react-core";
import { AGENT_NAME } from "@/lib/constants";
import type { AgentState } from "@/lib/types";
import { deriveStage } from "@/lib/types";
import { useApproval } from "@/lib/useApproval";
import { useDeploy } from "@/lib/useDeploy";
import { PRDCard } from "./PRDCard";
import { DesignCard } from "./DesignCard";
import { CodeView } from "./CodeView";
import { ApproveBar } from "./ApproveBar";
import { DeployBar } from "./DeployBar";
import { useBackendStatus } from "./CopilotProvider";
import type { Viewport } from "./SandpackPreview";

// Sandpack 依赖浏览器 iframe,必须 client-only(规避 Next SSR 对 window 的访问)。
const SandpackPreview = dynamic(
  () => import("./SandpackPreview").then((m) => m.SandpackPreview),
  {
    ssr: false,
    loading: () => (
      <div className="flex-1 flex items-center justify-center">
        <span className="w-5 h-5 rounded-full border-[1.5px] border-atoms-accent border-t-transparent animate-spin" />
      </div>
    ),
  },
);

// 部署后真站点预览:iframe 加载 vercel.app,同样 client-only。
const DeployedPreview = dynamic(
  () => import("./DeployedPreview").then((m) => m.DeployedPreview),
  {
    ssr: false,
    loading: () => (
      <div className="flex-1 flex items-center justify-center">
        <span className="w-5 h-5 rounded-full border-[1.5px] border-atoms-accent border-t-transparent animate-spin" />
      </div>
    ),
  },
);

/**
 * 右侧 Canvas · 三视图 Design / Code / Preview(此顺序)。
 *
 * 视图职责:
 *   - Design 视图(规划阶段,默认):Emma 的 PRD + HITL 批准 + Bob 的设计(前后端架构 + 数据库表)。
 *   - Code 视图:Alex 生成的源码(CodeView,文件树 + 高亮)。
 *   - Preview 视图:运行生成的应用(Sandpack / 后端 build 预览 / Vercel 部署)。
 *
 * 自动切(用户手动切过 tab 后停止):
 *   - empty / prd / design → Design 视图(Emma 规划、用户确认、Bob 设计都在此,tab 不切)。
 *   - files 到位(Alex 写完)→ Preview 视图(运行应用)。
 *
 * 状态分流:deriveStage(state) ∈ empty / prd / design / files。
 */
type View = "design" | "code" | "preview";

export function Canvas() {
  const { state, running } = useCoAgent<AgentState>({
    name: AGENT_NAME,
    initialState: { requirement: "", prd: null, design: null },
  });
  const { status, agent } = useBackendStatus();
  // 默认 Design 视图:进来就看规划(Emma 的 PRD 也归此)。
  const [view, setView] = useState<View>("design");
  const [viewport, setViewport] = useState<Viewport>("desktop");
  // 用户是否手动切过 view;未手动切 → 自动切(files 到位 → preview)。
  const [userPickedView, setUserPickedView] = useState(false);
  // 预览 iframe 的 remount 令牌:build_seq 递增时自增 → DeployedPreview remount 拉最新 build 产物。
  const [previewKey, setPreviewKey] = useState(0);

  // HITL 批准:直接对 agent 实例调 runAgent,发 forwardedProps.command.resume。
  const { awaitingApproval, hasInterrupt, approving, stalled, approve } = useApproval({
    state,
    agent,
    running,
  });

  // 部署:点"部署"→ agent.runAgent({forwardedProps:{action:"deploy"}})→ 后端 deploy_app。
  const { deploymentUrl, deployStatus, deploying, deploySyncLost, deploy, clearSyncLost } = useDeploy({ state, agent });

  // "重新描述需求"出口:聚焦左侧 chat 输入框,引导用户调整后重发。
  const handleRedescribe = useCallback(() => {
    const ta = window.document.querySelector<HTMLTextAreaElement>("textarea");
    if (ta) {
      ta.focus();
      ta.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, []);

  const stage = deriveStage(state);
  const prd = state?.prd ?? null;
  const design = state?.design ?? null;
  const files = state?.files;
  const filesCount = files?.length ?? 0;
  const buildStatus = state?.build_status ?? null;
  const buildErrors = state?.build_errors ?? null;
  // 代码产出 + Validator build 通过才允许部署。
  const canDeploy = filesCount > 0 && buildStatus === "passed";
  const deployedReady = deployStatus === "ready" && !!deploymentUrl;
  const previewUrl = state?.preview_url ?? null;
  const hasBackendPreview = !!previewUrl && buildStatus === "passed";

  // view 自动切:files 到位(Alex 写完)→ Preview;其余 → Design(规划阶段始终在 Design 视图)。
  useEffect(() => {
    if (userPickedView) return;
    setView(stage === "files" ? "preview" : "design");
  }, [stage, userPickedView]);

  // build_seq 递增(Validator 跑完一次新 build,含迭代修改后的重建)→ remount 预览 iframe,
  // 拉最新 build 产物。配合后端 /preview no-cache,改完代码预览能看到最新效果。
  const buildSeq = state?.build_seq ?? 0;
  useEffect(() => {
    if (buildSeq > 0) setPreviewKey((k) => k + 1);
  }, [buildSeq]);

  const pickView = useCallback((v: View) => {
    setUserPickedView(true);
    setView(v);
  }, []);

  const showViewportTabs = view === "preview" && filesCount > 0;

  return (
    <section className="flex-1 flex flex-col min-w-0">
      {/* Canvas 工具栏 */}
      <div className="h-12 flex-shrink-0 flex items-center gap-3 px-[22px] border-b border-atoms-border animate-fadeDown">
        {/* Design / Code / Preview 切换(顺序即规划→代码→运行) */}
        <div className="flex gap-0.5 p-[3px] bg-atoms-surface-2 border border-atoms-border rounded-[9px]">
          <ViewTab active={view === "design"} onClick={() => pickView("design")} label="Design" />
          <ViewTab active={view === "code"} onClick={() => pickView("code")} label="Code" />
          <ViewTab active={view === "preview"} onClick={() => pickView("preview")} label="Preview" />
        </div>

        {/* viewport tab 仅 Preview · 有 files 时显示(接 Sandpack 尺寸) */}
        {showViewportTabs && (
          <div className="flex gap-0.5 p-[3px] bg-atoms-surface-2 border border-atoms-border rounded-[9px]">
            <ViewportTab active={viewport === "desktop"} onClick={() => setViewport("desktop")} label="桌面" />
            <ViewportTab active={viewport === "tablet"} onClick={() => setViewport("tablet")} label="平板" />
            <ViewportTab active={viewport === "mobile"} onClick={() => setViewport("mobile")} label="手机" />
          </div>
        )}

        <div className="flex items-center gap-2 px-3 py-1.5 bg-atoms-surface border border-atoms-border rounded-[7px] font-mono text-[11.5px] text-atoms-text-3 max-w-[360px]">
          <span className={`w-1.5 h-1.5 rounded-full ${stageDotColor(stage)}`} />
          <span className="text-atoms-text-2">
            {view === "design"
              ? `design · ${design ? "设计已生成" : prd ? "PRD 已生成" : running ? "规划中" : "等待生成"}`
              : view === "code"
                ? `workspace · ${filesCount > 0 ? `${filesCount} files` : "等待生成"}`
                : deployedReady
                  ? `canvas · 应用预览`
                  : `canvas · ${filesCount > 0 ? "应用预览" : "等待生成"}`}
          </span>
        </div>

        {/* 右侧:部署按钮常驻(build 未就绪时内部显示禁用态;部署后显示固定 vercel 链接) */}
        <DeployBar
          canDeploy={canDeploy}
          deployStatus={deployStatus}
          deploymentUrl={deploymentUrl}
          deploying={deploying}
          deploySyncLost={deploySyncLost}
          onDeploy={deploy}
          onDismissSyncLost={clearSyncLost}
        />
      </div>

      {/* 内容区:按视图分流 */}
      {view === "design" ? (
        // Design 视图:Emma PRD + HITL 批准 + Bob 设计(规划阶段全程在此)
        <div className="flex-1 min-h-0 overflow-y-auto scroll-atoms">
          <div className="max-w-[680px] mx-auto p-7 flex flex-col gap-3">
            {stage === "empty" ? (
              <EmptyState status={status} running={running} />
            ) : (
              <>
                {prd && <PRDCard prd={prd} />}

                {/* HITL 批准入口(Emma PRD 后) */}
                {awaitingApproval && (
                  <ApproveBar
                    approving={approving}
                    hasInterrupt={hasInterrupt}
                    stalled={stalled}
                    onApprove={approve}
                    onRetry={approve}
                    onRedescribe={handleRedescribe}
                  />
                )}

                {/* Bob 设计(批准后产出;与 PRD 同在 Design 视图,tab 不切) */}
                {design && <DesignCard design={design} />}
              </>
            )}
          </div>
        </div>
      ) : view === "code" ? (
        // Code 视图:Alex 生成的源码
        <div className="flex-1 min-h-0">
          <CodeView files={files} running={running} />
        </div>
      ) : (
        // Preview 视图:运行应用(Alex 写完 files 才有内容)
        <div className="flex-1 min-h-0 flex flex-col">
          {filesCount > 0 ? (
            hasBackendPreview ? (
              <DeployedPreview deploymentUrl={previewUrl!} viewport={viewport} changeToken={previewKey} />
            ) : (
              <SandpackPreview
                files={files!}
                activePath={state?.active_file}
                viewport={viewport}
                buildStatus={buildStatus}
                buildErrors={buildErrors}
              />
            )
          ) : (
            <PreviewEmpty />
          )}
        </div>
      )}
    </section>
  );
}

/** stage → 工具栏圆点颜色(对应角色:prd=Emma 蓝,design=Bob 紫,files=Alex 黑) */
function stageDotColor(stage: ReturnType<typeof deriveStage>) {
  if (stage === "design") return "bg-atoms-bob";
  if (stage === "files") return "bg-atoms-alex";
  if (stage === "prd") return "bg-atoms-accent";
  return "bg-atoms-text-3";
}

function viewportLabel(v: Viewport) {
  return v === "desktop" ? "桌面" : v === "tablet" ? "平板" : "手机";
}

function ViewTab({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button
      onClick={onClick}
      className={`h-[26px] px-3 rounded-md text-[11px] font-medium flex items-center justify-center transition-all ${
        active ? "bg-atoms-surface text-atoms-accent shadow-sm" : "text-atoms-text-3 hover:text-atoms-text-2"
      }`}
    >
      {label}
    </button>
  );
}

function ViewportTab({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button
      onClick={onClick}
      className={`h-[26px] px-2.5 rounded-md text-[11px] flex items-center justify-center transition-all ${
        active ? "bg-atoms-surface text-atoms-accent shadow-sm" : "text-atoms-text-3 hover:text-atoms-text-2"
      }`}
    >
      {label}
    </button>
  );
}

/** Preview 视图空态:Alex 还没生成代码(files 未产)。 */
function PreviewEmpty() {
  return (
    <div className="flex-1 flex items-center justify-center">
      <div className="flex flex-col items-center text-center px-6">
        <div className="w-10 h-10 rounded-xl bg-atoms-surface-2 border border-atoms-border flex items-center justify-center mb-3 text-atoms-text-3">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
            <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7z" />
            <circle cx="12" cy="12" r="3" />
          </svg>
        </div>
        <div className="text-[14px] font-semibold mb-1">等待 Alex 生成代码</div>
        <p className="text-[12.5px] text-atoms-text-2 max-w-xs leading-relaxed">
          PRD 批准、Bob 产出设计后,Alex 会生成应用代码,完成后在此实时运行预览。
        </p>
      </div>
    </div>
  );
}

function EmptyState({ status, running }: { status: "checking" | "online" | "offline"; running: boolean }) {
  const offline = status === "offline";
  const checking = status === "checking";

  return (
    <div className="rounded-2xl border border-dashed border-atoms-border-strong bg-atoms-surface/60 p-10 flex flex-col items-center text-center animate-fadeUp">
      {offline ? (
        <>
          <div className="w-10 h-10 rounded-full bg-red-50 text-red-500 flex items-center justify-center mb-3 text-xl">
            !
          </div>
          <div className="text-[15px] font-semibold mb-1">后端未连接</div>
          <p className="text-[13px] text-atoms-text-2 max-w-sm">
            无法访问 <code className="font-mono text-[12px] text-atoms-text">localhost:8000/api/copilotkit</code>。
            请先启动后端(见 backend/README.md);启动后此区域会自动恢复。
          </p>
        </>
      ) : running ? (
        <>
          <span className="w-5 h-5 rounded-full border-[1.5px] border-atoms-accent border-t-transparent animate-spin mb-3" />
          <div className="text-[15px] font-semibold mb-1">Emma 正在梳理需求…</div>
          <p className="text-[13px] text-atoms-text-2">
            PM 节点调用 LLM 生成结构化 PRD,完成后会在此处渲染。
          </p>
        </>
      ) : (
        <>
          <div className="w-10 h-10 rounded-xl bg-atoms-accent-soft text-atoms-accent flex items-center justify-center mb-3">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path d="M12 2l2.39 7.36H22l-6.18 4.49L18.21 22 12 17.27 5.79 22l2.39-8.15L2 9.36h7.61z" />
            </svg>
          </div>
          <div className="text-[15px] font-semibold mb-1">
            {checking ? "正在检查后端连接…" : "描述需求,生成 PRD"}
          </div>
          <p className="text-[13px] text-atoms-text-2 max-w-sm">
            在左侧输入"做一个带登录的习惯打卡应用",Emma(PM)会产出 PRD,你批准后 Bob 生成设计、Alex 生成代码,Alex 完工后会自动切到应用预览。
          </p>
        </>
      )}
    </div>
  );
}
