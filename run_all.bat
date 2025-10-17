@echo off

echo 启动Telegram机器人...
start cmd /c "python telegram_commands_bot.py"

echo 等待3秒让Telegram机器人先启动...
ping 127.0.0.1 -n 4 > nul

echo 启动多周期分析脚本...
start cmd /c "python crypto_multiperiod_analysis.py"

echo 两个脚本已同时启动！
echo 要停止脚本，请关闭相应的命令窗口。
pause