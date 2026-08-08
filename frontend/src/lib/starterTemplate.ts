/**
 * Sandpack 启动模板 + 文件拼装。
 *
 * 职责:
 *  1) `STARTER_TEMPLATE`:Sandpack 运行时的"入口壳"——
 *     `/index.tsx`(挂载 `/src/App`)+ `/src/styles.css`(全局样式兜底)。
 *     用 `template="react-ts"`(CRA-TS 环境,Babel bundler)——比 `vite-react-ts` 稳:
 *     后者依赖 nodebox 里的 vite,常因 `esbuild-wasm` 解析失败而崩(Sandpack 已知问题)。
 *  2) `PROJECT_TEMPLATE_FILES`:生成项目的"完整模板"(package.json/vite.config/index.html/tsconfig),
 *     与后端 `backend/templates/react-supabase-starter/` **内容一致**。
 *     仅作"模板源真相"导出(供后端对齐/文档/未来 export zip 用),**不**注入 Sandpack——
 *     CRA 环境自带 react-scripts 等运行依赖,注入外部 package.json 反而会破坏其 bundler。
 *  3) `SANDPACK_OVERRIDES`:Supabase client **内存存储兜底**——
 *     绕过 Sandpack iframe 的 localStorage 限制、且无真实后端时让生成的应用仍可交互。
 *  4) `buildSandpackFiles(stateFiles)`:把 Alex 产的 `state.files`(路径形如 `src/App.tsx`)
 *     归一化为 Sandpack 约定(键以 `/` 开头),并把 `@/...` 别名导入重写成相对路径
 *     (CRA 环境不解析 vite alias,运行时直接相对导入最稳),最后合并
 *     `{...STARTER_TEMPLATE, ...mappedStateFiles, ...SANDPACK_OVERRIDES}`。
 *
 * 为保证 Supabase 内存兜底始终生效,`SANDPACK_OVERRIDES` 最后合并以覆盖 Alex 的
 * `src/lib/supabase.ts`,保证预览始终可交互。Code 视图仍展示 Alex 的真实产出(不被覆盖)。
 */
import type { ProjectFile } from "./types";
import type { SandpackFiles } from "@codesandbox/sandpack-react";

// ────────────────────────────────────────────────────────────────
// Sandpack 运行时依赖(react-ts 模板自带,customSetup 再强调一次)。
// 不列 @supabase/supabase-js:OVERRIDES 的内存 stub 已替换掉 Alex 的 supabase.ts,
// 不再 import 真包。若 Alex 在 component 里直接值导入 supabase-js(罕见,约定都走
// `@/lib/supabase` 单例),会在预览里报编译错误——属可回喂修复的常态。
// ────────────────────────────────────────────────────────────────
export const SANDBOX_DEPENDENCIES: Record<string, string> = {
  react: "^18.3.1",
  "react-dom": "^18.3.1",
};

/**
 * Sandpack 运行时入口壳(注入 Sandpack 的那部分模板)。
 * 用 `/index.tsx` 覆盖 react-ts 模板默认入口,使其挂载 Alex 的 `/src/App.tsx`。
 */
export const STARTER_TEMPLATE: SandpackFiles = {
  "/index.tsx": {
    code: `import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// 挂载点指向 Alex 产出的 App(路径约定:src/App.tsx 默认导出)。
import App from "./src/App";
import "./src/styles.css";

const rootEl = document.getElementById("root");
if (rootEl) {
  createRoot(rootEl).render(
    <StrictMode>
      <App />
    </StrictMode>
  );
}
`,
    hidden: true,
  },
  // 最小全局样式;Alex 若产 src/styles.css 会覆盖此文件。
  "/src/styles.css": {
    code: `:root {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
    "Microsoft YaHei", sans-serif;
  color-scheme: light;
}
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; }
button { font: inherit; cursor: pointer; }
input { font: inherit; }
`,
    hidden: true,
  },
};

