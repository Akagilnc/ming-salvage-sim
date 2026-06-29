#!/usr/bin/env bash
# 一键打 zip 分发包（#186，macOS / Linux）。onedir 形态：解压后根目录一个可执行（+ 子目录）。
#
# 前置（在干净 clone 里跑一次）：
#   python -m venv .venv && . .venv/bin/activate
#   pip install -r requirements.txt pyinstaller pywebview tiktoken   # 本仓无 pyproject/setup.py，用 requirements.txt（非 -e .）
# 然后：
#   scripts/build_release.sh
#
# 产物：dist/Ming_LLM-<macos|linux>.zip
#   macOS → 解压得 Ming_LLM.app（双击即用，原生窗口；含 Info.plist 放行本地 HTTP）
#   Linux → 解压得 Ming_LLM（可执行）+ _internal/（依赖子目录）
# LLM 后端在 app 内「设置」里自理，落 ~/.ming_sim/，不随包发（零配置文件）。
#
# PYTHON 覆盖：默认用 .venv/bin/python（若在），否则 python3。
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -n "${PYTHON:-}" ]; then
  PY="$PYTHON"
elif [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  PY="python3"
fi
echo "[build] 用 python: $PY ($("$PY" --version 2>&1))"

# fail-fast：Linux 用 zip 打包（mac 用 ditto），精简镜像/CI 可能没装 zip——慢构建前先拦，别跑到最后一步才挂。
if [ "$(uname -s)" = "Linux" ] && ! command -v zip >/dev/null 2>&1; then
  echo "[build] ✗ Linux 需要 zip 但未安装。先装：apt-get install zip / dnf install zip" >&2
  exit 1
fi

echo "[build] 1/3 构建前端 web/dist ..."
( cd web && npm install && npm run build )

echo "[build] 2/3 PyInstaller 打包（onedir + mac .app；spec 自带金手指/前端缺失 fail-loud 守门）..."
"$PY" -m PyInstaller --noconfirm --clean Ming_LLM.spec

echo "[build] 3/3 打 zip ..."
case "$(uname -s)" in
  Darwin)
    [ -d "dist/Ming_LLM.app" ] || { echo "[build] ✗ dist/Ming_LLM.app 缺失（spec BUNDLE 段未产出？）"; exit 1; }
    rm -f "dist/Ming_LLM-macos.zip"
    # ditto 是 macOS 打 .app 的正解：保留 bundle 内符号链接 / 资源叉，--keepParent 让 .app 当 zip 顶层
    ( cd dist && ditto -c -k --sequesterRsrc --keepParent "Ming_LLM.app" "Ming_LLM-macos.zip" )
    echo "[build] ✅ dist/Ming_LLM-macos.zip"
    echo "[build]    解压 → Ming_LLM.app（双击即用），零配置文件。"
    ;;
  Linux)
    [ -d "dist/Ming_LLM" ] || { echo "[build] ✗ dist/Ming_LLM/ 缺失（onedir COLLECT 未产出？）"; exit 1; }
    rm -f "dist/Ming_LLM-linux.zip"
    # 打 onedir 目录的内容：解压后根目录 = 单一可执行 Ming_LLM + _internal/ 子目录
    ( cd "dist/Ming_LLM" && zip -ry "../Ming_LLM-linux.zip" . )
    echo "[build] ✅ dist/Ming_LLM-linux.zip"
    echo "[build]    解压 → 根目录 Ming_LLM（可执行）+ _internal/，零配置文件。"
    ;;
  *)
    echo "[build] 未知 OS：$(uname -s)。Windows 用 scripts/build_release.bat"; exit 1 ;;
esac
