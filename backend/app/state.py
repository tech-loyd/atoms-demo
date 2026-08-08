"""LangGraph 的 graph state schema。

继承 CopilotKitState(它已含 messages 与 copilotkit 两个槽位),再加各阶段产物字段:
- requirement / prd                          (PM / Emma 产)
- design / files                             (Architect / Engineer 产)
- build_status / build_errors / iter_count   (Validator 产,回喂循环)
- deployment_url / deploy_status             (deploy_app 产,Vercel 真部署)
- preview_url                                (Validator 产,后端 Vite 构建产物静态托管地址,替代 Sandpack CDN)

前端 CopilotKit 通过 useCoAgent 读 agent.state:
- state.prd             → PRDCard(Emma)
- state.design          → DesignCard(Bob)
- state.files           → CodeView(Alex)
- state.build_status    → Validator 结果徽标 / 回喂提示(前端可选用)
- state.preview_url     → 后端 build 产物 iframe 预览(build passed + 未部署时)
- state.deployment_url  → 分享 URL(部署按钮 + 复制链接 / 打开新标签)
- state.deploy_status   → 部署状态:building(loading)/ ready(URL)/ failed(错误 + 重试)
"""

from __future__ import annotations

from typing import List, Optional

from copilotkit import CopilotKitState

from .schema import DesignDict, FileDict, PRDDict


class GraphState(CopilotKitState):
    """atoms graph 的共享状态。

    字段:
        requirement:     用户原始需求(一句话)。由 write_prd 写入。
        prd:             PM(Emma)产出的结构化 PRD。前端渲染 PRDCard。
        design:          Architect(Bob)产出的设计(含 supabase_tables)。前端渲染 DesignCard。
        files:           Engineer(Alex)产出的文件列表。前端渲染 CodeView。
        active_file:     当前 agent 正在写的文件路径(预留,Follow 演进用)。
        build_status:    Validator 产出:"passed" / "failed" / None(还没跑过)。
        build_errors:    Validator 失败时记录的构建日志(vite stderr);passed/未跑时为 None。
        iter_count:      Validator 已尝试的构建次数;到 MAX_BUILD_ITERS(3)就不再回喂。
        deployment_url:  deploy_app 产出:真 vercel.app URL(https://xxx.vercel.app)。未部署时 None。
        deploy_status:   deploy_app 产出:"building" / "ready" / "failed" / None(还没部署)。
        preview_url:     Validator 产出:后端 Vite 构建产物(dist/)的静态托管 URL,
                         形如 http://localhost:8000/preview/{session_id}/dist/index.html。
                         build 通过 + 未部署时,前端 Canvas 用它 iframe 预览(不依赖 CodeSandbox CDN)。
                         build 未跑/失败/已部署时为 None(已部署优先用 deployment_url)。
    """

    requirement: str
    prd: PRDDict
    # Architect(Bob)产出;PM 未产前默认 None
    design: Optional[DesignDict] = None
    # Engineer(Alex)写入;前端 CodeView 读
    files: Optional[List[FileDict]] = None
    active_file: Optional[str] = None
    # Validator 真 vite build 的结果
    build_status: Optional[str] = None
    build_errors: Optional[str] = None
    iter_count: int = 0
    # Vercel 真部署的结果
    deployment_url: Optional[str] = None
    deploy_status: Optional[str] = None
    # 后端 Vite 构建产物静态托管 URL(替代 Sandpack CDN,见 validator.py / main.py)
    preview_url: Optional[str] = None
