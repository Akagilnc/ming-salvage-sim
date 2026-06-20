@echo off
REM 一键打 zip 分发包（#186，Windows）。onedir 形态：解压后根目录一个可执行 + 子目录。
REM
REM 前置（在干净 clone 里跑一次）：
REM   python -m venv .venv ^&^& .venv\Scripts\activate
REM   pip install -e . pyinstaller pywebview tiktoken
REM 然后：
REM   scripts\build_release.bat
REM
REM 产物：dist\MingSalvageSim-windows.zip
REM   解压后根目录 = 单一可执行 MingSalvageSim.exe + _internal\（依赖子目录）。
REM   LLM 后端在 app 内「设置」里自理，落 %USERPROFILE%\.ming_sim\，不随包发（零配置文件）。
REM
REM PYTHON 覆盖：默认 .venv\Scripts\python.exe（若在），否则 python。
setlocal
cd /d "%~dp0\.."

if defined PYTHON goto :havepy
if exist ".venv\Scripts\python.exe" ( set "PYTHON=.venv\Scripts\python.exe" ) else ( set "PYTHON=python" )
:havepy
echo [build] python: %PYTHON%

echo [build] 1/3 build frontend web/dist ...
pushd web
REM 失败分支先 popd 再跳 :err，否则把调用者 cwd 留在 web\（.sh 用子shell 天然避免）
call npm install || (popd & goto :err)
call npm run build || (popd & goto :err)
popd

echo [build] 2/3 PyInstaller (onedir; spec has cheat/frontend fail-loud guard) ...
"%PYTHON%" -m PyInstaller --noconfirm --clean MingSalvageSim.spec || goto :err

echo [build] 3/3 zip ...
if not exist "dist\MingSalvageSim\MingSalvageSim.exe" (
  echo [build] x dist\MingSalvageSim\MingSalvageSim.exe missing -- onedir COLLECT did not produce the exe
  goto :err
)
del /q "dist\MingSalvageSim-windows.zip" 2>nul
REM 打 onedir 目录内容（dist\MingSalvageSim\*）：解压后根目录 = MingSalvageSim.exe + _internal\
REM $ErrorActionPreference='Stop'：Compress-Archive 的非终止错误默认不置非零退出码，不加这句 || goto :err 抓不到（静默坏包）。
REM 反斜杠路径：Windows PowerShell 5.1 的 Compress-Archive 对正斜杠通配路径可能解析失败。
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; Compress-Archive -Path 'dist\MingSalvageSim\*' -DestinationPath 'dist\MingSalvageSim-windows.zip' -Force" || goto :err
echo [build] OK dist\MingSalvageSim-windows.zip
echo [build]    unzip -^> root: MingSalvageSim.exe + _internal\, zero config files.
goto :eof

:err
echo [build] FAILED
exit /b 1
