// 接口契约(前后端共用)
//
// AG-UI 端点:http://localhost:8000/api/copilotkit
// 前端开发地址:http://localhost:3000(CORS 由后端放行)
//
// 如需指向其他后端地址(例如远程调试),在 frontend/.env.local 设置:
//   NEXT_PUBLIC_AGENT_URL=https://your-backend/api/copilotkit
export const RUNTIME_URL =
  process.env.NEXT_PUBLIC_AGENT_URL || "http://localhost:8000/api/copilotkit";

// 后端 origin(从 RUNTIME_URL 推,去 /api/copilotkit 后缀)。给非 AG-UI 的 HTTP 端点用(如 GET /api/threads)。
export const BACKEND_ORIGIN = RUNTIME_URL.replace(/\/api\/copilotkit\/?$/, "");

// agent 名:对齐 CopilotKit 默认 agentId "default"(CopilotChat 自动找 default;后端 config.py 同)。
// Direct Connection 模式下,useCoAgent({name}) 据此匹配 agents__unsafe_dev_only 的 key。
export const AGENT_NAME = "default";
