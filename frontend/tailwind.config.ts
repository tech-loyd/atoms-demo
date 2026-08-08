import type { Config } from "tailwindcss";

// atoms 浅色视觉语言(背景 #f6f6f6 / 强调 #4267ff / IBM Plex Sans)
const config: Config = {
  content: [
    "./src/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // atoms 体系
        atoms: {
          bg: "#f6f6f6",
          surface: "#ffffff",
          "surface-2": "#f1f1f1",
          "surface-3": "#e9e9e9",
          border: "rgba(12, 12, 12, 0.08)",
          "border-strong": "rgba(12, 12, 12, 0.14)",
          text: "#0c0c0c",
          "text-2": "rgba(12, 12, 12, 0.60)",
          "text-3": "rgba(12, 12, 12, 0.38)",
          accent: "#4267ff",
          "accent-2": "#7c3aed",
          "accent-soft": "rgba(66, 103, 255, 0.10)",
          "accent-line": "rgba(66, 103, 255, 0.28)",
          emma: "#4267ff",
          bob: "#7c3aed",
          alex: "#0c0c0c",
        },
      },
      fontFamily: {
        sans: [
          "IBM Plex Sans",
          "-apple-system",
          "PingFang SC",
          "Microsoft YaHei",
          "sans-serif",
        ],
        mono: [
          "JetBrains Mono",
          "ui-monospace",
          "SF Mono",
          "Menlo",
          "monospace",
        ],
      },
      boxShadow: {
        sm: "0 1px 2px rgba(12,12,12,0.04), 0 2px 8px -2px rgba(12,12,12,0.05)",
        md: "0 4px 16px -4px rgba(12,12,12,0.08), 0 1px 2px rgba(12,12,12,0.04)",
        lg: "0 24px 60px -16px rgba(12,12,12,0.16), 0 0 0 1px rgba(12,12,12,0.04)",
      },
      keyframes: {
        fadeUp: {
          from: { opacity: "0", transform: "translateY(14px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        fadeDown: {
          from: { opacity: "0", transform: "translateY(-10px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        pulse: {
          "0%": { boxShadow: "0 0 0 0 rgba(66,103,255,0.5)" },
          "70%": { boxShadow: "0 0 0 7px rgba(66,103,255,0)" },
          "100%": { boxShadow: "0 0 0 0 rgba(66,103,255,0)" },
        },
        spin: { to: { transform: "rotate(360deg)" } },
      },
      animation: {
        fadeUp: "fadeUp 0.5s cubic-bezier(0.2,0.8,0.2,1) both",
        fadeDown: "fadeDown 0.6s cubic-bezier(0.2,0.8,0.2,1) both",
        pulse: "pulse 2s infinite",
        spin: "spin 0.8s linear infinite",
      },
    },
  },
  plugins: [],
};

export default config;
