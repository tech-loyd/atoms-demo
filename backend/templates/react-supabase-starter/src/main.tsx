// 模板占位入口。Validator 实际 build 时,state.files(Alex 产的 src/main.tsx)会覆盖本文件。
// 保留它只是为了让"模板单独 build"在预热/自检时也能跑通。
import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
