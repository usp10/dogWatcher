import requests
import time
import hmac
import hashlib
import json
import logging
from datetime import datetime
import os
import sys

# 配置日志
log_dir = "logs"
if not os.path.exists(log_dir):
    os.makedirs(log_dir)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(log_dir, "btc_paxg_ratio.log")),
        logging.StreamHandler()
    ]
)

class BTC_PAXG_Monitor:
    def __init__(self):
        # Binance API 配置
        self.binance_base_url = "https://api.binance.com"
        self.api_timeout = 10  # API请求超时时间
        
        # 钉钉机器人配置
        self.dingtalk_webhook = "https://oapi.dingtalk.com/robot/send"
        # 请在运行前设置钉钉机器人的access_token
        self.dingtalk_token = "02fcc926215099c4d0315e453e86aa6d9af934ad538de89b13f67bc3d131ee07"  # 用户已设置的token
        self.dingtalk_secret = "加密货币"  # 可选，如果设置了加签
        
        # 监控配置
        self.alert_threshold = 26.0
        self.refresh_interval = 300  # 5分钟，单位：秒
        self.max_retry_count = 3  # API请求最大重试次数
        
        # 检查配置是否正确
        is_default_token = self.dingtalk_token == "your_dingtalk_robot_token"
        is_invalid_token = not self.dingtalk_token or len(self.dingtalk_token) < 10
        
        if is_default_token or is_invalid_token:
            print("⚠️ 警告：请在btc_paxg_ratio_monitor.py中设置正确的钉钉机器人token")
            print("示例：self.dingtalk_token = \"your_actual_token_here\"")
        else:
            print("✅ 钉钉机器人token已设置")
        
        logging.info("BTC/PAXG 价格比监控器初始化完成")
        logging.info(f"刷新间隔: {self.refresh_interval}秒，警报阈值: {self.alert_threshold}")
        if not is_default_token and not is_invalid_token:
            logging.info("钉钉机器人token已配置")
    
    def get_binance_price(self, symbol):
        """获取Binance交易所的最新价格"""
        retry_count = 0
        while retry_count < self.max_retry_count:
            try:
                endpoint = f"{self.binance_base_url}/api/v3/ticker/price"
                params = {"symbol": symbol}
                
                # 添加请求头，模拟正常的浏览器请求
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Content-Type': 'application/json'
                }
                
                response = requests.get(endpoint, params=params, headers=headers, timeout=self.api_timeout)
                response.raise_for_status()
                data = response.json()
                
                # 验证数据格式
                if "price" not in data:
                    raise ValueError(f"无效的API响应格式: {data}")
                
                price = float(data["price"])
                logging.info(f"成功获取{symbol}价格: {price:.2f}")
                return price
                
            except requests.exceptions.Timeout:
                retry_count += 1
                wait_time = 2 ** retry_count  # 指数退避
                logging.warning(f"获取{symbol}价格超时，{wait_time}秒后第{retry_count}次重试...")
                time.sleep(wait_time)
                
            except requests.exceptions.RequestException as e:
                logging.error(f"获取{symbol}价格请求异常: {str(e)}")
                return None
            except (ValueError, KeyError) as e:
                logging.error(f"解析{symbol}价格数据失败: {str(e)}")
                return None
            except Exception as e:
                logging.error(f"获取{symbol}价格发生未知错误: {str(e)}")
                return None
        
        logging.error(f"获取{symbol}价格达到最大重试次数({self.max_retry_count})")
        return None
    
    def calculate_ratio(self, btc_price, paxg_price):
        """计算BTC/PAXG价格比"""
        if btc_price and paxg_price and paxg_price > 0:
            return btc_price / paxg_price
        return None
    
    def send_dingtalk_message(self, message, title="提醒提醒提醒: BTC 价格 监控"):
        """发送消息到钉钉机器人，严格按照成功的实现格式"""
        # 检查token是否有效
        if not self.dingtalk_token or self.dingtalk_token == "your_dingtalk_robot_token" or len(self.dingtalk_token) < 30:
            print("❌ 钉钉消息发送失败: 请先设置正确的钉钉机器人token")
            logging.error(f"钉钉消息发送失败: 请先设置正确的钉钉机器人token")
            return False
            
        try:
            # 构建完整的URL
            url = f"https://oapi.dingtalk.com/robot/send?access_token={self.dingtalk_token}"
            
            # 确保消息开头包含多个关键词 - 这是最重要的！
            # 参考emergency_push.py中的成功实现格式
            markdown_content = f"提醒提醒提醒，价格价格价格！\n\n"
            markdown_content += f"### 提醒 - BTC 价格 监控 提醒\n\n"
            markdown_content += f"提醒：BTC PAXG 价格监控，{message}\n\n"
            markdown_content += message
            markdown_content += "\n\n提醒提醒提醒：请注意查看价格并及时处理！"
            
            # 严格按照成功实现的格式构造数据
            data = {
                "msgtype": "markdown",
                "markdown": {
                    "title": title,  # 标题包含多个关键词
                    "text": markdown_content
                }
            }
            
            print(f"正在发送钉钉消息，格式: markdown，标题: {title}")
            print(f"消息开头关键词部分: {markdown_content[:50]}...")
            
            # 发送请求
            headers = {'Content-Type': 'application/json;charset=utf-8'}
            response = requests.post(url, headers=headers, json=data)
            
            # 检查响应
            result = response.json()
            print(f"钉钉响应: {result}")
            
            if response.status_code == 200 and result.get('errcode') == 0:
                print("✅ 钉钉消息发送成功")
                logging.info("钉钉消息发送成功")
                return True
            else:
                error_msg = f"钉钉消息发送失败: {result.get('errmsg', '未知错误')}"
                print(f"❌ {error_msg}")
                logging.error(error_msg)
                return False
                    
        except Exception as e:
            error_msg = f"发送钉钉消息时发生异常: {str(e)}"
            print(f"❌ {error_msg}")
            logging.error(error_msg)
            return False
    
    def run_monitor(self):
        """运行监控主循环"""
        logging.info("开始运行 BTC/PAXG 价格比监控")
        logging.info(f"警报阈值: {self.alert_threshold}")
        logging.info(f"刷新间隔: {self.refresh_interval}秒")
        
        while True:
            try:
                print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 获取最新价格数据...")
                
                # 获取价格
                btc_price = self.get_binance_price("BTCUSDT")
                paxg_price = self.get_binance_price("PAXGUSDT")
                
                if btc_price and paxg_price:
                    # 计算价格比
                    ratio = self.calculate_ratio(btc_price, paxg_price)
                    
                    if ratio is not None:
                        # 构建消息内容
                        content = f"**BTCUSDT价格**: ${btc_price:,.2f}\n"
                        content += f"**PAXGUSDT价格**: ${paxg_price:,.2f}\n"
                        content += f"**BTC/PAXG 价格比**: {ratio:.2f}"
                        
                        # 判断是否需要发送警报
                        is_alert = ratio < self.alert_threshold
                        
                        # 发送钉钉消息
                        success = self.send_dingtalk_message(content)
                        
                        # 控制台输出
                        status_text = "⚠️ 价格比低于阈值，已发送警报！" if is_alert else "✅ 价格比正常"
                        print(f"BTC/PAXG 价格比: {ratio:.2f} | {status_text}")
                        print(f"钉钉消息发送: {'成功' if success else '失败'}")
                        
                        # 记录日志
                        logging.info(f"BTC/PAXG 价格比: {ratio:.2f} {'>= 阈值' if ratio >= self.alert_threshold else '< 阈值 (警报)'}")
                else:
                    error_msg = "无法获取价格数据"
                    if not btc_price:
                        error_msg += " (BTC价格获取失败)"
                    if not paxg_price:
                        error_msg += " (PAXG价格获取失败)"
                    
                    print(f"❌ {error_msg}")
                    logging.warning(error_msg)
                    
                    # 发送错误通知
                    error_content = f"**错误通知**: {error_msg}\n请检查网络连接和API状态"
                    self.send_dingtalk_message(error_content)
            
            except Exception as e:
                error_msg = f"监控运行出错: {str(e)}"
                print(f"❌ {error_msg}")
                logging.error(error_msg)
            
            # 等待下一次刷新
            remaining_time = self.refresh_interval
            print(f"\n等待下一次更新... ({remaining_time}秒)")
            
            # 倒计时显示
            while remaining_time > 0:
                try:
                    time.sleep(1)
                    remaining_time -= 1
                    if remaining_time % 30 == 0 or remaining_time <= 10:
                        print(f"{remaining_time}秒...", end='\r')
                except KeyboardInterrupt:
                    print("\n接收到停止信号，正在退出...")
                    return

