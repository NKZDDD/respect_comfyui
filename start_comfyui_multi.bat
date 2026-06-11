@echo off
setlocal enabledelayedexpansion

REM ============================================================
REM  秋叶 ComfyUI 整合包 - 批量多端口并行启动脚本 (v2)
REM
REM  用法 1（双击）：放到秋叶整合包根目录（与 绘世启动器.exe 同级），双击运行
REM  用法 2（命令行）：start_comfyui_multi.bat 4   即直接启动 4 个实例
REM
REM  关键改进 vs v1：
REM    - cd 到 ComfyUI 主目录后再启动 python
REM    - 每个实例独立 output/temp/user 目录，互不干扰
REM    - 通过生成临时 .bat 启动，避免 cmd /k 引号嵌套坑
REM    - python 一旦退出窗口保留并显示退出原因
REM    - 第 2 个起的实例默认加 --lowvram，避免显存撞死静默退出
REM ============================================================


REM ============ 可配置项 ============
set START_PORT=8188
set LISTEN=127.0.0.1

REM 多实例隔离目录开关：1=每个实例独立 output/temp/user；0=共享
set ISOLATE=1

REM 第 1 个实例的额外参数（一般用满血）
set EXTRA_ARGS_FIRST=--cpu

REM 第 2 个及之后实例的额外参数。
REM   GPU 多实例: 建议 --lowvram, 否则几乎必撞显存
REM   CPU 模式: 写 --cpu (强制纯 CPU, 不抢显存, 多实例可并行)
REM   默认 --cpu, 改成空 / --lowvram 切换成 GPU 模式
set EXTRA_ARGS_REST=--cpu

REM 启动间隔（秒），让前一个 torch 加载完再起下一个
set DELAY=10
REM ===================================


REM ============ 手动指定整合包根目录 (可选) ============
REM 如果你把本脚本放在了秋叶根目录之外, 在这里写死路径, 例如:
REM   set MANUAL_ROOT=D:\ComfyUI-aki-v3
REM 也可以通过环境变量 COMFYUI_ROOT 注入. 留空走自动探测.
set MANUAL_ROOT=

if "%MANUAL_ROOT%"=="" if not "%COMFYUI_ROOT%"=="" set MANUAL_ROOT=%COMFYUI_ROOT%

REM ============ 自动探测整合包路径 ============
if defined MANUAL_ROOT (
    set "ROOT=%MANUAL_ROOT%"
    if not "!ROOT:~-1!"=="\" set "ROOT=!ROOT!\"
) else (
    set "ROOT=%~dp0"
)

call :probe_root
if defined PYTHON if defined MAIN goto :root_ok

REM 自动探测失败 -> 交互式询问
echo.
echo =====================================================
echo [警告] 没能在以下目录自动找到 ComfyUI:
echo   %ROOT%
echo.
echo 期望该目录下有:
echo   - python\python.exe  或  python_embeded\python.exe
echo   - ComfyUI\main.py    或  main.py
echo.
echo 请把整合包根目录路径粘进来 (秋叶包就是 绘世启动器.exe 所在那一层),
echo 直接回车则退出脚本.
echo =====================================================
set /p USER_ROOT=秋叶整合包根目录: 
if "%USER_ROOT%"=="" (
    echo 已取消.
    pause & exit /b 1
)
REM 去掉用户粘贴时可能带的引号
set "USER_ROOT=%USER_ROOT:"=%"
set "ROOT=%USER_ROOT%"
if not "%ROOT:~-1%"=="\" set "ROOT=%ROOT%\"
call :probe_root
if not defined PYTHON (
    echo [错误] 你输入的目录下还是找不到 python.exe, 退出.
    pause & exit /b 1
)
if not defined MAIN (
    echo [错误] 你输入的目录下还是找不到 ComfyUI\main.py, 退出.
    pause & exit /b 1
)

:root_ok


REM ============ 实例数量 ============
set COUNT=%1
if "%COUNT%"=="" set /p COUNT=要启动几个 ComfyUI 实例？(建议 1-2 个, 多了会显存不够): 

set /a "_check=COUNT" 2>nul
if not "%_check%"=="%COUNT%" (
    echo [错误] 数量必须是正整数
    pause & exit /b 1
)
if %COUNT% LSS 1 (
    echo [错误] 数量必须 ^>= 1
    pause & exit /b 1
)


