#!/usr/bin/env python3
"""BTC/SOL/ETH/DOGE 一分钟波动监控 - 每分钟检测，对比5分钟前价格"""

import requests
import time
import json
import os
from datetime import datetime

# OpenClaw API 配置
GATEWAY_URL = "http://127.0.0.1:18789"
SESSION_KEY = "main"

# 钉钉配置
DINGTALK_ROBOT_TOKEN = "02fcc926215099c4d0315e453e86aa6d9af934ad538de89b13f67bc3d131ee07"
DINGTALK_WEBHOOK = f"https://oapi.dingtalk.com/robot/send?access_token={DINGTALK_ROBOT_TOKEN}"

# CallMeBot Telegram 语音通话配置
CALLMEBOT_API = "https://api.callmebot.com/start.php"
CALLMEBOT_USER = "@usp10dll"
CALLMEBOT_LANG = "zh-CN"
CALLMEBOT_RPT = 3  # 重复播报次数

# 饭碗警告 Webhook (电话通知)
FANWAN_WEBHOOK = "https://fwalert.com/7006d04b-160a-45a8-bd05-46e7861edf60"

# 存储价格文件
PRICE_FILE = "/root/.openclaw/workspace/volatility_monitor/prices.json"
VOLATILITY_FILE = "/root/.openclaw/workspace/volatility_monitor/.last_volatility"
# 波动阈值 (1%)
THRESHOLD = 0.01
# 对比5分钟前的价格（300秒）
COMPARE_INTERVAL = 300
# 保存最近价格记录的分钟数
KEEP_MINUTES = 10

# 夜间时段配置 (02:00 - 08:00)
NIGHT_START_HOUR = 2
NIGHT_END_HOUR = 8

# 夜间连发配置
NIGHT_MSGS_PER_MINUTE = 10  # 每分钟最多发送10条
NIGHT_INTERVAL = 6  # 发送间隔6秒 (60秒/10条)

def get_binance_price(symbol):
    """获取币安价格"""
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            return float(resp.json()["price"])
    except:
        pass
    return None

def load_price_history():
    """加载价格历史记录"""
    if os.path.exists(PRICE_FILE):
        with open(PRICE_FILE, 'r') as f:
            data = json.load(f)
            if "prices" in data:
                return data
    return {"prices": []}

def save_price_history(data):
    """保存价格历史记录，保留最近KEEP_MINUTES分钟的数据"""
    os.makedirs(os.path.dirname(PRICE_FILE), exist_ok=True)
    
    # 清理旧数据
    cutoff_time = time.time() - (KEEP_MINUTES * 60)
    data["prices"] = [p for p in data["prices"] if p["time"] > cutoff_time]
    
    with open(PRICE_FILE, 'w') as f:
        json.dump(data, f)

def find_price_5min_ago(data):
    """找到5分钟前的价格记录"""
    target_time = time.time() - COMPARE_INTERVAL
    prices = data.get("prices", [])
    
    # 找到最接近5分钟前的那条记录
    best_match = None
    min_diff = float('inf')
    
    for p in prices:
        diff = abs(p["time"] - target_time)
        if diff < min_diff and diff < 120:  # 允许2分钟内的误差
            min_diff = diff
            best_match = p
    
    return best_match

def send_to_main_session(message):
    """发送消息到主会话（QQ）"""
    try:
        url = f"{GATEWAY_URL}/sessions/{SESSION_KEY}/send"
        resp = requests.post(url, json={"message": message}, timeout=5)
        return resp.status_code == 200
    except:
        return False

def is_night_time():
    """判断当前是否为夜间时段 (02:00-08:00)"""
    current_hour = datetime.now().hour
    return NIGHT_START_HOUR <= current_hour < NIGHT_END_HOUR

def send_to_dingtalk(message):
    """发送消息到钉钉群"""
    try:
        headers = {'Content-Type': 'application/json;charset=utf-8'}
        data = {
            "msgtype": "markdown",
            "markdown": {
                "title": "价格行为波动警报",
                "text": f"**价格行为** {message}"
            }
        }
        resp = requests.post(DINGTALK_WEBHOOK, headers=headers, json=data, timeout=5)
        return resp.status_code == 200 and resp.json().get('errcode') == 0
    except:
        return False

def send_to_callmebot(alert_text):
    """通过 CallMeBot 发送 Telegram 语音通话/消息"""
    try:
        # 清理消息文本，去除特殊字符
        text = alert_text.replace("\n", " ").strip()
        url = f"{CALLMEBOT_API}?user={CALLMEBOT_USER}&text={text}&lang={CALLMEBOT_LANG}&rpt={CALLMEBOT_RPT}"
        resp = requests.get(url, timeout=10)
        return resp.status_code == 200
    except:
        return False

