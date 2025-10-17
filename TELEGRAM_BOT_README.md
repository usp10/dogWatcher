# 电报命令机器人使用说明

## 功能介绍

这个电报机器人可以帮助您在电报群中管理加密货币持仓，提供以下命令：

1. `addcc 币种名称 long/short` - 添加加密货币到持仓列表，指定多单(long)或空单(short)类型
2. `showcc` - 显示当前持仓列表，按多空单分组显示
3. `delcc 币种名称` - 从持仓列表中删除币种
4. `help` - 显示帮助信息

## 配置步骤

1. **创建电报机器人**
   - 在Telegram中搜索 `@BotFather`
   - 发送 `/newbot` 命令创建新机器人
   - 按照提示设置机器人名称和用户名
   - 完成后，BotFather会提供一个API Token，请保存好

2. **获取聊天ID**
   - 创建一个群聊并邀请您的机器人
   - 在群中发送一条消息
   - 访问 `https://api.telegram.org/botYOUR_TOKEN/getUpdates`（替换YOUR_TOKEN为您的实际token）
   - 在返回的JSON中找到您的聊天ID

3. **配置机器人**
   - 打开 `telegram_commands_bot.py` 文件
   - 将 `TELEGRAM_BOT_TOKEN` 和 `TELEGRAM_CHAT_ID` 替换为您的实际值

## 运行机器人

1. 确保已安装必要的依赖：
```
pip install requests
```

2. 运行机器人：
```
python telegram_commands_bot.py
```

## 使用示例

在电报群中发送以下命令（记得先邀请机器人到群里）：

- 添加持仓（默认多单）：`/addcc BTCUSDT`
- 添加多单持仓：`/addcc BTCUSDT long`
- 添加空单持仓：`/addcc BTCUSDT short`
- 修改持仓类型：`/addcc BTCUSDT short`  # 将已有的BTCUSDT从多单改为空单
- 查看持仓（按多空单分组显示）：`/showcc`
- 删除持仓：`/delcc BTCUSDT`
- 获取帮助：`/help`

## 注意事项

- 持仓数据保存在 `crypto_holdings.json` 文件中
- 机器人需要持续运行才能响应命令
- 建议使用 `screen` 或 `nohup` 命令使机器人在后台运行
- 如果只需要在特定群中使用，请设置 `TELEGRAM_CHAT_ID`，否则将处理所有消息

## 与现有分析脚本集成

您可以将此机器人与 `crypto_multiperiod_analysis.py` 集成，实现持仓币种的自动分析。需要在分析脚本中读取 `crypto_holdings.json` 文件中的持仓数据，并针对这些币种进行重点分析。