def main():
    """主函数"""
    # 确保命令行输出编码正确
    if sys.stdout.encoding != 'utf-8':
        sys.stdout.reconfigure(encoding='utf-8')
    
    print("BTC/PAXG 价格比监控器")
    print("====================")
    print("功能：每5分钟计算BTC/PAXG价格比并推送至钉钉")
    print("当价格比低于26时发送警报")
    print("\n请确保在脚本中设置了正确的钉钉机器人token")
    print("\n正在启动监控...")
    
    # 创建并运行监控器
    monitor = BTC_PAXG_Monitor()
    
    # 先进行一次立即检测
    print("\n正在进行初始价格检查...")
    try:
        btc_price = monitor.get_binance_price("BTCUSDT")
        paxg_price = monitor.get_binance_price("PAXGUSDT")
        
        if btc_price and paxg_price:
            ratio = monitor.calculate_ratio(btc_price, paxg_price)
            print(f"\n初始价格检查结果：")
            print(f"  BTC价格: ${btc_price:,.2f}")
            print(f"  PAXG价格: ${paxg_price:,.2f}")
            print(f"  BTC/PAXG 价格比: {ratio:.2f}")
            if ratio < monitor.alert_threshold:
                print(f"  状态: 低于阈值，需要警报")
            else:
                print(f"  状态: 正常")
        else:
            print("\n无法获取初始价格数据，请检查网络连接和API状态")
            print("可能的原因:")
            print("  1. 网络连接问题")
            print("  2. Binance API限制")
            print("  3. 防火墙阻止")
    except Exception as e:
        print(f"\n初始价格检查出错: {str(e)}")
    
    print("\n进入定时监控模式...")
    print("按 Ctrl+C 停止监控")
    
    try:
        monitor.run_monitor()
    except KeyboardInterrupt:
        print("\n监控已停止")
        logging.info("用户中断，监控已停止")
    except Exception as e:
        error_msg = f"监控异常停止: {str(e)}"
        print(f"\n{error_msg}")
        logging.error(error_msg)
        # 尝试发送错误警报
        try:
            monitor.send_dingtalk_message(f"**监控异常通知**: {error_msg}")
        except:
            pass
        finally:
            time.sleep(3)  # 给用户时间看到错误信息

if __name__ == "__main__":
    main()