// ────────────────────────────────────────────────────────────────
// Supabase client 内存存储 stub
// ────────────────────────────────────────────────────────────────
// 仅给 Sandpack 预览用:绕 iframe localStorage 限制 + 无真实后端时让应用可交互。
// 实现:`auth` 自动登录一个 demo 用户(让受登录保护的应用直接进主界面);
//       `from(table)` 链式 query,内存表支持 select/insert/update/delete + eq/neq 过滤,
//       写操作即时落内存、读操作返回过滤后的行——打卡 toggle 之类交互真实可感。
//
// 实现范围(诚实清单):
//  ✅ 已实现(demo 路径子集):from/select/insert/update/delete、eq/neq、maybeSingle/single、then(await)。
//  🟡 链式 no-op(仅 return this,保证常见链不报 TypeError,但**不真实过滤/排序/分页**):
//     order/limit/range/in/gt/lt/gte/lte/like/ilike/is/not/or/count。
//  ❌ 不模拟:RLS、storage 真上传、realtime 真订阅、RPC、schema 校验、错误路径、count 真实计数。
// 生成应用用到 no-op 链时不崩,数据按内存全量返回(顺序/数量可能与真实后端不一致,可接受)。
// 注意:Code 视图仍展示 Alex 的真实 src/lib/supabase.ts;此 stub 只活在预览 iframe 里。
const SUPABASE_MEMORY_STUB = `// atoms Sandpack 预览专用 · 内存版 Supabase client(自动生成,非 Alex 产出)。
// 绕过 iframe localStorage 限制、无真实后端时兜底,让生成的应用可点可交互。
type Row = Record<string, any>;
const DB: Record<string, Row[]> = {};

function rowsOf(table: string): Row[] {
  if (!DB[table]) DB[table] = [];
  return DB[table];
}

class Query {
  private table: string;
  private filters: Array<[string, any]> = [];
  private payload: Row | Row[] | null = null;
  private mode: "select" | "insert" | "update" | "delete" = "select";

  constructor(table: string) {
    this.table = table;
  }

  eq(col: string, val: any) {
    this.filters.push([col, val]);
    return this;
  }
  neq(col: string, val: any) {
    this.filters.push([col, { $ne: val }]);
    return this;
  }

  // —— 宽容 no-op 链(等价 Supabase 同名方法,但仅保证不报 TypeError;不真实过滤/排序/分页)。
  //    生成的应用里 .order(...)/.limit(...)/.in(...) 等常见链不崩,demo 数据按内存全量返回。
  order(_column?: string, _opts?: any): this { return this; }
  limit(_count?: number, _opts?: any): this { return this; }
  range(_from?: number, _to?: number, _opts?: any): this { return this; }
  in(_column?: string, _values?: any[]): this { return this; }
  gt(_column?: string, _val?: any): this { return this; }
  lt(_column?: string, _val?: any): this { return this; }
  gte(_column?: string, _val?: any): this { return this; }
  lte(_column?: string, _val?: any): this { return this; }
  like(_column?: string, _pattern?: string): this { return this; }
  ilike(_column?: string, _pattern?: string): this { return this; }
  is(_column?: string, _val?: any): this { return this; }
  not(_column?: string, _operator?: string, _val?: any): this { return this; }
  or(_filters?: string, _opts?: any): this { return this; }
  count(_opts?: any): this { return this; }

  select(_columns?: string) {
    // 不重置 mode:.insert(row).select() / .update(row).select() / .delete().select()
    // 是"写并返回"链(Supabase 真实语义里 select 在写操作后是"返回修饰符",不是切回读模式);
    // 之前无脑 mode="select" 会丢 payload,导致 .insert(row).select() 不落库。
    // 构造时 mode 已默认 "select",这里无需赋值。
    return this;
  }
  insert(row: Row | Row[]) {
    this.mode = "insert";
    this.payload = row;
    return this;
  }
  update(row: Row) {
    this.mode = "update";
    this.payload = row;
    return this;
  }
  delete() {
    this.mode = "delete";
    return this;
  }

  private match(r: Row): boolean {
    return this.filters.every(([k, v]) =>
      v && typeof v === "object" && "$ne" in v ? r[k] !== v.$ne : r[k] === v,
    );
  }

  private resolve(): Promise<{ data: any; error: null }> {
    const all = rowsOf(this.table);
    if (this.mode === "select") {
      return Promise.resolve({ data: all.filter((r) => this.match(r)), error: null });
    }
    if (this.mode === "insert") {
      const rows = Array.isArray(this.payload) ? this.payload : [this.payload as Row];
      rows.forEach((r) => all.push({ ...r }));
      return Promise.resolve({ data: rows, error: null });
    }
    if (this.mode === "update") {
      const patch = this.payload as Row;
      all.forEach((r) => {
        if (this.match(r)) Object.assign(r, patch);
      });
      return Promise.resolve({ data: all.filter((r) => this.match(r)), error: null });
    }
    // delete
    for (let i = all.length - 1; i >= 0; i--) {
      if (this.match(all[i])) all.splice(i, 1);
    }
    return Promise.resolve({ data: null, error: null });
  }

  // 让 builder 可 await(等价于 select 后取多行)。
  then(onFulfilled: any, onRejected?: any) {
    return this.resolve().then(onFulfilled, onRejected);
  }
  maybeSingle() {
    return this.resolve().then((r) => ({
      data: Array.isArray(r.data) ? (r.data[0] ?? null) : r.data,
      error: r.error,
    }));
  }
  single() {
    return this.maybeSingle();
  }
}

// 内存 auth:预置一个 demo 登录态,让受登录保护的应用直接进主界面。
const DEMO_USER = { id: "demo-user", email: "demo@atoms.dev" };
const DEMO_SESSION = {
  access_token: "demo-token",
  refresh_token: "demo-refresh",
  user: DEMO_USER,
  // 未来 1h:某些生成的应用会判断 expires_at <= now 显示"登录过期"强制登出,0 会被当过期。
  expires_at: Math.floor(Date.now() / 1000) + 3600,
};

export const supabase = {
  auth: {
    getUser: () => Promise.resolve({ data: { user: DEMO_USER }, error: null }),
    getSession: () => Promise.resolve({ data: { session: DEMO_SESSION }, error: null }),
    signInWithPassword: () =>
      Promise.resolve({ data: { user: DEMO_USER, session: DEMO_SESSION }, error: null }),
    signInWithOtp: () => Promise.resolve({ data: {}, error: null }),
    signUp: () =>
      Promise.resolve({ data: { user: DEMO_USER, session: DEMO_SESSION }, error: null }),
    signOut: () => Promise.resolve({ error: null }),
    onAuthStateChange: (cb: (event: string, session: any) => void) => {
      // 预览启动即派发一次 SIGNED_IN,让 UI 拿到登录态。
      try {
        cb("SIGNED_IN", DEMO_SESSION);
      } catch {}
      return { data: { subscription: { unsubscribe: () => {} } } };
    },
  },
  from: (table: string) => new Query(table),
  channel: () => ({
    on: () => ({ subscribe: () => {} }),
    unsubscribe: () => {},
  }),
  storage: {
    list: () => Promise.resolve({ data: [], error: null }),
    upload: () => Promise.resolve({ data: { path: "" }, error: null }),
  },
};
`;

