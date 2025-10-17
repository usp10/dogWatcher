import logging
import json
import os
import time
import subprocess
import requests
import urllib3
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 禁用安全警告（可选）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class TelegramCommandsBot:
    def __init__(self, token, chat_id=None):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.holdings_file = "crypto_holdings.json"
        self.session = self.create_session()  # 先创建会话，用于可能的欢迎消息发送
        self.load_holdings()
        
        # 检查是否有重启标志，如有则发送欢迎消息
        self.check_restart_flag()
        
    def create_session(self):
        """创建一个带有重试机制的会话"""
        session = requests.Session()
        
        # 设置重试策略（移除allowed_methods参数以兼容较旧版本的requests库）
        retry_strategy = Retry(
            total=3,  # 总重试次数
            backoff_factor=0.1,  # 重试间隔因子
            status_forcelist=[429, 500, 502, 503, 504]  # 触发重试的HTTP状态码
        )
        
        # 为HTTP和HTTPS创建适配器
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        # 设置超时
        session.timeout = 10
        
        return session
    
    def check_restart_flag(self):
        """检查重启标志，如果存在则发送欢迎消息"""
        try:
            restart_flag_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.restart_flag')
            if os.path.exists(restart_flag_path):
                # 读取重启标志文件中的聊天ID
                with open(restart_flag_path, 'r', encoding='utf-8') as f:
                    restart_chat_id = f.read().strip()
                
                # 发送欢迎消息
                welcome_message = """
🎉 机器人已成功重启！

✅ 系统已完成以下操作：
• 更新代码库
• 重启所有服务
• 恢复监控功能

🔍 当前状态：
• 机器人已在线并正常工作
• 持仓数据已加载
• 命令处理功能已就绪

ℹ️ 可以使用 /help 查看可用的命令列表
                    """
                self.send_message(restart_chat_id, welcome_message)
                logger.info(f"已向聊天ID {restart_chat_id} 发送重启欢迎消息")
                
                # 删除重启标志文件，避免下次启动再次触发
                os.remove(restart_flag_path)
                logger.info("已删除重启标志文件")
        except Exception as e:
            logger.error(f"检查重启标志时出错: {e}")
    
    def load_holdings(self):
        """加载持仓数据"""
        try:
            if os.path.exists(self.holdings_file):
                with open(self.holdings_file, 'r', encoding='utf-8') as f:
                    self.holdings = json.load(f)
            else:
                self.holdings = {}
                self.save_holdings()
        except Exception as e:
            logger.error(f"加载持仓数据失败: {e}")
            self.holdings = {}
    
    def save_holdings(self):
        """保存持仓数据"""
        try:
            with open(self.holdings_file, 'w', encoding='utf-8') as f:
                json.dump(self.holdings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存持仓数据失败: {e}")
    
    def send_message(self, chat_id, text, parse_mode="Markdown"):
        """发送消息到电报"""
        try:
            url = f"{self.base_url}/sendMessage"
            params = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode
            }
            # 使用会话发送请求
            response = self.session.get(url, params=params)
            if response.status_code == 200 and response.json().get('ok'):
                return True
            else:
                logger.error(f"发送消息失败: {response.text}")
                return False
        except Exception as e:
            logger.error(f"发送消息异常: {e}")
            # 异常时重建会话
            self.session = self.create_session()
            return False
    
    def get_crypto_price(self, symbol):
        """获取加密货币的当前价格（使用合约API）"""
        try:
            # 使用币安合约API获取价格
            url = f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={symbol}"
            
            try:
                # 尝试使用当前会话
                response = self.session.get(
                    url,
                    headers={
                        "Connection": "close",  # 避免连接复用问题
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    },
                    verify=False  # 禁用SSL验证（解决部分SSL握手问题）
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return float(data.get('price', 0))
                else:
                    logger.error(f"获取价格失败 {symbol}: {response.status_code} - {response.text}")
                    return None
            except requests.exceptions.SSLError:
                logger.warning(f"SSL错误，尝试更换会话后重试...")
                # 重建会话
                self.session = self.create_session()
                # 重试请求
                response = self.session.get(url, verify=False)
                if response.status_code == 200:
                    data = response.json()
                    return float(data.get('price', 0))
                else:
                    logger.error(f"重试后获取价格失败 {symbol}: {response.status_code}")
                    return None
            except requests.exceptions.ConnectionError:
                logger.warning(f"连接错误，尝试更换会话后重试...")
                # 重建会话
                self.session = self.create_session()
                # 重试请求
                response = self.session.get(url, verify=False)
                if response.status_code == 200:
                    data = response.json()
                    return float(data.get('price', 0))
                else:
                    logger.error(f"重试后获取价格失败 {symbol}: {response.status_code}")
                    return None
        except Exception as e:
            logger.error(f"获取价格异常 {symbol}: {e}")
            # 异常发生时尝试使用REST API（备用）
            try:
                rest_url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
                response = requests.get(rest_url, timeout=5, verify=False)
                if response.status_code == 200:
                    data = response.json()
                    return float(data.get('price', 0))
            except Exception as backup_e:
                logger.error(f"备用API获取价格也失败 {symbol}: {backup_e}")
            return None
    
    def get_updates(self, offset=None):
        """获取更新"""
        try:
            url = f"{self.base_url}/getUpdates"
            params = {"timeout": 30}
            if offset:
                params["offset"] = offset
            # 使用会话发送请求
            response = self.session.get(url, params=params)
            if response.status_code == 200 and response.json().get('ok'):
                return response.json().get('result', [])
            else:
                logger.error(f"获取更新失败: {response.text}")
                return []
        except Exception as e:
            logger.error(f"获取更新异常: {e}")
            # 异常时重建会话
            self.session = self.create_session()
            return []
    
    def handle_addcc(self, chat_id, command_args):
        """处理添加持仓命令"""
        args = command_args.strip().split(' ')
        
        if len(args) < 1:
            self.send_message(chat_id, "❌ 请提供要添加的币种，格式：`addcc 币种名称 long/short [价格]`")
            return
        
        symbol = args[0].upper()
        # 自动添加USDT后缀（如果没有的话）
        if not symbol.endswith('USDT'):
            symbol = f"{symbol}USDT"
        
        position_type = "long"  # 默认多单
        entry_price = None
        
        # 如果提供了第二个参数，检查是否为 long 或 short
        if len(args) >= 2:
            position_type = args[1].lower()
            if position_type not in ["long", "short"]:
                self.send_message(chat_id, "❌ 持仓类型必须是 long 或 short，格式：`addcc 币种名称 long/short [价格]`")
                return
        
        # 如果提供了第三个参数，尝试解析为价格
        if len(args) >= 3:
            try:
                entry_price = float(args[2])
                if entry_price <= 0:
                    self.send_message(chat_id, "❌ 价格必须大于0")
                    return
            except ValueError:
                self.send_message(chat_id, "❌ 无效的价格格式，请输入数字")
                return
        
        # 如果没有提供价格，获取当前价格
        if entry_price is None:
            entry_price = self.get_crypto_price(symbol)
        
        if symbol in self.holdings:
            # 如果已存在，更新持仓信息
            old_type = self.holdings[symbol].get("position_type", "long")
            old_price = self.holdings[symbol].get("entry_price", None)
            
            self.holdings[symbol]["position_type"] = position_type
            self.holdings[symbol]["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.holdings[symbol]["entry_price"] = entry_price
            
            self.save_holdings()
            
            # 根据是否有价格变化生成消息
            if old_type != position_type and old_price != entry_price:
                new_price_str = f"${entry_price:.4f}" if entry_price is not None else "未知"
                self.send_message(chat_id, f"🔄 已更新 {symbol}:\n- 持仓类型: 从 {old_type} 到 {position_type}\n- 入场价: {'$' + str(old_price) if old_price else '未知'} 到 {new_price_str}")
            elif old_type != position_type:
                self.send_message(chat_id, f"🔄 已更新 {symbol} 的持仓类型：从 {old_type} 到 {position_type}")
            elif old_price != entry_price:
                new_price_str = f"${entry_price:.4f}" if entry_price is not None else "未知"
                self.send_message(chat_id, f"🔄 已更新 {symbol} 的入场价：{'$' + str(old_price) if old_price else '未知'} 到 {new_price_str}")
            else:
                self.send_message(chat_id, f"ℹ️ {symbol} 的持仓信息未变更")
        else:
            # 检查是否为有效交易对（如果没有提供价格）
            if entry_price is None:
                self.send_message(chat_id, f"❌ 无法添加 {symbol}，无效的交易对或无法获取价格")
                return
            
            self.holdings[symbol] = {
                "added_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "position_type": position_type,
                "status": "持仓",
                "entry_price": entry_price
            }
            self.save_holdings()
            position_text = "多单" if position_type == "long" else "空单"
            self.send_message(chat_id, f"✅ 已成功添加 {symbol} 到持仓列表，类型：{position_text}\n入场价: ${entry_price:.4f}")
    
    def handle_showcc(self, chat_id):
        """处理列出持仓命令，显示盈亏情况"""
        if not self.holdings:
            self.send_message(chat_id, "📋 当前没有持仓")
            return
        
        # 按多空单分组显示
        long_positions = []
        short_positions = []
        
        for symbol, info in self.holdings.items():
            position_type = info.get("position_type", "long")
            if position_type == "long":
                long_positions.append((symbol, info))
            else:
                short_positions.append((symbol, info))
        
        message = "📊 **当前持仓列表**\n\n"
        
        # 显示多单
        if long_positions:
            message += "📈 **多单持仓**\n"
            for i, (symbol, info) in enumerate(long_positions, 1):
                added_at = info.get("added_at", "未知")
                entry_price = info.get("entry_price", "未知")
                profit_loss_text = ""
                
                # 计算盈亏
                if entry_price != "未知" and entry_price is not None:
                    current_price = self.get_crypto_price(symbol)
                    if current_price:
                        profit_percent = ((current_price - entry_price) / entry_price) * 100
                        profit_loss_text = f" 盈亏: {'+' if profit_percent > 0 else ''}{profit_percent:.2f}%"
                        if profit_percent > 0:
                            profit_loss_text += " 🟢"
                        elif profit_percent < 0:
                            profit_loss_text += " 🔴"
                        else:
                            profit_loss_text += " ⚪"
                
                if entry_price != "未知" and entry_price is not None:
                    message += f"{i}. {symbol} (入场价: ${entry_price:.4f}{profit_loss_text})\n"
                else:
                    message += f"{i}. {symbol}\n"
            message += "\n"
        
        # 显示空单
        if short_positions:
            message += "📉 **空单持仓**\n"
            for i, (symbol, info) in enumerate(short_positions, 1):
                added_at = info.get("added_at", "未知")
                entry_price = info.get("entry_price", "未知")
                profit_loss_text = ""
                
                # 计算盈亏
                if entry_price != "未知" and entry_price is not None:
                    current_price = self.get_crypto_price(symbol)
                    if current_price:
                        profit_percent = ((entry_price - current_price) / entry_price) * 100
                        profit_loss_text = f" 盈亏: {'+' if profit_percent > 0 else ''}{profit_percent:.2f}%"
                        if profit_percent > 0:
                            profit_loss_text += " 🟢"
                        elif profit_percent < 0:
                            profit_loss_text += " 🔴"
                        else:
                            profit_loss_text += " ⚪"
                
                if entry_price != "未知" and entry_price is not None:
                    message += f"{i}. {symbol} (入场价: ${entry_price:.4f}{profit_loss_text})\n"
                else:
                    message += f"{i}. {symbol}\n"
        
        # 如果没有持仓
        if not long_positions and not short_positions:
            message += "当前没有持仓"
        
        self.send_message(chat_id, message)
    
    def handle_delcc(self, chat_id, symbol):
        """处理删除持仓命令"""
        if not symbol:
            self.send_message(chat_id, "❌ 请提供要删除的币种，格式：`delcc 币种名称`")
            return
        
        symbol = symbol.upper()
        # 自动添加USDT后缀（如果没有的话）
        if not symbol.endswith('USDT'):
            symbol = f"{symbol}USDT"
            
        if symbol in self.holdings:
            # 获取持仓信息
            holding_info = self.holdings[symbol]
            entry_price = holding_info.get("entry_price")
            position_type = holding_info.get("position_type", "long")
            
            # 获取当前价格
            current_price = self.get_crypto_price(symbol)
            
            # 计算盈亏
            profit_loss_text = ""
            if entry_price is not None and current_price:
                if position_type == "long":
                    profit_percent = ((current_price - entry_price) / entry_price) * 100
                else:  # short
                    profit_percent = ((entry_price - current_price) / entry_price) * 100
                
                profit_loss_text = f"\n入场价: ${entry_price:.4f}\n当前价: ${current_price:.4f}\n盈亏: {'+' if profit_percent > 0 else ''}{profit_percent:.2f}%"
                if profit_percent > 0:
                    profit_loss_text += " 🟢"
                elif profit_percent < 0:
                    profit_loss_text += " 🔴"
                else:
                    profit_loss_text += " ⚪"
            
            # 删除持仓
            del self.holdings[symbol]
            self.save_holdings()
            
            # 发送消息
            self.send_message(chat_id, f"✅ 已成功从持仓列表中删除 {symbol}{profit_loss_text}")
        else:
            self.send_message(chat_id, f"❌ {symbol} 不在持仓列表中")
    
    def handle_reboot(self, chat_id):
        """处理重启命令 - 仅支持Linux系统"""
        try:
            # 发送确认消息
            self.send_message(chat_id, "🔄 正在执行重启操作...\n这将停止当前运行的脚本，更新代码并重新启动")
            logger.info(f"收到重启命令，正在执行重启脚本")
            
            # 仅使用Linux版本的重启脚本
            script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'restart_all.sh')
            
            # 确保脚本有执行权限
            subprocess.run(['chmod', '+x', script_path], check=False)
            
            # 创建重启标记文件，用于重启后发送欢迎消息
            restart_flag_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.restart_flag')
            with open(restart_flag_path, 'w', encoding='utf-8') as f:
                f.write(str(chat_id))  # 保存发起重启的聊天ID
            
            # 优化的方式执行重启脚本，确保完全脱离主进程
            # 使用preexec_fn=os.setsid创建新的进程组
            # 将输出重定向到/dev/null避免任何可能的阻塞
            subprocess.Popen(
                ['nohup', 'bash', script_path, '&'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                shell=False,
                preexec_fn=os.setsid if hasattr(os, 'setsid') else None
            )
            logger.info(f"已启动Linux重启脚本: {script_path}")
            
            # 确保不会卡住，立即返回
            
            # 给用户发送最终确认消息
            final_message = "✅ 重启脚本已启动执行！\n请稍等片刻，脚本将在后台完成停止、更新和重启操作。\n重启完成后，你将收到欢迎消息。"
            self.send_message(chat_id, final_message)
            logger.info("已发送重启确认消息")
            
        except Exception as e:
            logger.error(f"执行重启脚本失败: {e}")
            self.send_message(chat_id, f"❌ 执行重启操作时出错: {str(e)}")
    
    def handle_help(self, chat_id):
        """处理帮助命令"""
        help_text = "📖 **命令帮助**\n\n"
        help_text += "`ac 币种名称 long/short [价格]` - 添加币种到持仓列表，指定多单(long)或空单(short)，价格可选，没写则使用当前价格，无需输入USDT后缀\n"
        help_text += "`sc` - 显示当前持仓列表，按多空单分组，显示实时盈亏情况\n"
        help_text += "`dc 币种名称` - 从持仓列表中删除币种，无需输入USDT后缀，会显示持仓盈亏\n"
        help_text += "`cc` - 清空所有持仓列表\n"
        help_text += "`sf` - 显示重点关注列表\n"
        help_text += "`af 币种名称` - 添加币种到重点关注列表，无需输入USDT后缀\n"
        help_text += "`df 币种名称` - 从重点关注列表中删除币种，无需输入USDT后缀\n"
        help_text += "`reboot` - 重启系统，更新代码并重新启动所有脚本\n"
        help_text += "`help` - 显示此帮助信息"
        
        self.send_message(chat_id, help_text)
    
    def handle_showfocus(self, chat_id):
        """显示重点关注列表命令"""
        try:
            # 设置重点关注列表文件路径（根据crypto_multiperiod_analysis.py中的设置）
            focus_file = "d:/crypto/自定义看盘/focus_list.json"
            focus_list = []
            
            # 尝试加载重点关注列表文件
            if os.path.exists(focus_file):
                with open(focus_file, 'r', encoding='utf-8') as f:
                    focus_list = json.load(f)
            
            # 添加默认关注币种
            default_focus = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
            all_focus = focus_list + default_focus
            # 去重
            all_focus = list(set(all_focus))
            
            if all_focus:
                message = "📋 **重点关注列表**\n\n"
                for i, symbol in enumerate(sorted(all_focus), 1):
                    # 标记默认关注的币种
                    if symbol in default_focus:
                        message += f"{i}. {symbol} ⭐(默认重点关注)\n"
                    else:
                        message += f"{i}. {symbol}\n"
                self.send_message(chat_id, message)
            else:
                self.send_message(chat_id, "📋 重点关注列表为空")
        except Exception as e:
            logger.error(f"显示重点关注列表失败: {e}")
            self.send_message(chat_id, f"❌ 显示重点关注列表时出错: {str(e)}")
    
    def handle_addfocus(self, chat_id, command_args):
        """添加币种到重点关注列表"""
        try:
            symbol = command_args.strip().upper()
            
            if not symbol:
                self.send_message(chat_id, "❌ 请提供要添加的币种，格式：`af 币种名称`")
                return
            
            # 自动添加USDT后缀（如果没有的话）
            if not symbol.endswith('USDT'):
                symbol = f"{symbol}USDT"
            
            # 设置重点关注列表文件路径
            focus_file = "d:/crypto/自定义看盘/focus_list.json"
            focus_list = []
            
            # 尝试加载现有列表
            if os.path.exists(focus_file):
                with open(focus_file, 'r', encoding='utf-8') as f:
                    focus_list = json.load(f)
            
            # 检查是否已存在
            default_focus = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
            if symbol in focus_list:
                self.send_message(chat_id, f"ℹ️ {symbol} 已在重点关注列表中")
            elif symbol in default_focus:
                self.send_message(chat_id, f"ℹ️ {symbol} 是默认重点关注币种，无需添加")
            else:
                # 添加到列表
                focus_list.append(symbol)
                # 保存到文件
                # 确保目录存在
                os.makedirs(os.path.dirname(focus_file), exist_ok=True)
                with open(focus_file, 'w', encoding='utf-8') as f:
                    json.dump(focus_list, f, ensure_ascii=False, indent=2)
                
                self.send_message(chat_id, f"✅ 已成功将 {symbol} 添加到重点关注列表")
        except Exception as e:
            logger.error(f"添加重点关注币种失败: {e}")
            self.send_message(chat_id, f"❌ 添加重点关注币种时出错: {str(e)}")
    
    def handle_delfocus(self, chat_id, command_args):
        """从重点关注列表中删除币种"""
        try:
            symbol = command_args.strip().upper()
            
            if not symbol:
                self.send_message(chat_id, "❌ 请提供要删除的币种，格式：`df 币种名称`")
                return
            
            # 自动添加USDT后缀（如果没有的话）
            if not symbol.endswith('USDT'):
                symbol = f"{symbol}USDT"
            
            # 设置重点关注列表文件路径
            focus_file = "d:/crypto/自定义看盘/focus_list.json"
            focus_list = []
            
            # 检查默认关注币种
            default_focus = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
            if symbol in default_focus:
                self.send_message(chat_id, f"❌ {symbol} 是默认重点关注币种，无法删除")
                return
            
            # 尝试加载现有列表
            if os.path.exists(focus_file):
                with open(focus_file, 'r', encoding='utf-8') as f:
                    focus_list = json.load(f)
            
            # 检查是否存在
            if symbol in focus_list:
                # 从列表中删除
                focus_list.remove(symbol)
                # 保存到文件
                with open(focus_file, 'w', encoding='utf-8') as f:
                    json.dump(focus_list, f, ensure_ascii=False, indent=2)
                
                self.send_message(chat_id, f"✅ 已成功从重点关注列表中删除 {symbol}")
            else:
                self.send_message(chat_id, f"❌ {symbol} 不在重点关注列表中")
        except Exception as e:
            logger.error(f"删除重点关注币种失败: {e}")
            self.send_message(chat_id, f"❌ 删除重点关注币种时出错: {str(e)}")
    
    def handle_clearcc(self, chat_id):
        """处理清空持仓命令"""
        if not self.holdings:
            self.send_message(chat_id, "📋 当前没有持仓，无需清空")
            return
        
        # 清空持仓
        self.holdings = {}
        self.save_holdings()
        self.send_message(chat_id, "✅ 已成功清空所有持仓列表")
    
    def process_command(self, chat_id, text):
        """处理命令"""
        parts = text.strip().split(' ', 1)
        command = parts[0].lower()
        
        if command == "ac" or command == "addcc":
            args = parts[1] if len(parts) > 1 else ""
            self.handle_addcc(chat_id, args)
        elif command == "sc" or command == "showcc":
            self.handle_showcc(chat_id)
        elif command == "dc" or command == "delcc":
            symbol = parts[1] if len(parts) > 1 else ""
            self.handle_delcc(chat_id, symbol)
        elif command == "cc" or command == "clearcc":
            self.handle_clearcc(chat_id)
        elif command == "sf" or command == "showfocus":
            self.handle_showfocus(chat_id)
        elif command == "af" or command == "addfocus":
            args = parts[1] if len(parts) > 1 else ""
            self.handle_addfocus(chat_id, args)
        elif command == "df" or command == "delfocus":
            args = parts[1] if len(parts) > 1 else ""
            self.handle_delfocus(chat_id, args)
        elif command == "reboot":
            self.handle_reboot(chat_id)
        elif command == "help":
            self.handle_help(chat_id)
    
    def run(self):
        """运行机器人"""
        logger.info("电报命令机器人已启动")
        last_update_id = None
        
        while True:
            try:
                updates = self.get_updates(last_update_id)
                
                for update in updates:
                    update_id = update.get('update_id')
                    message = update.get('message', {})
                    text = message.get('text', '')
                    chat = message.get('chat', {})
                    chat_id = chat.get('id')
                    
                    # 只有在指定的聊天群或直接消息中处理命令
                    if self.chat_id is None or str(chat_id) == str(self.chat_id):
                        if text.startswith('/'):
                            # 移除命令前的斜杠
                            command_text = text[1:]
                            logger.info(f"收到命令: {command_text} 来自聊天ID: {chat_id}")
                            self.process_command(chat_id, command_text)
                    
                    last_update_id = update_id + 1
                
                time.sleep(1)
            except Exception as e:
                logger.error(f"运行异常: {e}")
                time.sleep(5)

if __name__ == "__main__":
    # 请替换为您的实际电报机器人token和聊天ID
    TELEGRAM_BOT_TOKEN = "7708753284:AAEYV4WRHfJQR4tCb5uQ8ye-T29IEf6X9qE"
    TELEGRAM_CHAT_ID = "-4611171283"  # 可选，如果指定则只处理该聊天群的消息
    
    bot = TelegramCommandsBot(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    bot.run()