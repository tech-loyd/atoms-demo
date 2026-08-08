/** @type {import('tailwindcss').Config} */
// atoms starter Tailwind 配置 + DaisyUI 设计基线(Apple 风自定义主题)。
// - DaisyUI v4(对应 Tailwind 3.x):提供 navbar / stats / card / btn / progress / badge /
//   form-control 等成品组件类,LLM 直接用即可拿到统一设计基线。
// - 主题 apple:自定义,Apple 产品风 —— 系统蓝 primary(#0071e3)、浅灰背景 base-200
//   (#f5f5f7,苹果官网色)、深灰文字 base-content(#1d1d1f)、**大圆角**(--rounded-box
//   1.25rem ≈ 20px,解决"卡片直角"显丑)。应用通过 <html data-theme="apple"> 启用。
// - 字体走系统栈(-apple-system 优先),Mac/iOS 原生 SF Pro,零外部字体依赖。
module.exports = {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', '"SF Pro Display"', '"Helvetica Neue"', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [require('daisyui')],
  daisyui: {
    themes: [
      {
        apple: {
          "primary": "#0071e3",
          "primary-content": "#ffffff",
          "secondary": "#06afe4",
          "secondary-content": "#ffffff",
          "accent": "#34c759",
          "accent-content": "#ffffff",
          "neutral": "#1d1d1f",
          "neutral-content": "#ffffff",
          "base-100": "#ffffff",
          "base-200": "#f5f5f7",
          "base-300": "#e3e3e8",
          "base-content": "#1d1d1f",
          "info": "#0071e3",
          "info-content": "#ffffff",
          "success": "#34c759",
          "success-content": "#ffffff",
          "warning": "#ff9f0a",
          "warning-content": "#ffffff",
          "error": "#ff3b30",
          "error-content": "#ffffff",
          "--rounded-box": "1.25rem",
          "--rounded-btn": "1rem",
          "--rounded-badge": "0.75rem",
          "--rounded-tabs": "0.75rem",
        },
      },
      "corporate",
    ],
    logs: false,
  },
}
