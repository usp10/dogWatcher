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

# 查找并杀死crypto_multiperiod_analysis.py进程（使用更宽松的匹配模式）
echo "\n正在查找并终止多周期分析脚本进程..."

# 方法1: 精确匹配
ANALYSIS_PIDS=$(ps aux | grep "python crypto_multiperiod_analysis.py" | grep -v grep | awk '{print $2}')
for pid in $ANALYSIS_PIDS; do
  echo "方法1 - 杀死精确匹配进程: $pid"
  kill -9 $pid 2>/dev/null
  if [ $? -eq 0 ]; then
    echo "精确匹配进程已成功终止"
  fi
done

# 方法2: 使用正则表达式匹配crypto和analysis关键词
CRYPTO_ANALYSIS_PIDS=$(ps aux | grep -E "[p]ython.*[c]rypto.*[a]nalysis" | grep -v grep | awk '{print $2}')
for pid in $CRYPTO_ANALYSIS_PIDS; do
  echo "方法2 - 杀死crypto+analysis进程: $pid"
  kill -9 $pid 2>/dev/null
  if [ $? -eq 0 ]; then
    echo "crypto+analysis进程已成功终止"
  fi
done

# 方法3: 查找所有可能的crypto_xxx_analysis进程变体
ALL_VARIANTS_PIDS=$(ps aux | grep -E "[c]rypto_[^ ]*_analysis" | grep python | grep -v grep | awk '{print $2}')
for pid in $ALL_VARIANTS_PIDS; do
  echo "方法3 - 杀死变体进程: $pid"
  kill -9 $pid 2>/dev/null
  if [ $? -eq 0 ]; then
    echo "变体进程已成功终止"
  fi
done

# 方法4: 终极清理 - 终止所有包含crypto的Python进程
echo "\n执行终极进程清理..."
FINAL_CLEANUP_PIDS=$(ps aux | grep -E "[p]ython" | grep -E "[c]rypto" | grep -v grep | awk '{print $2}')
for pid in $FINAL_CLEANUP_PIDS; do
  echo "终极清理 - 终止进程: $pid"
  kill -9 $pid 2>/dev/null
  if [ $? -eq 0 ]; then
    echo "终极清理进程已成功终止"
  fi
done

# 等待进程完全终止
echo "\n等待进程完全终止..."
sleep 3

# 再次检查是否还有crypto相关进程
REMAINING_PIDS=$(ps aux | grep -E "[p]ython" | grep -E "[c]rypto" | grep -v grep | awk '{print $2}')
if [ ! -z "$REMAINING_PIDS" ]; then
  echo "\n警告: 发现仍有残留进程，尝试再次终止:"
  for pid in $REMAINING_PIDS; do
    echo "再次尝试终止残留进程: $pid"
    kill -9 $pid 2>/dev/null
    if [ $? -eq 0 ]; then
      echo "残留进程已成功终止"
    else
      echo "无法终止残留进程: $pid"
    fi
  done
fi

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