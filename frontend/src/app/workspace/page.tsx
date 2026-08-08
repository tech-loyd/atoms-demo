import { Workspace } from "@/components/Workspace";

/**
 * 工作台路由(/workspace)—— 欢迎页 CTA / composer / hint 点击跳转到此。
 * 根路径 `/` 是欢迎页(landing);工作台主界面渲染于此(Workspace 为 client component)。
 */
export default function WorkspacePage() {
  return <Workspace />;
}
