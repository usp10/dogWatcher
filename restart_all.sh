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

# 查找并杀死交易所相关的分析脚本进程
echo "\n正在查找并终止交易所分析脚本进程..."

# 方法1: 精确匹配币安脚本
BINANCE_PIDS=$(ps aux | grep "python crypto_multiperiod_analysis.py" | grep -v grep | awk '{print $2}')
for pid in $BINANCE_PIDS; do
  echo "方法1 - 杀死币安分析脚本进程: $pid"
  kill -9 $pid 2>/dev/null
  if [ $? -eq 0 ]; then
    echo "币安分析脚本进程已成功终止"
  fi
done

# 方法1.1: 精确匹配OKX脚本
OKX_PIDS=$(ps aux | grep "python crypto_multiperiod_analysis_okx.py" | grep -v grep | awk '{print $2}')
for pid in $OKX_PIDS; do
  echo "方法1.1 - 杀死OKX分析脚本进程: $pid"
  kill -9 $pid 2>/dev/null
  if [ $? -eq 0 ]; then
    echo "OKX分析脚本进程已成功终止"
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

# 查找并杀死波动监控进程
VOLATILITY_PIDS=$(ps aux | grep "python volatility_monitor/monitor.py" | grep -v grep | awk '{print $2}')
for pid in $VOLATILITY_PIDS; do
  echo "杀死波动监控进程: $pid"
  kill -9 $pid 2>/dev/null
  if [ $? -eq 0 ]; then
    echo "波动监控进程已成功终止"
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
# 创建日志目录
mkdir -p logs

# 启动telegram_commands_bot.py，并将日志输出到文件
nohup python3 telegram_commands_bot.py > logs/telegram_bot.log 2>&1 &
TELEGRAM_PID=$!

echo "Telegram机器人已重新启动，PID: $TELEGRAM_PID，日志文件: logs/telegram_bot.log"

# 等待3秒让telegram机器人先启动
sleep 3

# 启动币安分析脚本，并将日志输出到文件
nohup python3 crypto_multiperiod_analysis.py > logs/binance_analysis.log 2>&1 &
BINANCE_PID=$!

echo "币安分析脚本已重新启动，PID: $BINANCE_PID"

# 启动OKX分析脚本，并将日志输出到文件
# nohup python3 crypto_multiperiod_analysis_okx.py > logs/okx_analysis.log 2>&1 &
# OKX_PID=$!

# echo "OKX分析脚本已重新启动，PID: $OKX_PID"

echo "\n所有操作已完成！Telegram + 币安分析已启动。"

# 启动波动监控
cd volatility_monitor
nohup python3 monitor.py > logs/volatility_monitor.log 2>&1 &
VOLATILITY_PID=$!
cd ..

echo "波动监控已启动，PID: $VOLATILITY_PID，日志文件: logs/volatility_monitor.log"