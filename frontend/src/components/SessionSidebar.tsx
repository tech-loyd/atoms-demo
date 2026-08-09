"use client";

import { useCallback, useEffect, useState } from "react";
import { BACKEND_ORIGIN } from "@/lib/constants";

/**
 * 左侧会话栏 · 历史会话列表(从后端 GET /api/threads 拉,Postgres 跨设备共享)。
 *
 * - 点一条:window.location.href = /workspace?t=<tid>(整页重载切换 → CopilotProvider
 *   用新 threadId 重建 HttpAgent → restore 自动拉该会话 state)。reload 式切换最可靠
 *   (CopilotKit Direct Connection 下 message state 无法可靠随 threadId 切换重置)。
 * - + 新建会话:清 localStorage 的 thread_id + 跳 /workspace(无 ?t → 新 threadId)。
 * - 当前会话高亮:mount 后读 URL ?t= 比对(用 state 避免 SSR/hydration mismatch)。
 */
export function SessionSidebar() {
  const [items, setItems] = useState<ThreadItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [currentTid, setCurrentTid] = useState<string | null>(null);

  const fetchThreads = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await fetch(`${BACKEND_ORIGIN}/api/threads`, { cache: "no-store" });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      setItems(Array.isArray(data.threads) ? (data.threads as ThreadItem[]) : []);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  // mount:拉列表 + 读当前 thread(SSR 后才拿得到 window)
  useEffect(() => {
    fetchThreads();
    setCurrentTid(new URLSearchParams(window.location.search).get("t"));
  }, [fetchThreads]);

  const openThread = (tid: string) => {
    if (tid === currentTid) return; // 已是当前会话,不重复 reload
    window.location.href = `/workspace?t=${encodeURIComponent(tid)}`;
  };

  const newThread = () => {
    try {
      window.localStorage.removeItem("atoms_thread_id");
    } catch {
      /* localStorage 不可用 —— 忽略,URL 无 ?t 仍会触发新 threadId */
    }
    window.location.href = "/workspace";
  };

  const deleteThread = async (tid: string) => {
    if (!window.confirm("确定删除该会话?此操作不可恢复。")) return;
    try {
      const resp = await fetch(`${BACKEND_ORIGIN}/api/threads/${encodeURIComponent(tid)}`, {
        method: "DELETE",
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      if (!data.ok) throw new Error(data.error || "删除失败");
      // 删的是当前会话 → 清 thread_id 跳新会话;否则刷新列表
      if (tid === currentTid) {
        try {
          window.localStorage.removeItem("atoms_thread_id");
        } catch {
          /* ignore */
        }
        window.location.href = "/workspace";
      } else {
        fetchThreads();
      }
    } catch (e) {
      window.alert(`删除失败:${e instanceof Error ? e.message : e}`);
    }
  };

  return (
    <aside className="w-60 flex-shrink-0 flex flex-col border-r border-atoms-border bg-atoms-surface/40">
      {/* 头部:标题 + 刷新 + 新建 */}
      <div className="h-12 flex-shrink-0 flex items-center gap-1.5 px-3 border-b border-atoms-border">
        <span className="font-mono text-[11px] text-atoms-text-3 uppercase tracking-wider flex-1">
          会话历史
        </span>
        <button
          onClick={fetchThreads}
          title="刷新列表"
          className="w-7 h-7 rounded-md flex items-center justify-center text-atoms-text-3 hover:text-atoms-text hover:bg-atoms-surface-2 transition-colors"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2}>
            <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
            <path d="M3 3v5h5" />
          </svg>
        </button>
        <button
          onClick={newThread}
          className="h-7 px-2.5 rounded-md text-[11.5px] font-medium text-atoms-accent bg-atoms-accent-soft hover:bg-atoms-accent hover:text-white transition-colors flex items-center gap-1"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.6}>
            <path d="M12 5v14M5 12h14" />
          </svg>
          新建
        </button>
      </div>

      {/* 列表 */}
      <div className="flex-1 min-h-0 overflow-y-auto scroll-atoms">
        {loading ? (
          <div className="p-5 text-center text-[12px] text-atoms-text-3">加载中…</div>
        ) : error ? (
          <div className="p-5 text-center">
            <div className="text-[12px] text-atoms-text-3 mb-2">加载失败({error})</div>
            <button
              onClick={fetchThreads}
              className="text-[11.5px] font-medium text-atoms-accent hover:underline"
            >
              重试
            </button>
          </div>
        ) : items.length === 0 ? (
          <div className="p-5 text-center text-[12px] text-atoms-text-3 leading-relaxed">
            还没有历史会话。
            <br />
            在右侧描述需求,生成第一个应用。
          </div>
        ) : (
          <ul className="py-1">
            {items.map((it) => {
              const active = it.thread_id === currentTid;
              return (
                <li key={it.thread_id} className="relative group">
                  <button
                    onClick={() => openThread(it.thread_id)}
                    className={`w-full text-left pl-3 pr-8 py-2 flex items-start gap-2 transition-colors ${
                      active ? "bg-atoms-accent-soft" : "hover:bg-atoms-surface-2"
                    }`}
                  >
                    <span
                      className={`w-1.5 h-1.5 rounded-full mt-[7px] flex-shrink-0 ${STAGE_DOT[it.stage] ?? "bg-atoms-text-3"}`}
                    />
                    <span className="min-w-0 flex-1">
                      <span
                        className={`block text-[12.5px] truncate ${
                          active ? "font-semibold text-atoms-accent" : "font-medium text-atoms-text"
                        }`}
                      >
                        {it.title || "未命名会话"}
                      </span>
                      <span className="block text-[10.5px] text-atoms-text-3 mt-0.5">
                        {STAGE_LABEL[it.stage] ?? it.stage}
                      </span>
                    </span>
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteThread(it.thread_id);
                    }}
                    title="删除会话"
                    className="absolute right-1.5 top-1.5 w-6 h-6 rounded flex items-center justify-center text-atoms-text-3 hover:text-red-500 hover:bg-red-50 opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity"
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2}>
                      <path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
                    </svg>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </aside>
  );
}

interface ThreadItem {
  thread_id: string;
  title: string;
  summary: string;
  stage: "files" | "design" | "prd" | "empty" | string;
}

const STAGE_LABEL: Record<string, string> = {
  files: "已生成",
  design: "已设计",
  prd: "规划中",
  empty: "空",
};

const STAGE_DOT: Record<string, string> = {
  files: "bg-atoms-alex",
  design: "bg-atoms-bob",
  prd: "bg-atoms-accent",
  empty: "bg-atoms-text-3",
};
