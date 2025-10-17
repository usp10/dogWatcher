import sys
import requests
from datetime import datetime

# 导入CryptoAnalyzer类
from crypto_multiperiod_analysis import CryptoAnalyzer

# 配置参数
DINGTALK_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=02fcc926215099c4d0315e453e86aa6d9af934ad538de89b13f67bc3d131ee07"

# 创建分析器实例
analyzer = CryptoAnalyzer(dingtalk_webhook=DINGTALK_WEBHOOK)

# 紧急推送函数
def send_emergency_push(symbol="BTCUSDT", message="紧急提醒"):
    """发送紧急推送通知"""
    print(f"正在发送{symbol}的紧急推送...")
    
    # 构建紧急推送消息，确保开头就包含关键词
    push_content = f"""
提醒提醒提醒，价格价格价格！

### 提醒 - {symbol} 价格紧急通知

提醒：{symbol} 价格提醒，{message}

- **价格时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- **价格状态**: 紧急
- **价格类型**: 手动触发

提醒提醒提醒：请注意查看价格并及时处理！
    """
    
    # 发送钉钉通知，标题也包含多个关键词
    success = analyzer.send_dingtalk_notification(
        push_content, 
        title=f"提醒提醒：{symbol} 价格紧急通知提醒 加密货币"
    )
    
    if success:
        print(f"✅ {symbol}的紧急推送发送成功")
    else:
        print(f"❌ {symbol}的紧急推送发送失败")
    
    return success

if __name__ == "__main__":
    # 获取命令行参数
    symbol = sys.argv[1] if len(sys.argv) > 1 else "BTCUSDT"
    message = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "紧急提醒"
    
    # 发送紧急推送
    send_emergency_push(symbol, message)