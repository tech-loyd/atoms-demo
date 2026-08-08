import type { Metadata } from "next";
import { IBM_Plex_Sans, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { CopilotProvider } from "@/components/CopilotProvider";

const ibmPlexSans = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-ibm-plex-sans",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-jetbrains-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "atoms — Agent Studio",
  description:
    "用自然语言生成全栈应用的 agent 平台:Emma(PM)产 PRD → 用户批准 → Bob(Architect)产数据模型 → Alex(Engineer)产代码,三角色 SOP 端到端可视、HITL 批准把控节点。",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN" className={`${ibmPlexSans.variable} ${jetbrainsMono.variable}`}>
      <body className="font-sans">
        <CopilotProvider>{children}</CopilotProvider>
      </body>
    </html>
  );
}
