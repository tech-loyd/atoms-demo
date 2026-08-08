import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // monorepo:把文件追踪根指向仓库根,避免 Next.js 误选上层目录的 lockfile
  outputFileTracingRoot: path.resolve(__dirname, ".."),
  // CopilotKit 的包已经发布了正确的 ESM/CJS 产物，一般无需 transpile；
  // 若后续升级遇到 ESM 解析问题再放开。
  // transpilePackages: ["@copilotkit/react-core", "@copilotkit/react-ui"],
};

export default nextConfig;
