#!/bin/bash
# BTC/SOL/ETH 波动监控后台服务
# 每1分钟检测一次，对比5分钟前价格
# 消息通知由 Cron job 负责发送

cd /root/.openclaw/workspace/volatility_monitor

echo "🚀 波动监控服务启动 (每1分钟检测)"

while true; do
    current_time=$(date "+%Y-%m-%d %H:%M:%S")
    echo "[$current_time] 检测中..."
    
    python3 monitor.py 2>&1

    sleep 60
done
