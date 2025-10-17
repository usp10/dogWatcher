#!/bin/bash

# 启动telegram_commands_bot.py
python telegram_commands_bot.py &
TELEGRAM_PID=$!

echo "Telegram机器人已启动，PID: $TELEGRAM_PID"

# 等待3秒让telegram机器人先启动
sleep 3

# 启动crypto_multiperiod_analysis.py
python crypto_multiperiod_analysis.py &
ANALYSIS_PID=$!

echo "多周期分析脚本已启动，PID: $ANALYSIS_PID"

echo "两个脚本已同时启动！"
echo "要停止脚本，请使用: kill $TELEGRAM_PID $ANALYSIS_PID"

# 等待两个进程结束
wait $TELEGRAM_PID $ANALYSIS_PID