export const SANDPACK_OVERRIDES: SandpackFiles = {
  "/src/lib/supabase.ts": { code: SUPABASE_MEMORY_STUB, hidden: true },
};

// ────────────────────────────────────────────────────────────────
// PROJECT_TEMPLATE_FILES:生成项目的完整模板(与后端 templates/ 内容一致)。
// 不注入 Sandpack(CRA 环境自带运行依赖);仅作模板源真相,供后端对齐 / 文档 / 后续 export zip。
// ────────────────────────────────────────────────────────────────
export const PROJECT_TEMPLATE_FILES = {
  "package.json": JSON.stringify(
    {
      name: "atoms-generated-app",
      private: true,
      version: "0.0.0",
      type: "module",
      scripts: {
        dev: "vite",
        build: "tsc -b && vite build",
        preview: "vite preview",
      },
      dependencies: {
        react: "^18.3.1",
        "react-dom": "^18.3.1",
        "@supabase/supabase-js": "^2.45.0",
      },
      devDependencies: {
        "@types/react": "^18.3.0",
        "@types/react-dom": "^18.3.0",
        "@vitejs/plugin-react": "^4.3.0",
        tailwindcss: "^3.4.0",
        autoprefixer: "^10.4.0",
        postcss: "^8.4.0",
        typescript: "^5.6.0",
        vite: "^5.4.0",
      },
    },
    null,
    2,
  ),
  "vite.config.ts": `import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// atoms 生成项目 vite 配置(@ alias → ./src)。
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
`,
  "tsconfig.json": JSON.stringify(
    {
      compilerOptions: {
        target: "ES2020",
        useDefineForClassFields: true,
        lib: ["ES2020", "DOM", "DOM.Iterable"],
        module: "ESNext",
        skipLibCheck: true,
        moduleResolution: "bundler",
        allowImportingTsExtensions: true,
        resolveJsonModule: true,
        isolatedModules: true,
        noEmit: true,
        jsx: "react-jsx",
        strict: true,
        baseUrl: ".",
        paths: { "@/*": ["./src/*"] },
      },
      include: ["src", "index.tsx"],
    },
    null,
    2,
  ),
  "index.html": `<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>atoms · 生成应用</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/index.tsx"></script>
  </body>
</html>
`,
} as const;

