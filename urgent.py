import requests
import json
from datetime import datetime

# 钉钉webhook地址
webhook = "https://oapi.dingtalk.com/robot/send?access_token=02fcc926215099c4d0315e453e86aa6d9af934ad538de89b13f67bc3d131ee07"

def send_dingtalk_urgent(symbol="BTCUSDT", message="紧急提醒"):
    """发送钉钉紧急推送通知"""
    # 使用与mad_push_to_dingtalk相同的消息格式，因为这个格式之前应该工作过
    push_content = f"""
### ⚠️⚠️⚠️ 提醒 - 紧急价格异动 ⚠️⚠️⚠️

#### 提醒: {symbol} 紧急价格通知

- **当前价格**: 40000.0000
- **价格5分钟涨幅**: 5.00%
- **持仓方向**: long
- **盈亏状态**: 盈利
- **提醒原因**: {message}
- **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🔔 提醒: 价格紧急波动，请及时关注！
    """
    
    # 构造钉钉消息格式
    data = {
        "msgtype": "markdown",
        "markdown": {
            "title": f"提醒: {symbol} 加密货币",
            "text": push_content
        }
    }
    
    try:
        # 发送请求
        response = requests.post(
            webhook,
            headers={"Content-Type": "application/json"},
            data=json.dumps(data)
        )
        
        # 检查响应
        result = response.json()
        if result.get("errcode") == 0:
            print(f"✅ {symbol}的紧急推送发送成功")
            return True
        else:
            print(f"❌ {symbol}的紧急推送发送失败: {result}")
            return False
            
    except Exception as e:
        print(f"发送紧急推送时出错: {e}")
        return False

if __name__ == "__main__":
    # 直接发送BTCUSDT的紧急推送
    send_dingtalk_urgent("BTCUSDT", "价格波动较大，请及时关注")