REM ============ 启动信息 ============
echo.
echo ----------------------------------------
echo  Python      : %PYTHON%
echo  ComfyUI cwd : %CWD%
echo  实例数      : %COUNT%
echo  起始端口    : %START_PORT%
echo  监听        : %LISTEN%
echo  隔离目录    : %ISOLATE%
echo  第 1 实例参数: %EXTRA_ARGS_FIRST%
echo  其他实例参数: %EXTRA_ARGS_REST%
echo  启动间隔    : %DELAY% 秒
echo ----------------------------------------
echo.

set MULTI_ROOT=%ROOT%comfyui_multi
if "%ISOLATE%"=="1" (
    if not exist "%MULTI_ROOT%" mkdir "%MULTI_ROOT%"
)


REM ============ 循环启动 ============
for /L %%i in (1,1,%COUNT%) do (
    set /a PORT=%START_PORT% + %%i - 1

    if %%i EQU 1 (
        set EXTRA=%EXTRA_ARGS_FIRST%
    ) else (
        set EXTRA=%EXTRA_ARGS_REST%
    )

    set ISO_ARGS=
    if "%ISOLATE%"=="1" (
        set INST_DIR=%MULTI_ROOT%\inst_!PORT!
        if not exist "!INST_DIR!\output" mkdir "!INST_DIR!\output"
        if not exist "!INST_DIR!\temp"   mkdir "!INST_DIR!\temp"
        if not exist "!INST_DIR!\user"   mkdir "!INST_DIR!\user"
        set ISO_ARGS=--output-directory "!INST_DIR!\output" --temp-directory "!INST_DIR!\temp" --user-directory "!INST_DIR!\user"
    )

    REM 生成一次性启动器 .bat，避免引号嵌套问题
    set LAUNCHER=%TEMP%\comfyui_inst_!PORT!.bat
    (
        echo @echo off
                echo title ComfyUI :!PORT!
        echo cd /d "%CWD%"
        echo echo ============================================
        echo echo  ComfyUI instance on port !PORT!
        echo echo  python : %PYTHON%
        echo echo  args   : --port !PORT! --listen %LISTEN% !ISO_ARGS! !EXTRA!
        echo echo ============================================
        echo echo.
        echo "%PYTHON%" %MAIN% --port !PORT! --listen %LISTEN% !ISO_ARGS! !EXTRA!
        echo echo.
        echo echo --------------------------------------------
        echo echo  ComfyUI :!PORT! 已退出, exit code %%ERRORLEVEL%%
        echo echo  常见原因: 显存不够 / 端口被占 / 依赖缺失
        echo echo --------------------------------------------
        echo pause
    ) > "!LAUNCHER!"

    echo [%%i/%COUNT%] 启动端口 !PORT! ... 启动器: !LAUNCHER!
    start "ComfyUI :!PORT!" cmd /k call "!LAUNCHER!"

    if %%i LSS %COUNT% (
        echo     等待 %DELAY% 秒后启动下一个...
        timeout /t %DELAY% /nobreak >nul
    )
)


echo.
echo ============ 全部已启动 ============
for /L %%i in (1,1,%COUNT%) do (
    set /a PORT=%START_PORT% + %%i - 1
    echo   http://%LISTEN%:!PORT!
)
echo.
echo 提示:
echo   1. 每个实例的输出在 comfyui_multi\inst_PORT\output\
echo   2. 若新窗口闪退或卡在 Checkpoint files... 后退出,
echo      99%% 是显存不够; 把 EXTRA_ARGS_REST 改成 --lowvram 或 --novram, 或减少实例数.
echo   3. 想真正并行加速, 建议每张物理 GPU 只跑 1 个实例;
echo      多 GPU 用户可在 EXTRA_ARGS 里加 --cuda-device 0 / 1.
echo.
pause
goto :eof


REM ============================================================
REM  子程序: 根据 %ROOT% 检测 python.exe / main.py 路径
REM ============================================================
:probe_root
set PYTHON=
if exist "%ROOT%python\python.exe"          set PYTHON=%ROOT%python\python.exe
if exist "%ROOT%python_embeded\python.exe"  set PYTHON=%ROOT%python_embeded\python.exe

set CWD=
set MAIN=
if exist "%ROOT%ComfyUI\main.py" (
    set CWD=%ROOT%ComfyUI
    set MAIN=main.py
) else if exist "%ROOT%main.py" (
    REM 去掉尾部 \, 保证 CWD 不以反斜杠结尾
    set CWD=%ROOT:~0,-1%
    set MAIN=main.py
)
goto :eof