// ────────────────────────────────────────────────────────────────
// buildSandpackFiles:state.files → Sandpack files
// ────────────────────────────────────────────────────────────────

/** 把 `src/App.tsx` 归一化为 Sandpack 键 `/src/App.tsx`(保证以 `/` 开头)。 */
function toSandpackPath(p: string): string {
  const trimmed = p.replace(/^\.?\/+/, "");
  return "/" + trimmed;
}

/**
 * `@/foo/bar` → 相对路径重写(CRA bundler 不解析 vite alias,运行时直接相对导入)。
 * 仅替换静态 import/export 与动态 import 里的 `@/` spec,不动其它字符。
 */
function rewriteAliasImports(content: string, filePath: string): string {
  const fileDir = filePath.slice(0, filePath.lastIndexOf("/")); // 如 "/src/components"
  const fromSegs = fileDir.split("/").filter(Boolean);

  const toRelative = (atImport: string): string => {
    // atImport: "foo/bar"(已去 `@/`)
    const target = "/src/" + atImport.replace(/^\/+/, "");
    const tgtSegs = target.split("/").filter(Boolean); // ["src","foo","bar"]
    const tgtDir = tgtSegs.slice(0, -1);
    const fname = tgtSegs[tgtSegs.length - 1];
    let k = 0;
    while (k < fromSegs.length && k < tgtDir.length && fromSegs[k] === tgtDir[k]) k++;
    const ups = fromSegs.length - k;
    const downs = tgtDir.slice(k);
    const rel = "../".repeat(ups) + [...downs, fname].join("/");
    return rel.startsWith(".") ? rel : "./" + rel;
  };

  // 静态 import/export ... from "@/..."
  let out = content.replace(
    /\bfrom\s+["'](@\/[^"']+)["']/g,
    (m, spec: string) => m.replace(spec, toRelative(spec.slice(2))),
  );
  // 动态 import("@/...")
  out = out.replace(
    /\bimport\s*\(\s*["'](@\/[^"']+)["']\s*\)/g,
    (m, spec: string) => m.replace(spec, toRelative(spec.slice(2))),
  );
  return out;
}

/**
 * 拼装最终 Sandpack files:`{...STARTER_TEMPLATE, ...mappedStateFiles, ...SANDPACK_OVERRIDES}`。
 *
 * @param stateFiles Alex 产的 src/*(可能为空 → 仅返回 STARTER_TEMPLATE,Sandpack 会因找不到 /src/App 报错,正常)
 * @param activePath 可选,标记某个文件 active(目前不展示编辑器,仅元数据)
 */
export function buildSandpackFiles(
  stateFiles: ProjectFile[] | null | undefined,
  activePath?: string,
): SandpackFiles {
  const mapped: SandpackFiles = {};
  if (stateFiles && stateFiles.length > 0) {
    for (const f of stateFiles) {
      const spPath = toSandpackPath(f.path);
      const code = rewriteAliasImports(f.content ?? "", spPath);
      mapped[spPath] = {
        code,
        hidden: true,
        active: activePath ? toSandpackPath(activePath) === spPath : undefined,
      };
    }
  }

  // OVERRIDES 最后合并 → Supabase 内存 stub 始终覆盖 Alex 的 src/lib/supabase.ts。
  return {
    ...STARTER_TEMPLATE,
    ...mapped,
    ...SANDPACK_OVERRIDES,
  };
}