def send_to_fanwan(alert_text):
    """发送通知到饭碗警告（电话通知）"""
    try:
        resp = requests.get(FANWAN_WEBHOOK, timeout=10)
        return resp.status_code == 200
    except:
        return False

def check_volatility():
    """检查波动 - 每分钟检测，对比5分钟前价格"""
    symbols = {
        "BTC": ["BTCUSDT", "BTC-USDT"],
        "SOL": ["SOLUSDT", "SOL-USDT"],
        "ETH": ["ETHUSDT", "ETH-USDT"],
        "DOGE": ["DOGEUSDT", "DOGE-USDT"]
    }

    data = load_price_history()
    current_time = time.time()
    new_prices = {}
    alerts = []

    # 获取当前价格
    for name, symbol_list in symbols.items():
        price = None
        for sym in symbol_list:
            price = get_binance_price(sym)
            if price:
                break
        if price:
            new_prices[name] = price

    # 保存当前价格记录
    data["prices"].append({
        "time": current_time,
        "prices": new_prices.copy()
    })
    save_price_history(data)
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 已记录当前价格")

    # 找到5分钟前的价格记录
    baseline_record = find_price_5min_ago(data)
    
    if baseline_record:
        baseline_prices = baseline_record["prices"]
        baseline_time = baseline_record["time"]
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 对比 {int(time.time() - baseline_time)}秒前价格")

        # 对比价格
        for name, price in new_prices.items():
            baseline_price = baseline_prices.get(name)
            
            if baseline_price and baseline_price > 0:
                change_pct = (price - baseline_price) / baseline_price
                abs_change = abs(change_pct)

                if abs_change > THRESHOLD:
                    direction = "📈 上涨" if change_pct > 0 else "📉 下跌"
                    time_str = time.strftime("%Y-%m-%d %H:%M:%S")
                    alert_msg = f"【{time_str}】{name} 5分钟波动 {abs_change*100:.2f}% {direction}\n"
                    alert_msg += f"  价格: {baseline_price:.2f} → {price:.2f}\n"
                    alerts.append(alert_msg)
    else:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 暂无5分钟前的价格记录，将从下次开始检测")

    # 保存检测结果
    with open(VOLATILITY_FILE, 'w') as f:
        if alerts:
            f.write("🚨 波动检测:\n")
            for alert in alerts:
                f.write(alert)
        else:
            f.write(f"【{current_time}】无明显波动\n")
    
    return alerts

def send_alerts(alerts, repeat_count=1):
    """发送警报消息，支持连发模式"""
    if not alerts:
        return
    
    msg_prefix = "🚨 **波动警报** 🚨\n\n"
    dingtalk_prefix = "### 🚨 波动警报\n\n"
    
    # 夜间模式：连续发送多次
    if is_night_time() and repeat_count > 1:
        print(f"🌙 夜间模式检测到波动，将连续发送 {repeat_count} 条提醒...")
        for i in range(repeat_count):
            # 分割消息，避免单条过长
            for j, alert in enumerate(alerts):
                msg = f"🔔 【第{i+1}/{repeat_count}次】\n{msg_prefix}{alert}"
                if send_to_main_session(msg):
                    print(f"✅ 夜间提醒 第{i+1}次 - {j+1}/{len(alerts)} 条发送成功")
                else:
                    print(f"❌ 夜间提醒 第{i+1}次 - {j+1}/{len(alerts)} 条发送失败")
                time.sleep(NIGHT_INTERVAL)  # 间隔发送
    else:
        # 白天模式：正常发送
        msg = msg_prefix + "".join(alerts)
        if send_to_main_session(msg):
            print("\n✅ 已发送通知到QQ")
        else:
            print("\n❌ QQ发送失败")

    # 钉钉通知保持不变
    dingtalk_msg = dingtalk_prefix + "".join(alerts)
    if send_to_dingtalk(dingtalk_msg):
        print("✅ 已发送通知到钉钉")
    else:
        print("❌ 钉钉发送失败")

    # Telegram 语音通话通知 (CallMeBot)
    callmebot_msg = " ".join([a.replace("\n", " ") for a in alerts])
    if send_to_callmebot(callmebot_msg):
        print("✅ 已发送 Telegram 语音通话通知")
    else:
        print("❌ Telegram 语音通话通知发送失败")

    # 饭碗警告电话通知
    if send_to_fanwan(""):
        print("✅ 已触发饭碗警告电话通知")
    else:
        print("❌ 饭碗警告电话通知发送失败")

if __name__ == "__main__":
    alerts = check_volatility()
    for alert in alerts:
        print(alert)
        
    if alerts:
        # 判断是否为夜间时段
        if is_night_time():
            # 夜间模式：发送3次，每次间隔6秒，共约18秒
            send_alerts(alerts, repeat_count=3)
        else:
            # 白天模式：只发送1次
            send_alerts(alerts, repeat_count=1)
