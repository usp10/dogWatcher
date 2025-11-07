#!/bin/bash

# 创建日志目录
mkdir -p logs

# 启动telegram_commands_bot.py，并将日志输出到文件
nohup python telegram_commands_bot.py > logs/telegram_bot.log 2>&1 &
TELEGRAM_PID=$!

echo "Telegram机器人已启动，PID: $TELEGRAM_PID，日志文件: logs/telegram_bot.log"

# 等待3秒让telegram机器人先启动
sleep 3

# 启动crypto_multiperiod_analysis.py (Binance)，并将日志输出到文件
nohup python crypto_multiperiod_analysis.py > logs/binance_analysis.log 2>&1 &
BINANCE_ANALYSIS_PID=$!

echo "币安多周期分析脚本已启动，PID: $BINANCE_ANALYSIS_PID，日志文件: logs/binance_analysis.log"

# 启动crypto_multiperiod_analysis_okx.py (OKX)，并将日志输出到文件
nohup python crypto_multiperiod_analysis_okx.py > logs/okx_analysis.log 2>&1 &
OKX_ANALYSIS_PID=$!

echo "OKX多周期分析脚本已启动，PID: $OKX_ANALYSIS_PID，日志文件: logs/okx_analysis.log"

echo "所有脚本已同时启动！"
echo "要停止脚本，请使用: kill $TELEGRAM_PID $BINANCE_ANALYSIS_PID $OKX_ANALYSIS_PID"

# 等待所有进程结束
wait $TELEGRAM_PID $BINANCE_ANALYSIS_PID $OKX_ANALYSIS_PID