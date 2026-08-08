import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

// atoms 后端 Validator 的 vite 配置(固定,与前端 Sandpack starter / PROJECT_TEMPLATE_FILES 一致)。
// Validator 写临时 build 目录时把这份文件连同 package.json 一起落盘,vite build 用它。
//
// CR 🟡#2:@ alias → ./src,与前端 starterTemplate.ts 的 PROJECT_TEMPLATE_FILES 对齐。
// Alex 产代码常写 `@/lib/supabase`、`@/components/...` 别名导入(前端 tsconfig 同样配了
// `@/* → ./src/*`)。若后端模板这里不配 alias,Alex 用 @/ 导入时后端 vite build 会报
// "Could resolve @/..."假失败,白白消耗回喂 iter 配额(代码本身没错,前端也能跑)。
export default defineConfig({
  // base: './' 让 Vite 输出**相对路径**(`src="./assets/..."` 而非 `src="/assets/..."`),
  // 这样后端 StaticFiles serve 到 /preview/{id}/dist/index.html 时,iframe 能正确加载 assets。
  // 不加 base → index.html 用绝对路径 /assets/...,从子路径访问时 404。
  base: './',
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: { sourcemap: false },
})
