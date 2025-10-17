import requests
import json
import time
from datetime import datetime
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 禁用安全警告（可选）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 钉钉webhook地址
webhook = "https://oapi.dingtalk.com/robot/send?access_token=02fcc926215099c4d0315e453e86aa6d9af934ad538de89b13f67bc3d131ee07"

def create_session():
    """创建一个带有重试机制的会话"""
    session = requests.Session()
    
    # 设置重试策略
    retry_strategy = Retry(
        total=3,  # 总重试次数
        backoff_factor=0.1,  # 重试间隔因子
        status_forcelist=[429, 500, 502, 503, 504],  # 触发重试的HTTP状态码
        allowed_methods=["POST"]  # 允许重试的HTTP方法
    )
    
    # 为HTTP和HTTPS创建适配器
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    # 设置超时
    session.timeout = 10
    
    return session

def send_mad_urgent_push(symbol="BTCUSDT", message="紧急提醒"):
    """根据时间段控制推送频率，只第一次获取价格数据后重复发送相同消息"""
    # 获取当前小时
    current_hour = datetime.now().hour
    
    # 判断是否在允许连续推送的时间范围内（晚上12点到早上7点）
    is_night_time = current_hour >= 0 and current_hour < 7
    
    # 只在第一次获取价格数据
    print(f"📊 正在获取{symbol}的价格数据...")
    
    # 随机生成模拟涨跌幅（实际应用中可以从API获取一次）
    import random
    price_change = round(random.uniform(-10, 10), 2)
    price_change_str = f"{'+' if price_change > 0 else ''}{price_change}%"
    
    # 生成固定的推送内容和数据，包含关键字"加密货币"
    push_content = f"""
### ⚠️⚠️⚠️ 加密货币紧急价格异动提醒 ⚠️⚠️⚠️

#### 加密货币提醒: {symbol} 价格异常波动

- **加密货币价格5分钟涨幅**: {price_change_str}
- **提醒原因**: {message}
- **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🔔 请及时关注加密货币市场变化！
    """
    
    data = {
        "msgtype": "markdown",
        "markdown": {
            "title": f"{symbol} {price_change_str} 价格异动",
            "text": push_content
        }
    }
    
    headers = {
        "Content-Type": "application/json",
        "Connection": "close",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    # 创建会话
    session = create_session()
    push_count = 0
    
    try:
        if is_night_time:
            print(f"🌙 夜间模式: 启动{symbol}的连续紧急推送，持续2分钟，每1秒一次...")
            total_pushes = 120  # 总共发送120次（2分钟，每秒一次）
            
            # 夜间模式：连续推送2分钟
            for i in range(1, total_pushes + 1):
                # 每10次推送后重新创建会话
                if i % 10 == 0:
                    session.close()
                    session = create_session()
                    print("🔄 会话已重置，继续推送...")
                
                send_single_push(session, webhook, data, headers, i)
                push_count = i
                time.sleep(1)
                
            print(f"✅ 夜间推送结束，共推送{push_count}条消息")
        else:
            print(f"☀️ 白天模式: 只发送一次{symbol}的紧急推送")
            # 白天模式：只推送一次
            send_single_push(session, webhook, data, headers, 1)
            push_count = 1
            print(f"✅ 白天推送结束，共推送{push_count}条消息")
    finally:
        session.close()

def send_single_push(session, webhook, data, headers, push_count):
    """发送单条推送消息"""
    try:
        # 发送请求
        response = session.post(
            webhook,
            headers=headers,
            data=json.dumps(data),
            verify=False
        )
        
        # 检查响应
        if response.status_code == 200:
            result = response.json()
            if result.get("errcode") == 0:
                print(f"✅ 第{push_count}次推送成功")
            else:
                print(f"❌ 第{push_count}次推送失败: {result}")
        else:
            print(f"❌ 第{push_count}次推送失败，HTTP状态码: {response.status_code}")
    except requests.exceptions.SSLError as e:
        print(f"SSL错误 - 第{push_count}次推送: {str(e)[:100]}...")
        # SSL错误时尝试更换会话
        session.close()
        session = create_session()
    except requests.exceptions.ConnectionError as e:
        print(f"连接错误 - 第{push_count}次推送: {str(e)[:100]}...")
        # 连接错误时尝试更换会话
        session.close()
        session = create_session()
    except Exception as e:
        print(f"其他错误 - 第{push_count}次推送: {str(e)[:100]}...")



# 如果直接运行脚本
if __name__ == "__main__":
    # 发送BTCUSDT的紧急推送
    send_mad_urgent_push("BTCUSDT", "价格波动较大，请及时关注")