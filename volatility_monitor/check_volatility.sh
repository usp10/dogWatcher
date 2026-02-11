#!/bin/bash
# 波动监控并输出结果
cd /root/.openclaw/workspace/volatility_monitor
result=$(/usr/bin/python3 monitor.py 2>&1)
echo "$result"
