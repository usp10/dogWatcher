#!/bin/bash

echo "正在停止运行中的Python脚本..."

# 查找并杀死telegram_commands_bot.py进程
TELEGRAM_PIDS=$(ps aux | grep "python telegram_commands_bot.py" | grep -v grep | awk '{print $2}')
for pid in $TELEGRAM_PIDS; do
  echo "杀死Telegram机器人进程: $pid"
  kill -9 $pid 2>/dev/null
  if [ $? -eq 0 ]; then
    echo "Telegram机器人进程已成功终止"
  fi
done

# 查找并杀死crypto_multiperiod_analysis.py进程
ANALYSIS_PIDS=$(ps aux | grep "python crypto_multiperiod_analysis.py" | grep -v grep | awk '{print $2}')
for pid in $ANALYSIS_PIDS; do
  echo "杀死多周期分析脚本进程: $pid"
  kill -9 $pid 2>/dev/null
  if [ $? -eq 0 ]; then
    echo "多周期分析脚本进程已成功终止"
  fi
done

# 等待进程完全终止
sleep 2

echo "\n正在使用Git更新代码..."
# 拉取最新代码
git pull
if [ $? -eq 0 ]; then
  echo "Git更新成功！"
else
  echo "Git更新失败，请检查网络连接和Git配置"
fi

echo "\n正在重新启动脚本..."
# 启动telegram_commands_bot.py
python telegram_commands_bot.py &
TELEGRAM_PID=$!

echo "Telegram机器人已重新启动，PID: $TELEGRAM_PID"

# 等待3秒让telegram机器人先启动
sleep 3

# 启动crypto_multiperiod_analysis.py
python crypto_multiperiod_analysis.py &
ANALYSIS_PID=$!

echo "多周期分析脚本已重新启动，PID: $ANALYSIS_PID"

echo "\n所有操作已完成！两个脚本已重新启动。"