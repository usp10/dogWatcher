# Volatility Monitor

BTC/SOL/ETH 5分钟波动监控，夜间时段自动连发提醒。

## 功能特性

- 每分钟检测一次价格
- 对比5分钟前价格，计算波动幅度
- 波动超过1%时触发警报
- **夜间模式 (02:00-08:00)**: 自动连发3次提醒，间隔6秒
- 同时推送到 QQ 和钉钉

## 文件结构

```
volatility_monitor/
├── monitor.py           # 主程序
├── check_volatility.sh  # Shell 包装脚本
├── run_monitor.sh      # 运行脚本
└── README.md            # 本文档
```

## 使用方法

### 手动运行

```bash
cd /root/.openclaw/workspace/dogWatcher/volatility_monitor
python3 monitor.py
```

### 配合 cron 每分钟执行

```bash
# 编辑 crontab
crontab -e

# 添加以下行
* * * * * cd /root/.openclaw/workspace/dogWatcher/volatility_monitor && python3 monitor.py >> /root/.openclaw/workspace/dogWatcher/volatility_monitor/logs/monitor.log 2>&1
```

## 配置项

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `THRESHOLD` | 0.01 | 波动阈值 (1%) |
| `COMPARE_INTERVAL` | 300 | 对比时间间隔 (秒) |
| `KEEP_MINUTES` | 10 | 价格历史保留分钟数 |
| `NIGHT_START_HOUR` | 2 | 夜间模式开始时间 |
| `NIGHT_END_HOUR` | 8 | 夜间模式结束时间 |
| `NIGHT_INTERVAL` | 6 | 夜间连发间隔 (秒) |

## 输出示例

### 白天模式 (单次发送)
```
🚨 **波动警报** 🚨

【2026-02-09 10:15:00】BTC 5分钟波动 1.23% 📈 上涨
  价格: 72000.00 → 72885.60
```

### 夜间模式 (连发3次)
```
🔔 【第1/3次】
🚨 **波动警报** 🚨

【2026-02-09 03:15:00】BTC 5分钟波动 1.23% 📉 下跌
  价格: 72000.00 → 71144.00
```

## 日志位置

- `/root/.openclaw/workspace/dogWatcher/volatility_monitor/logs/monitor.log`
- `/root/.openclaw/workspace/volatility_monitor/prices.json`
- `/root/.openclaw/workspace/volatility_monitor/.last_volatility`
