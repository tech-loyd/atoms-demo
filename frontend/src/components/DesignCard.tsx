"use client";

import type { Design, TableSchema } from "@/lib/types";

/**
 * DesignCard · Bob(Architect)产出的"前后端架构总览"。
 *
 * 三块(覆盖从前端到数据库的完整链路):
 * 1. 全栈架构分层:前端(React+Vite+Tailwind)⇄ 后端(Supabase:Auth·Postgres·RLS)
 * 2. 数据库表(主角):ER 风格大卡片,字段名 + 类型色彩徽章 + PK/FK 徽章 + FK→目标
 * 3. 外键关系小结 + "设计已就绪 → 进入编码"过渡条(design 后无 HITL,给明确收尾)
 *
 * 订阅 `state.design`,字段对齐后端 DesignSchema(见 types.ts)。
 * 主色 Bob 紫 atoms-bob;前端层用 atoms-accent(蓝)与后端层区分。
 */
export function DesignCard({ design }: { design: Design }) {
  const tables = design.supabase_tables ?? [];
  const pages = design.pages ?? [];

  // 业务表名集合(判断 FK 是否指向本 design 内的表 → 决定是否画关系)
  const tableNames = tables.map((t) => t.name);
  // 收集所有外键关系(checkins.habit_id → habits.id),用于"外键关系"小结
  const relations = tables.flatMap((t) =>
    (t.fields ?? [])
      .filter((f) => f.fk)
      .map((f) => ({ from: `${t.name}.${f.name}`, to: f.fk as string })),
  );
  // 有 user_id 字段 → 带 Supabase Auth + RLS(对齐后端 _render_rls 约定)
  const hasUserAuth = tables.some((t) => (t.fields ?? []).some((f) => f.name === "user_id"));

  return (
    <div
      data-agent="bob"
      className="relative bg-atoms-surface border border-atoms-border rounded-2xl shadow-md animate-fadeUp"
    >
      {/* 卡片头:Bob · 架构 · 设计已生成 */}
      <div className="flex items-center gap-2.5 px-[15px] pt-[13px] pb-[11px]">
        <span className="w-6 h-6 rounded-full bg-atoms-bg border-2 border-atoms-bg flex items-center justify-center font-mono text-[11px] font-semibold text-atoms-bob ring-1 ring-atoms-bob/30">
          B
        </span>
        <span className="text-[14px] font-semibold">Bob</span>
        <span className="font-mono text-[10.5px] text-atoms-text-3 px-[7px] py-0.5 rounded bg-atoms-surface-2">
          架构
        </span>
        <span className="ml-auto flex items-center gap-1.5 font-mono text-[10.5px] text-atoms-accent">
          <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={3}>
            <path d="M5 13l4 4L19 7" />
          </svg>
          设计已生成
        </span>
      </div>

      {/* 卡片正文 */}
      <div className="px-[15px] pb-[15px] border-t border-atoms-border">
        {/* ① 全栈架构分层 */}
        <ArchLayer type={design.product_type} hasUserAuth={hasUserAuth} />

        {/* ② 数据库表(主角,ER 风格) */}
        <div className="flex items-center gap-2 mt-1 mb-2">
          <span className="w-1.5 h-1.5 rounded-full bg-atoms-bob" />
          <span className="font-mono text-[12.5px] font-semibold text-atoms-text">数据模型</span>
          <span className="font-mono text-[11px] text-atoms-text-3">· {tables.length} 张表</span>
        </div>
        {tables.length === 0 ? (
          <div className="text-[12px] text-atoms-text-3 font-mono py-2">// 暂无表结构</div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {tables.map((t) => (
              <ERTableCard key={t.name} table={t} tableNames={tableNames} />
            ))}
          </div>
        )}

        {/* ③ 外键关系小结 */}
        {relations.length > 0 && (
          <div className="mt-3">
            <div className="font-mono text-[10px] uppercase tracking-[0.1em] text-atoms-text-3 mb-1.5">
              外键关系
            </div>
            <div className="flex flex-col gap-1">
              {relations.map((r, i) => (
                <div key={i} className="flex items-center gap-1.5 font-mono text-[10.5px] text-atoms-text-2">
                  <span className="px-1.5 py-px rounded bg-atoms-surface-2 border border-atoms-border">
                    {r.from}
                  </span>
                  <span className="text-atoms-bob">→</span>
                  <span className="px-1.5 py-px rounded bg-atoms-surface-2 border border-atoms-border">
                    {r.to}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 页面路由 */}
        {pages.length > 0 && (
          <>
            <div className="font-mono text-[10px] tracking-[0.1em] uppercase text-atoms-text-3 mt-3.5 mb-1.5">
              页面
            </div>
            <div className="flex flex-wrap gap-1.5">
              {pages.map((p, i) => (
                <span
                  key={p + "-" + i}
                  className="text-[11.5px] px-[9px] py-1 rounded-full bg-atoms-surface-2 border border-atoms-border text-atoms-text-2"
                >
                  {p}
                </span>
              ))}
            </div>
          </>
        )}

        {/* ④ 过渡条:设计已就绪 → 进入编码(design 后无 HITL,给第二步产出明确收尾) */}
        <div className="mt-3.5 flex items-center gap-2 rounded-lg border border-dashed border-atoms-border-strong bg-atoms-surface-2/60 px-3 py-2">
          <span className="w-1.5 h-1.5 rounded-full bg-atoms-accent" />
          <span className="text-[11.5px] text-atoms-text-2">设计已就绪</span>
          <span className="font-mono text-[10.5px] text-atoms-text-3">Bob → Alex</span>
          <span className="ml-auto flex items-center gap-1 font-mono text-[10.5px] text-atoms-alex">
            <span className="w-1 h-1 rounded-full bg-atoms-alex animate-pulse" />
            进入编码…
          </span>
        </div>
      </div>
    </div>
  );
}

/** 全栈架构分层:前端 ⇄ 后端(Supabase),标题点明"连后端数据库都有"。 */
function ArchLayer({ type, hasUserAuth }: { type: string; hasUserAuth: boolean }) {
  return (
    <div className="rounded-xl border border-atoms-border bg-gradient-to-br from-atoms-surface-2 to-atoms-surface p-3 mt-3.5">
      <div className="flex items-center gap-1.5 mb-2.5">
        <span className="w-1.5 h-1.5 rounded-full bg-atoms-accent" />
        <span className="font-mono text-[10.5px] uppercase tracking-[0.1em] text-atoms-text-3">
          全栈架构
        </span>
        <ProductTypeTag type={type} />
        <span className="ml-auto text-[10.5px] text-atoms-accent font-medium">连后端数据库都有</span>
      </div>
      <div className="flex items-stretch gap-2">
        {/* 前端 */}
        <div className="flex-1 rounded-lg border border-atoms-accent-line bg-atoms-accent-soft/40 px-2.5 py-2">
          <div className="flex items-center gap-1.5 mb-1">
            <span className="text-[11px]">⚛</span>
            <span className="text-[11px] font-semibold text-atoms-accent">前端</span>
          </div>
          <div className="font-mono text-[10px] text-atoms-text-2 leading-[1.55]">
            React · Vite
            <br />
            Tailwind CSS
          </div>
        </div>
        {/* 连接 */}
        <div className="flex flex-col items-center justify-center px-0.5">
          <span className="font-mono text-[8.5px] text-atoms-text-3">REST</span>
          <span className="text-atoms-text-3 text-[15px] leading-none my-0.5">⇄</span>
          <span className="font-mono text-[8.5px] text-atoms-text-3">JS SDK</span>
        </div>
        {/* 后端 Supabase */}
        <div className="flex-1 rounded-lg border border-atoms-bob/30 bg-atoms-bob/[0.08] px-2.5 py-2">
          <div className="flex items-center gap-1.5 mb-1">
            <span className="w-2 h-2 rounded-full bg-emerald-500" />
            <span className="text-[11px] font-semibold text-atoms-bob">Supabase</span>
          </div>
          <div className="font-mono text-[10px] text-atoms-text-2 leading-[1.55]">
            {hasUserAuth ? "Auth · " : ""}Postgres{hasUserAuth ? " · RLS" : ""}
          </div>
        </div>
      </div>
    </div>
  );
}

/** 单张表的 ER 卡片:表名头 + 字段列(name + 类型徽章 + PK/FK + FK→目标)。 */
function ERTableCard({ table, tableNames }: { table: TableSchema; tableNames: string[] }) {
  const fields = table.fields ?? [];
  return (
    <div className="rounded-xl border border-atoms-border bg-atoms-surface overflow-hidden shadow-sm">
      {/* 表头 */}
      <div className="flex items-center gap-1.5 px-3 py-2 bg-gradient-to-r from-atoms-bob/12 to-transparent border-b border-atoms-border">
        <span className="text-[11.5px]">🗄</span>
        <span className="font-mono text-[12.5px] font-semibold text-atoms-bob truncate">
          {table.name}
        </span>
        <span className="ml-auto font-mono text-[9.5px] text-atoms-text-3 uppercase tracking-wider">
          {fields.length} cols
        </span>
      </div>
      {/* 字段 */}
      <div className="divide-y divide-atoms-border/50">
        {fields.map((f, i) => {
          const fkTargetTable = f.fk ? f.fk.split(".")[0] : null;
          const isBizFk = !!fkTargetTable && tableNames.includes(fkTargetTable);
          return (
            <div
              key={f.name + "-" + i}
              className="flex items-center gap-2 px-3 py-[5px] font-mono text-[11.5px]"
            >
              <span className="w-3.5 text-center flex-shrink-0">
                {f.pk ? (
                  <span className="text-atoms-accent text-[11px]" title="主键">
                    🔑
                  </span>
                ) : f.fk ? (
                  <span className="text-atoms-bob text-[11px]" title="外键">
                    🔗
                  </span>
                ) : null}
              </span>
              <span
                className={`truncate ${f.pk ? "font-semibold text-atoms-text" : "text-atoms-text-2"}`}
              >
                {f.name}
              </span>
              <span className="ml-auto flex items-center gap-1 flex-shrink-0">
                {f.fk && (
                  <span
                    className={`text-[9.5px] ${isBizFk ? "text-atoms-bob" : "text-atoms-text-3"}`}
                  >
                    → {f.fk}
                  </span>
                )}
                <span className={`text-[9.5px] px-1.5 py-px rounded border ${typeStyle(f.type)}`}>
                  {f.type}
                </span>
                {f.pk && (
                  <span className="text-[8.5px] px-1 py-px rounded bg-atoms-accent-soft text-atoms-accent font-semibold">
                    PK
                  </span>
                )}
                {f.fk && (
                  <span className="text-[8.5px] px-1 py-px rounded bg-atoms-bob/10 text-atoms-bob font-semibold">
                    FK
                  </span>
                )}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Postgres 类型 → 徽章配色(uuid 紫 / text 蓝 / 时间 绿 / 布尔 琥珀 / 数值 灰 / json 粉)。 */
function typeStyle(t: string): string {
  const n = (t || "").toLowerCase();
  if (n === "uuid") return "bg-violet-50 text-violet-600 border-violet-200";
  if (["text", "varchar", "char", "bpchar"].includes(n))
    return "bg-sky-50 text-sky-600 border-sky-200";
  if (["date", "timestamptz", "timestamp", "time", "timetz"].includes(n))
    return "bg-emerald-50 text-emerald-600 border-emerald-200";
  if (["boolean", "bool"].includes(n)) return "bg-amber-50 text-amber-600 border-amber-200";
  if (["integer", "int", "int4", "int8", "bigint", "smallint", "int2", "numeric", "decimal", "real", "float8"].includes(n))
    return "bg-slate-100 text-slate-600 border-slate-200";
  if (["jsonb", "json"].includes(n)) return "bg-pink-50 text-pink-600 border-pink-200";
  return "bg-atoms-surface-2 text-atoms-text-3 border-atoms-border";
}

/** product_type 翻译成中文标签(宽松:未知值原样显示)。 */
function ProductTypeTag({ type }: { type: string }) {
  const label =
    type === "web_app"
      ? "Web 应用"
      : type === "landing"
        ? "落地页"
        : type === "tool"
          ? "工具"
          : type || "未分类";
  return (
    <span className="inline-flex items-center gap-1 px-[7px] py-px rounded-full bg-atoms-bob/10 border border-atoms-bob/25 text-atoms-bob text-[10px] font-medium">
      {label}
    </span>
  );
}
