@echo off

echo 正在停止运行中的Python脚本...

REM 查找并终止telegram_commands_bot.py进程
for /f "tokens=2" %%a in ('tasklist /fi "imagename eq python.exe" /v /fo list /fi "windowtitle eq *telegram_commands_bot.py*" ^| findstr PID') do (
  set "TELEGRAM_PID=%%a"
)
if defined TELEGRAM_PID (
  echo 杀死Telegram机器人进程: %TELEGRAM_PID%
  taskkill /PID %TELEGRAM_PID% /F
  if %errorlevel% equ 0 (
    echo Telegram机器人进程已成功终止
  )
)

REM 查找并终止crypto_multiperiod_analysis.py进程
for /f "tokens=2" %%a in ('tasklist /fi "imagename eq python.exe" /v /fo list /fi "windowtitle eq *crypto_multiperiod_analysis.py*" ^| findstr PID') do (
  set "ANALYSIS_PID=%%a"
)
if defined ANALYSIS_PID (
  echo 杀死多周期分析脚本进程: %ANALYSIS_PID%
  taskkill /PID %ANALYSIS_PID% /F
  if %errorlevel% equ 0 (
    echo 多周期分析脚本进程已成功终止
  )
)

REM 使用更通用的方法查找并终止进程
wmic process where "commandline like '%telegram_commands_bot.py%'" call terminate > nul 2>&1
wmic process where "commandline like '%crypto_multiperiod_analysis.py%'" call terminate > nul 2>&1

echo 等待进程完全终止...
ping 127.0.0.1 -n 3 > nul

echo.
echo 正在使用Git更新代码...
REM 拉取最新代码
git pull
if %errorlevel% equ 0 (
  echo Git更新成功！
) else (
  echo Git更新失败，请检查网络连接和Git配置
)

echo.
echo 正在重新启动脚本...
REM 启动telegram_commands_bot.py
start cmd /c "title Telegram Bot && python telegram_commands_bot.py"

echo Telegram机器人已重新启动

REM 等待3秒让telegram机器人先启动
echo 等待3秒让Telegram机器人初始化...
ping 127.0.0.1 -n 4 > nul

REM 启动crypto_multiperiod_analysis.py
start cmd /c "title Crypto Analysis && python crypto_multiperiod_analysis.py"

echo 多周期分析脚本已重新启动

echo.
echo 所有操作已完成！两个脚本已重新启动。
pause