// PRD schema(前后端共用)
export interface PRD {
  title: string;
  summary: string;
  features: string[];
  acceptanceChecks: string[];
}

// —— Design schema ——
// 后端 Architect(Bob)节点写 state.design;前端 DesignCard 订阅渲染。
// 字段与后端 DesignSchema(BaseModel)一一对应:
//   FieldSchema    : { name, type, pk?, fk? }
//   TableSchema    : { name, fields[] }
//   DesignSchema   : { product_type, supabase_tables[], pages[] }
export type FieldType =
  | "uuid"
  | "text"
  | "date"
  | "timestamptz"
  | "integer"
  | "boolean"
  | "jsonb"
  | "numeric"
  | "varchar"
  | string; // 宽松:后端可能返回其它 Postgres 类型,不硬阻断渲染

export interface FieldSchema {
  name: string;
  type: FieldType;
  pk?: boolean;
  fk?: string | null; // 形如 "users.id",为 null/undefined 则非外键
}

export interface TableSchema {
  name: string;
  fields: FieldSchema[];
}

export interface Design {
  product_type: string; // web_app / landing / tool(宽松 string,不强校验)
  supabase_tables: TableSchema[];
  pages?: string[]; // 后端可省略,默认空
}

// 代码视图:项目文件(文件树 + 代码区)
// Alex 的 write_file 工具写 state.files;为空时 CodeView 显示等待态(不回退 mock)。
export type FileStatus = "done" | "active" | "queued";

/**
 * 文件语言(代码高亮 + 文件图标用)。
 * 后端 `Engineer.write_file` 经 markdown 围栏解析产出,实际值见 backend/app/schema.py
 * 与 backend/app/tools.py:tsx / ts / jsx / js(=javascript)/ css / json / markdown / text,
 * LLM 也可能返回 html / typescript 等同义写法。这里列前端已知值,并 `string` 兜底
 * (prism-react-renderer 的 `Language` 本就是 string,未知值降级为纯文本,不阻断渲染)。
 */
export type FileLanguage =
  | "tsx"
  | "ts"
  | "jsx"
  | "js"
  | "javascript"
  | "typescript"
  | "css"
  | "json"
  | "markdown"
  | "html"
  | "text"
  | string;

export interface ProjectFile {
  path: string; // "src/components/HabitCard.tsx"
  content: string;
  language: FileLanguage;
  status?: FileStatus; // active 文件高亮
}

// 后端 LangGraph graph state 的前端镜像。
// 后端 PM 节点写 prd;Architect 写 design;Alex 的 write_file 写 files。
// 这里只声明前端消费的字段。
export interface AgentState {
  requirement?: string;
  prd?: PRD | null;
  design?: Design | null; // Architect(Bob)产;为空 → DesignCard 不渲染
  // 代码视图:为空 → CodeView 显示等待态(不回退 mock)
  files?: ProjectFile[];
  active_file?: string; // agent 正在写的文件(对齐后端 state.py)
  // —— Validator 节点 ——
  // 后端 `write_code` 之后跑 `vite build`;成功 "passed" / 失败 "failed" / 未跑 null。
  // 前端只读消费:在 Sandpack 预览地址栏右侧显示 build 徽标 + 失败日志(回喂可视化)。
  build_status?: "passed" | "failed" | null;
  build_errors?: string | null; // build 失败时的 stderr/日志摘要
  // —— deploy_app tool ——
  // 后端 deploy_app(Vercel API inlined files 部署)写回;前端只读消费。
  // building=Vercel 构建中 / ready=部署完成,deployment_url 可用 / failed=部署失败 / null=未部署。
  deployment_url?: string | null; // "https://xxx.vercel.app"
  deploy_status?: "building" | "ready" | "failed" | null;
  // 后端 Vite 构建产物的静态托管 URL(替代 Sandpack CDN,不依赖 CodeSandbox)
  preview_url?: string | null;
  messages?: unknown[];
}

// 派生:当前工作区所处阶段(用于 Canvas 分流 + 进度可视化)。
// 流程顺序:prd → design → files;后续产出不清空前置。
export type Stage = "empty" | "prd" | "design" | "files";

// 据 AgentState 推导当前阶段(最靠后的已产出物)。
export function deriveStage(s: AgentState | null | undefined): Stage {
  if (!s) return "empty";
  if (Array.isArray(s.files) && s.files.length > 0) return "files";
  if (s.design) return "design";
  if (s.prd) return "prd";
  return "empty";
}
