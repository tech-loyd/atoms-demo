"use client";

import { useMemo, useState } from "react";
import { Highlight, themes } from "prism-react-renderer";
import type { ProjectFile } from "@/lib/types";

/**
 * 代码视图:左文件树 + 右代码区(prism 深色高亮 + 行号)。
 *
 * files 为空(Alex 未产出)→ 渲染"等待生成"空态,不用 mock 假代码兜底,
 * 避免让人误以为代码是写死的。files 非空 → 展示 state.files 实时生成的真实代码。
 */
export function CodeView({ files, running }: { files?: ProjectFile[]; running?: boolean }) {
  const list = files ?? [];
  const [activePath, setActivePath] = useState<string | undefined>(list[0]?.path);
  const active = useMemo(
    () => list.find((f) => f.path === activePath) ?? list[0],
    [list, activePath],
  );
  const groups = useMemo(() => groupByDir(list), [list]);

  // 空态:Alex 还没产出。诚实提示,不用 mock 顶上。
  if (list.length === 0) {
    return <CodeEmpty running={running} />;
  }

  return (
    <div className="flex h-full">
      {/* 文件树 */}
      <aside className="w-[220px] flex-shrink-0 border-r border-atoms-border bg-atoms-surface overflow-y-auto scroll-atoms">
        <div className="sticky top-0 bg-atoms-surface font-mono text-[10px] text-atoms-text-3 uppercase tracking-wider px-3 py-2 border-b border-atoms-border">
          files · {list.length}
        </div>
        <div className="p-2">
          {Object.entries(groups).map(([dir, fs]) => (
            <div key={dir} className="mb-2">
              <div className="font-mono text-[10.5px] text-atoms-text-3 mb-1 px-2 truncate">
                {dir}/
              </div>
              {fs.map((f) => {
                const name = f.path.split("/").pop() ?? f.path;
                const isActive = f.path === active?.path;
                return (
                  <button
                    key={f.path}
                    onClick={() => setActivePath(f.path)}
                    className={`w-full text-left flex items-center gap-2 px-2 py-1.5 rounded-md text-[12px] font-mono transition-colors ${
                      isActive
                        ? "bg-atoms-accent-soft text-atoms-accent"
                        : "text-atoms-text-2 hover:bg-atoms-surface-2"
                    }`}
                  >
                    <FileIcon language={f.language} />
                    <span className="truncate flex-1">{name}</span>
                    {f.status === "done" && (
                      <span className="text-atoms-accent text-[10px]">✓</span>
                    )}
                    {f.status === "active" && (
                      <span className="text-atoms-bob text-[10px] animate-pulse">●</span>
                    )}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
      </aside>

      {/* 代码区(深色高亮) */}
      <div className="flex-1 flex flex-col min-w-0 bg-[#0c0d12]">
        {active && (
          <>
            <div className="flex items-center gap-2 px-4 h-10 flex-shrink-0 bg-[#15171d] border-b border-white/5 font-mono text-[11.5px]">
              <span className="text-white/30">▣</span>
              <span className="text-white/70 truncate">{active.path}</span>
              <span className="ml-auto text-white/30 uppercase tracking-wider text-[10px]">
                {active.language}
              </span>
            </div>
            <div className="flex-1 overflow-auto scroll-atoms">
              <Highlight
                theme={themes.vsDark}
                code={active.content.trimEnd()}
                language={active.language}
              >
                {({ className, style, tokens, getLineProps, getTokenProps }) => (
                  <pre
                    className={`${className} m-0 p-4 text-[12.5px] leading-[1.65]`}
                    style={{ ...style, background: "transparent" }}
                  >
                    {tokens.map((line, i) => {
                      const lineProps = getLineProps({ line });
                      return (
                        <div key={i} {...lineProps} className={`${lineProps.className} flex`}>
                          <span className="select-none text-white/20 pr-4 text-right w-[2.5rem] flex-shrink-0">
                            {i + 1}
                          </span>
                          <span className="flex-1">
                            {line.map((token, key) => (
                              <span key={key} {...getTokenProps({ token })} />
                            ))}
                          </span>
                        </div>
                      );
                    })}
                  </pre>
                )}
              </Highlight>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/** 空态:Alex 还没产出代码。深色背景匹配代码区,区分"生成中 / 等待"。 */
function CodeEmpty({ running }: { running?: boolean }) {
  return (
    <div className="h-full flex items-center justify-center bg-[#0c0d12]">
      <div className="flex flex-col items-center text-center px-6">
        {running ? (
          <>
            <span className="w-6 h-6 rounded-full border-[1.5px] border-atoms-accent border-t-transparent animate-spin mb-3" />
            <div className="text-[13px] font-semibold text-white/90 mb-1">正在生成应用…</div>
            <p className="text-[12px] text-white/40 max-w-xs leading-relaxed">
              Emma → Bob → Alex 三角色协作产出代码,完成后在此实时展示。
            </p>
          </>
        ) : (
          <>
            <div className="w-10 h-10 rounded-xl bg-white/5 border border-white/10 flex items-center justify-center mb-3 font-mono text-[14px] text-white/30">
              &lt;/&gt;
            </div>
            <div className="text-[13px] font-semibold text-white/90 mb-1">等待生成代码</div>
            <p className="text-[12px] text-white/40 max-w-xs leading-relaxed">
              描述需求并批准方案后,Alex(Engineer)会在此实时生成 React + Supabase 源码。
            </p>
          </>
        )}
      </div>
    </div>
  );
}

function groupByDir(files: ProjectFile[]): Record<string, ProjectFile[]> {
  const groups: Record<string, ProjectFile[]> = {};
  for (const f of files) {
    const parts = f.path.split("/");
    const dir = parts.length > 1 ? parts.slice(0, -1).join("/") : ".";
    (groups[dir] ??= []).push(f);
  }
  return groups;
}

function FileIcon({ language }: { language: ProjectFile["language"] }) {
  const icon =
    language === "css" ? "🎨" : language === "json" ? "{}" : language === "ts" ? "TS" : "⚛";
  return (
    <span className="text-[10px] text-atoms-text-3 w-3 inline-block text-center">
      {icon}
    </span>
  );
}
