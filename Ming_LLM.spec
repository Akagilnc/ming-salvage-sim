# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Ming Salvage Sim 桌面包。

打 onedir（首选）：
    pyinstaller Ming_LLM.spec

打 onefile（单文件，启动慢）：
    pyinstaller --onefile Ming_LLM.spec
    （或改下方 EXE/COLLECT 段；spec 默认走 onedir）

产物：dist/Ming_LLM/
- macOS：.app bundle 由 BUNDLE 段生成（dist/Ming_LLM.app）。
- Windows/Linux：dist/Ming_LLM/ 整目录可分发。
"""

from PyInstaller.utils.hooks import collect_all, collect_submodules
from pathlib import Path

# agno / openai / agno-sqlite 大量动态导入，全收集。
_agno_data, _agno_bin, _agno_hidden = collect_all("agno")
_openai_data, _openai_bin, _openai_hidden = collect_all("openai")
_tiktoken_data, _tiktoken_bin, _tiktoken_hidden = collect_all("tiktoken")
# pywebview + Mac WKWebView (pyobjc)
_webview_data, _webview_bin, _webview_hidden = collect_all("webview")
# #544 in-process consumer of the organic-markdown authority product
_quickjs_data, _quickjs_bin, _quickjs_hidden = collect_all("quickjs")


def tree_datas(root: str, dest: str, exclude_parts=()):
    """Collect files under root while excluding dev-only backup/cache folders."""
    root_path = Path(root)
    rows = []
    for path in root_path.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root_path)
        parts = set(rel.parts)
        if path.name == ".DS_Store" or any(part in parts for part in exclude_parts):
            continue
        rows.append((str(path), str(Path(dest) / rel.parent)))
    return rows


# ── 发行包 build-time fail-loud 守门（#96 release）──────────────────────────────
# spec 从工作区文件系统直接打 content/ 与 web/dist；二者各有静默坏包风险，构建前响亮拦：
#   1) 金手指：content/buildings.json 三建筑是开发工作区「常驻例外」未提交改动；脏树直接
#      打包会把作弊建筑带进发行包（违「金手指不带」）。
#   2) 前端：web/dist 被 .gitignore 排除；从干净 clone 跳过 `npm run build` 直接打包，
#      tree_datas 对缺失目录静默返 0 行 → 得到 import 全成功、运行期前端缺失的「假成功」坏包。
def _release_guard():
    import subprocess

    # 1) 前端构建产物必须在且非空（否则运行期 StaticFiles 指向空目录）
    if not Path("web/dist/index.html").is_file():
        raise SystemExit(
            "[release-guard] web/dist/index.html 缺失——发行包前端未构建。\n"
            "  先： cd web && npm install && npm run build && cd .."
        )
    assets_dir = Path("web/dist/assets")
    if not assets_dir.is_dir() or not any(assets_dir.glob("*.js")):
        raise SystemExit(
            "[release-guard] web/dist/assets 无 JS 产物——前端构建不完整。先： cd web && npm run build"
        )
    # #544：写入缝与发行包共用 web/dist/organicMarkdown.js 权威产物（非 web/src + 外部 Node）
    if not Path("web/dist/organicMarkdown.js").is_file():
        raise SystemExit(
            "[release-guard] web/dist/organicMarkdown.js 缺失——organic 权威产物未构建。\n"
            "  先： cd web && npm run build"
        )

    # 2) 金手指建筑不得进包（无 git 依赖的硬底线：直接扫已知作弊建筑 id）
    KNOWN_CHEAT_IDS = ("royal_gold_mine", "royal_inner_bank", "imperial_aviation")
    try:
        bj_text = Path("content/buildings.json").read_text(encoding="utf-8")
    except OSError as exc:  # 核心内容文件缺失/不可读 → 清晰中止，不抛 raw traceback（cmr 线上 sourcery）
        raise SystemExit(f"[release-guard] 读 content/buildings.json 失败（核心内容缺失？）：{exc}")
    hits = [cid for cid in KNOWN_CHEAT_IDS if cid in bj_text]
    if hits:
        raise SystemExit(
            f"[release-guard] content/buildings.json 含金手指建筑 {hits}——发行包不可含。\n"
            "  金手指=常驻例外，打包前还原： git stash push content/buildings.json （打完 git stash pop）"
        )

    # 3) 真 git 仓库时：content/buildings.json 不得有任何未提交改动（更一般，兜未来新增作弊）。
    #    仅在 .git 存在（真 working tree）才查——纯 export 包（无 .git，即便装了 git）跳过，
    #    否则 `git diff HEAD` 因 HEAD 不可达返 rc=1 会误报「有未提交改动」（cmr r1 claude）；
    #    export 包的金手指由上面 ② 已知 id 扫描兜底。
    if Path(".git").exists():
        try:
            rc = subprocess.run(
                ["git", "diff", "--quiet", "HEAD", "--", "content/buildings.json"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,  # 保持 build 控制台干净（cmr 线上 gemini）
            ).returncode
        except (FileNotFoundError, OSError):
            rc = 0  # 无 git 二进制 → 跳过；②已知 cheat id 扫描兜底
        if rc == 1:
            raise SystemExit(
                "[release-guard] content/buildings.json 有未提交改动——发行包须从干净 content 打。\n"
                "  先： git stash push content/buildings.json （打完 git stash pop）"
            )


_release_guard()


# FastAPI/uvicorn 系列
hiddenimports = (
    _agno_hidden
    + _openai_hidden
    + _tiktoken_hidden
    + _webview_hidden
    + _quickjs_hidden
    + collect_submodules("uvicorn")
    + collect_submodules("fastapi")
    + collect_submodules("anyio")
    + collect_submodules("starlette")
    + [
        "ming_sim",
        "ming_sim.cli.terminal",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
    ]
)

datas = (
    _agno_data
    + _openai_data
    + _tiktoken_data
    + _webview_data
    + _quickjs_data
    + tree_datas("web/dist", "web/dist", exclude_parts={"_backup_rgb", "_original_before_cutout"})
    + [
        ("content", "content"),
        # Sibling copy keeps the write seam loadable if dist lookup is redirected in tests.
        ("ming_sim/organic_markdown.authority.js", "ming_sim"),
    ]
)

binaries = _agno_bin + _openai_bin + _tiktoken_bin + _webview_bin + _quickjs_bin


block_cipher = None


a = Analysis(
    ["launcher.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 不打包测试/构建工具/CLI 第三方
        # 注意：tkinter 保留——launcher 缺 key 时用其弹窗收 key（GUI 模式无 stdin）
        "pytest",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "matplotlib",
        "pandas",
        "numpy.tests",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Ming_LLM",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # pywebview 套壳无需终端窗口；debug 需看日志时改 True 或跑 dist/.../Ming_LLM 二进制
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Ming_LLM",
)

# macOS .app bundle
import sys
if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Ming_LLM.app",
        icon=None,
        bundle_identifier="com.local.mingllm",
        info_plist={
            "NSHighResolutionCapable": True,
            "LSBackgroundOnly": False,
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "0.1.0",
            # WKWebView 默认禁明文 HTTP；允许 127.0.0.1 + localhost 本地 server
            "NSAppTransportSecurity": {
                "NSAllowsLocalNetworking": True,
                "NSExceptionDomains": {
                    "localhost": {
                        "NSExceptionAllowsInsecureHTTPLoads": True,
                        "NSIncludesSubdomains": True,
                    },
                    "127.0.0.1": {
                        "NSExceptionAllowsInsecureHTTPLoads": True,
                    },
                },
            },
        },
    )
