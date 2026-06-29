@echo off
REM 一键打 zip 分发包（#186，Windows）。onedir 形态：解压后根目录一个可执行 + 子目录。
REM
REM 前置（在干净 clone 里跑一次）：
REM   python -m venv .venv ^&^& .venv\Scripts\activate
REM   pip install -r requirements.txt pyinstaller pywebview tiktoken   REM 本仓无 pyproject/setup.py，用 requirements.txt（非 -e .）
REM 然后：
REM   scripts\build_release.bat
REM
REM 产物：dist\Ming_LLM-windows.zip
REM   解压后根目录 = 单一可执行 Ming_LLM.exe + _internal\（依赖子目录）。
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
"%PYTHON%" -m PyInstaller --noconfirm --clean Ming_LLM.spec || goto :err

echo [build] 3/3 zip ...
if not exist "dist\Ming_LLM\Ming_LLM.exe" (
  echo [build] x dist\Ming_LLM\Ming_LLM.exe missing -- onedir COLLECT did not produce the exe
  goto :err
)
del /q "dist\Ming_LLM-windows.zip" 2>nul
REM 打 onedir 目录内容（dist\Ming_LLM\*）：解压后根目录 = Ming_LLM.exe + _internal\
REM $ErrorActionPreference='Stop'：Compress-Archive 的非终止错误默认不置非零退出码，不加这句 || goto :err 抓不到（静默坏包）。
REM Get-ChildItem | Compress-Archive（非 -Path 'dir\*' 通配）：PS 5.1 的 Compress-Archive 用通配符路径打含子目录（如 _internal）的目录
REM 会触发已知 bug（"An item with the same key has already been added"）；管道传顶层项更稳，且保持 exe + _internal\ 在 zip 根。
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; Get-ChildItem -Path 'dist\Ming_LLM' | Compress-Archive -DestinationPath 'dist\Ming_LLM-windows.zip' -Force" || goto :err
echo [build] OK dist\Ming_LLM-windows.zip
echo [build]    unzip -^> root: Ming_LLM.exe + _internal\, zero config files.
goto :eof

:err
echo [build] FAILED
exit /b 1
