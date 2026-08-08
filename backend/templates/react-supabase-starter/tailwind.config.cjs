/** @type {import('tailwindcss').Config} */
// atoms starter Tailwind 配置。content 扫描 index.html + src/**,只生成用到的 class。
module.exports = {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: { extend: {} },
  plugins: [],
}
