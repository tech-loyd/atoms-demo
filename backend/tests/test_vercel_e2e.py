"""端到端实测:真调 Vercel API 部署一次,拿到 vercel.app URL。

⚠️ 默认 **skip**(每次跑都会真部署,占用 Vercel Hobby 100/day 配额)。
   显式设置环境变量 ATOMS_RUN_VERCEL_E2E=1 才跑。

用法:
    cd backend && source .venv/bin/activate
    env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy -u ALL_PROXY -u all_proxy \\
        ATOMS_RUN_VERCEL_E2E=1 python tests/test_vercel_e2e.py

成功输出:
    - 真部署的 vercel.app URL(可在浏览器打开)
    - deploy_status: ready / building / failed

实测要点:
    - inlined files 模式 POST /v13/deployments 免 git
    - 轮询 GET /v13/deployments/{id} 到 READY
    - Supabase 配置注入(src/lib/supabase.ts 含真实 SUPABASE_URL + anon key)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import deploy as deploy_mod  # noqa: E402
from app.config import settings  # noqa: E402

TEMPLATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "templates", "react-supabase-starter",
)


def _tpl(name: str) -> str:
    with open(os.path.join(TEMPLATE_DIR, name), encoding="utf-8") as f:
        return f.read()


def main() -> None:
    if os.getenv("ATOMS_RUN_VERCEL_E2E") != "1":
        print("⏭  跳过(默认 skip)。设 ATOMS_RUN_VERCEL_E2E=1 启用真 Vercel 部署。")
        return

    if not settings.vercel_token:
        print("❌ backend/.env 未配 VERCEL_TOKEN,无法实测。")
        sys.exit(1)
    print(f"SUPABASE_URL = {settings.supabase_url}")
    print(f"VERCEL_TOKEN = {'<已配置,' + str(len(settings.vercel_token)) + ' 字符>'}")

    # 模拟 Alex 产的 files(模板占位 + supabase.ts 注入)
    files = [
        {"path": "src/main.tsx", "content": _tpl("src/main.tsx"), "language": "tsx"},
        {"path": "src/App.tsx", "content": _tpl("src/App.tsx"), "language": "tsx"},
    ]
    files = deploy_mod.inject_supabase_config(
        files, settings.supabase_url, settings.supabase_anon_key
    )

    print("\n[1/2] POST /v13/deployments(inlined files)…")
    try:
        resp = deploy_mod.create_deployment(files, settings.vercel_token)
    except deploy_mod.VercelAPIError as e:
        print(f"❌ 创建部署失败:{e}")
        sys.exit(2)

    dep_id = resp.get("id")
    url = deploy_mod._normalize_url(resp.get("url"))
    init_state = resp.get("readyState")
    print(f"   deployment id: {dep_id}")
    print(f"   url: {url}")
    print(f"   readyState(初始): {init_state}")
    if not dep_id or not url:
        print(f"❌ 响应缺 id/url。完整响应(去敏):{ {k:v for k,v in resp.items() if k in ('id','url','readyState','status','error')} }")
        sys.exit(3)

    print(f"\n[2/2] 轮询 GET /v13/deployments/{{id}}(最长 {int(deploy_mod._POLL_TIMEOUT)}s)…")
    status, final_url = deploy_mod.poll_deployment(dep_id, settings.vercel_token)
    print(f"   最终 status: {status}")
    print(f"   最终 url: {final_url or url}")

    if status == "ready":
        print(f"\n=== ✅ 部署成功,真站点 URL(浏览器打开即可):===")
        print(f"    {final_url or url}")
        # 验证部署的应用确实有 supabase.ts(通过看 build_vercel_files 输出)
        vf = deploy_mod.build_vercel_files(files)
        sb = next((f for f in vf if f["file"] == "src/lib/supabase.ts"), None)
        assert sb and settings.supabase_url in sb["data"], "inlined supabase.ts 应含真实 URL"
        print(f"    Supabase 注入自检:✅(src/lib/supabase.ts 含真实 {settings.supabase_url})")
    elif status == "building":
        print(f"\n⏳ 仍在构建中,1-2 分钟后访问:{final_url or url}")
    else:
        print(f"\n❌ 部署失败。临时 URL:{final_url or url}(到 Vercel 控制台看 Build Logs)")


if __name__ == "__main__":
    main()
