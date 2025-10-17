import requests
from requests.adapters import HTTPAdapter, Retry
import pandas as pd
import numpy as np
import time
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import heapq
import schedule
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import json
import os

# 设置中文显示
plt.rcParams['font.sans-serif'] = ['SimHei']  # 用来正常显示中文标签
plt.rcParams['axes.unicode_minus'] = False  # 用来正常显示负号

class CryptoAnalyzer:
    def __init__(self, dingtalk_webhook=None, telegram_bot_token=None, telegram_chat_id=None):
        self.binance_spot_url = 'https://api.binance.com/api/v3/klines'
        self.binance_futures_url = 'https://fapi.binance.com/fapi/v1/klines'  # 合约API
        self.binance_ticker_url = 'https://fapi.binance.com/fapi/v1/ticker/24hr'  # 合约行情数据
        self.supported_intervals = {
            '15m': 15,  # 15分钟
            '1h': 60,   # 1小时
            '4h': 240   # 4小时
        }
        self.interval_map = {
            '1h': {'name': '1小时', 'four_x': '4h'},
            '4h': {'name': '4小时', 'four_x': '1d'}
        }
        self.dingtalk_webhook = dingtalk_webhook
        self.telegram_bot_token = telegram_bot_token
        self.telegram_chat_id = telegram_chat_id
        self.holdings_file = 'crypto_holdings.json'
        # 重点关注列表，包含需要显示左侧信号的币种
        self.focus_list_file = 'focus_list.json'
        self.focus_list = self.load_focus_list()
        # 默认重点关注币种（BTC、ETH、SOL）
        self.default_focus_coins = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
        # 存储上次5分钟检查的价格
        self.last_check_prices = {}
        # 存储累计盈亏历史，用于跟踪是否达到10%阈值
        self.previous_total_pnl = 0
        # 用于跟踪正在进行的疯狂推送任务，避免重复推送
        self.active_mad_pushes = set()
    
    def load_focus_list(self):
        """加载重点关注列表"""
        try:
            if os.path.exists(self.focus_list_file):
                with open(self.focus_list_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"加载重点关注列表出错: {e}")
        # 如果文件不存在或加载失败，返回空列表
        return []
    
    def save_focus_list(self):
        """保存重点关注列表"""
        try:
            with open(self.focus_list_file, 'w', encoding='utf-8') as f:
                json.dump(self.focus_list, f, ensure_ascii=False, indent=2)
            print(f"重点关注列表已保存，共{len(self.focus_list)}个币种")
        except Exception as e:
            print(f"保存重点关注列表出错: {e}")
        
    def get_futures_klines(self, symbol, interval, limit=500, max_retries=2):
        """从Binance合约API获取K线数据，带重试机制"""
        params = {
            'symbol': symbol,
            'interval': interval,
            'limit': limit
        }
        
        # 设置超时和重试
        session = requests.Session()
        retry = Retry(total=max_retries, backoff_factor=0.3)  # 减少重试间隔
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('https://', adapter)
        # 添加请求头和超时优化
        headers = {'Accept-Encoding': 'gzip, deflate'}
        
        for attempt in range(max_retries):
            try:
                response = session.get(self.binance_futures_url, params=params, timeout=10)
                response.raise_for_status()
                data = response.json()
                
                # 格式化数据为DataFrame
                df = pd.DataFrame(data, columns=[
                    'open_time', 'open', 'high', 'low', 'close', 'volume',
                    'close_time', 'quote_volume', 'trades', 'taker_base_vol', 'taker_quote_vol', 'ignore'
                ])
                
                # 转换数据类型
                df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
                df['close_time'] = pd.to_datetime(df['close_time'], unit='ms')
                numeric_columns = ['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trades', 'taker_base_vol', 'taker_quote_vol']
                df[numeric_columns] = df[numeric_columns].astype(float)
                
                return df
            except Exception as e:
                print(f"获取{symbol}的{interval}合约数据时出错 (尝试 {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    print("正在重试...")
                    time.sleep(1)
        
        print(f"获取{symbol}的{interval}合约数据失败，已达到最大重试次数")
        return None
    
    def get_top_usdt_futures(self, top_n=50, max_retries=3):
        """获取成交额前N名的USDT合约币种及其成交额"""
        # 设置超时和重试
        session = requests.Session()
        retry = Retry(total=max_retries, backoff_factor=0.5)
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('https://', adapter)
        
        for attempt in range(max_retries):
            try:
                response = session.get(self.binance_ticker_url, timeout=15)
                response.raise_for_status()
                tickers = response.json()
                
                # 筛选USDT合约币种并保存成交额
                usdt_pairs = []
                for ticker in tickers:
                    if ticker['symbol'].endswith('USDT') and 'quoteVolume' in ticker:
                        try:
                            quote_volume = float(ticker['quoteVolume'])
                            usdt_pairs.append((ticker['symbol'], quote_volume))  # (符号, 成交额)
                        except ValueError:
                            continue
                
                # 按成交额降序排序并取前N名
                usdt_pairs.sort(key=lambda x: x[1], reverse=True)
                
                return usdt_pairs[:top_n]
                
            except Exception as e:
                print(f"获取合约币种数据时出错 (尝试 {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    print("正在重试...")
                    time.sleep(2)
        
        print("获取合约币种数据失败，已达到最大重试次数")
        return []
    
    def calculate_macd(self, data, fast_period=12, slow_period=26, signal_period=9):
        """计算MACD指标"""
        # 计算指数移动平均线
        ema_fast = data['close'].ewm(span=fast_period, adjust=False).mean()
        ema_slow = data['close'].ewm(span=slow_period, adjust=False).mean()
        
        # 计算MACD线
        macd_line = ema_fast - ema_slow
        
        # 计算信号线
        signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
        
        # 计算柱状图
        histogram = macd_line - signal_line
        
        return macd_line, signal_line, histogram
    
    def calculate_kdj(self, data, n=9, m1=3, m2=3):
        """计算KDJ指标"""
        # 计算RSV
        low_n = data['low'].rolling(window=n, min_periods=1).min()
        high_n = data['high'].rolling(window=n, min_periods=1).max()
        rsv = (data['close'] - low_n) / (high_n - low_n) * 100
        
        # 计算K、D、J线
        k = rsv.ewm(com=m1-1, adjust=False).mean()
        d = k.ewm(com=m2-1, adjust=False).mean()
        j = 3 * k - 2 * d
        
        return k, d, j
    
    def detect_kdj_cross(self, k_series, d_series):
        """检测KDJ金叉死叉，精确识别上一个小时的金叉/死叉，金叉在50以下，死叉在50以上"""
        # 检查是否有足够的数据
        if len(k_series) < 3:  # 需要至少3个数据点来确认交叉发生在上一个完整小时
            return None
        
        # 检查金叉（K线上穿D线）- 确保交叉发生在上一个完整小时且KDJ值<50
        # 即倒数第二个K线完成了金叉动作
        if (k_series.iloc[-3] < d_series.iloc[-3] and 
            k_series.iloc[-2] > d_series.iloc[-2] and
            k_series.iloc[-2] < 50):  # 金叉必须在50以下
            return 'golden_cross'
        
        # 检查死叉（K线下穿D线）- 确保交叉发生在上一个完整小时且KDJ值>50
        elif (k_series.iloc[-3] > d_series.iloc[-3] and 
              k_series.iloc[-2] < d_series.iloc[-2] and
              k_series.iloc[-2] > 50):  # 死叉必须在50以上
            return 'death_cross'
        
        return None
    
    def analyze_signal(self, main_period_data, four_x_period_data):
        """分析交易信号"""
        # 计算指标
        main_k, main_d, main_j = self.calculate_kdj(main_period_data)
        main_macd, main_signal, main_hist = self.calculate_macd(main_period_data)
        four_x_macd, four_x_signal, four_x_hist = self.calculate_macd(four_x_period_data)
        
        # 判断大周期MACD方向（多头：dif > dea，空头：dif < dea）
        four_x_macd_direction = 'bullish' if four_x_macd.iloc[-1] > four_x_signal.iloc[-1] else 'bearish'
        
        # 检测KDJ交叉
        kdj_cross = self.detect_kdj_cross(main_k, main_d)
        
        # 生成信号
        signal = None
        if four_x_macd_direction == 'bullish' and kdj_cross == 'golden_cross':
            signal = '买入信号：大周期多头+小周期KDJ金叉'
        elif four_x_macd_direction == 'bearish' and kdj_cross == 'death_cross':
            signal = '卖出信号：大周期空头+小周期KDJ死叉'
        
        return {
            'four_x_macd_direction': four_x_macd_direction,
            'four_x_macd_value': four_x_macd.iloc[-1],
            'kdj_cross': kdj_cross,
            'main_k_last': main_k.iloc[-1],
            'main_d_last': main_d.iloc[-1],
            'signal': signal
        }
    
    def calculate_7day_growth(self, symbol):
        """计算币种最近7天的涨幅百分比"""
        try:
            # 获取1天K线数据，至少需要7+1天的数据来计算7天涨幅
            daily_data = self.get_futures_klines(symbol, '1d', limit=8)
            if daily_data is None or len(daily_data) < 8:
                return 0.0
            
            # 计算7天前的收盘价和当前收盘价
            seven_days_ago_close = daily_data['close'].iloc[-8]
            current_close = daily_data['close'].iloc[-1]
            
            # 计算涨幅百分比
            growth_rate = ((current_close - seven_days_ago_close) / seven_days_ago_close) * 100
            return growth_rate
        except Exception as e:
            print(f"计算{symbol}7天涨幅时出错: {e}")
            return 0.0
    
    def analyze_single_currency(self, symbol):
        """分析单个币种，返回分析结果"""
        try:
            # 计算最近7天涨幅
            seven_day_growth = self.calculate_7day_growth(symbol)
            
            # 根据7天涨幅动态选择周期
            # 如果最近7天涨幅大于30%，则使用15分钟KDJ和1小时MACD
            if seven_day_growth > 30:
                macd_interval = '1h'  # MACD判断周期改为1小时
                kdj_interval = '15m'  # KDJ金叉周期改为15分钟
                print(f"{symbol} 7天涨幅{seven_day_growth:.2f}% > 30%，使用15分钟KDJ和1小时MACD")
            else:
                # 否则使用原方法：1小时KDJ和4小时MACD
                macd_interval = '4h'
                kdj_interval = '1h'
            
            # 获取相应周期的数据
            macd_data = self.get_futures_klines(symbol, macd_interval, limit=50)
            kdj_data = self.get_futures_klines(symbol, kdj_interval, limit=50)
            
            if macd_data is None or kdj_data is None:
                return symbol, None, None, None, None, None, None, None, None
            
            # 计算MACD
            macd_line, macd_signal, macd_hist = self.calculate_macd(macd_data)
            
            # 确定MACD状态（多头左侧/右侧、空头左侧/右侧）
            current_dif = macd_line.iloc[-1]
            current_dea = macd_signal.iloc[-1]
            
            if current_dif > current_dea:
                if current_dif > 0:
                    macd_status = "多头右侧"
                else:
                    macd_status = "多头左侧"
            else:
                if current_dif < 0:
                    macd_status = "空头右侧"
                else:
                    macd_status = "空头左侧"
            
            # 计算KDJ
            kdj_k, kdj_d, kdj_j = self.calculate_kdj(kdj_data)
            kdj_cross = self.detect_kdj_cross(kdj_k, kdj_d)
            is_golden_cross = kdj_cross == 'golden_cross'
            
            # 如果检测到金叉，额外验证一下确保K线形态
            if is_golden_cross:
                # 打印额外信息用于调试
                if len(kdj_k) > 3 and len(kdj_d) > 3:
                    print(f"  {symbol}检测到可能的金叉: K[-3]={kdj_k.iloc[-3]:.2f}, D[-3]={kdj_d.iloc[-3]:.2f}, "
                          f"K[-2]={kdj_k.iloc[-2]:.2f}, D[-2]={kdj_d.iloc[-2]:.2f}")
            
            # 返回详细信息，添加KDJ值和使用的KDJ周期
            k_value = kdj_k.iloc[-2] if len(kdj_k) > 1 else None
            d_value = kdj_d.iloc[-2] if len(kdj_d) > 1 else None
            # 返回MACD值、状态等信息，添加使用的KDJ周期
            return symbol, macd_status, is_golden_cross, macd_line.iloc[-1], kdj_cross, current_dif > current_dea, k_value, d_value, kdj_interval
        except Exception as e:
            print(f"分析{symbol}时出错: {e}")
            return symbol, None, None, None, None, None, None, None
    
    def check_4h_bullish_1h_goldencross(self, symbol):
        """检查特定信号：4小时MACD状态（多头左侧/右侧、空头左侧/右侧）和1小时KDJ金叉/死叉"""
        symbol, macd_status, is_golden_cross, four_hour_macd_value, kdj_cross, four_hour_macd_bullish = self.analyze_single_currency(symbol)
        return macd_status, is_golden_cross, four_hour_macd_value, kdj_cross, four_hour_macd_bullish
    
    def plot_chart(self, symbol, main_interval, main_data, four_x_data, analysis_result):
        """绘制图表"""
        try:
            # 设置图表大小
            plt.figure(figsize=(15, 12))
            
            # 计算指标
            main_k, main_d, main_j = self.calculate_kdj(main_data)
            main_macd, main_signal, main_hist = self.calculate_macd(main_data)
            four_x_macd, four_x_signal, four_x_hist = self.calculate_macd(four_x_data)
            
            # 绘制价格图
            plt.subplot(4, 1, 1)
            plt.plot(main_data['open_time'], main_data['close'], label='收盘价')
            plt.title(f'{symbol} - {self.interval_map[main_interval]["name"]}价格')
            plt.grid(True)
            plt.legend()
            
            # 绘制主周期KDJ
            plt.subplot(4, 1, 2)
            plt.plot(main_data['open_time'], main_k, label='K线')
            plt.plot(main_data['open_time'], main_d, label='D线')
            plt.plot(main_data['open_time'], main_j, label='J线')
            plt.axhline(y=80, color='r', linestyle='--')
            plt.axhline(y=20, color='g', linestyle='--')
            plt.title(f'KDJ指标 - {self.interval_map[main_interval]["name"]}')
            plt.grid(True)
            plt.legend()
            
            # 绘制主周期MACD
            plt.subplot(4, 1, 3)
            plt.plot(main_data['open_time'], main_macd, label='MACD')
            plt.plot(main_data['open_time'], main_signal, label='信号线')
            plt.bar(main_data['open_time'], main_hist, label='柱状图', alpha=0.5)
            plt.axhline(y=0, color='k', linestyle='-', linewidth=0.5)
            plt.title(f'MACD指标 - {self.interval_map[main_interval]["name"]}')
            plt.grid(True)
            plt.legend()
            
            # 绘制4倍周期MACD
            four_x_interval = self.interval_map[main_interval]['four_x']
            plt.subplot(4, 1, 4)
            plt.plot(four_x_data['open_time'], four_x_macd, label='MACD')
            plt.plot(four_x_data['open_time'], four_x_signal, label='信号线')
            plt.bar(four_x_data['open_time'], four_x_hist, label='柱状图', alpha=0.5)
            plt.axhline(y=0, color='k', linestyle='-', linewidth=0.5)
            plt.title(f'MACD指标 - {self.interval_map[four_x_interval]["name"]} (4倍周期)')
            plt.grid(True)
            plt.legend()
            
            # 添加分析结果文本
            text_str = f"分析结果:\n"
            text_str += f"大周期MACD方向: {'多头' if analysis_result['four_x_macd_direction'] == 'bullish' else '空头'} (值: {analysis_result['four_x_macd_value']:.4f})\n"
            if analysis_result['kdj_cross'] == 'golden_cross':
                text_str += "本周期KDJ: 金叉\n"
            elif analysis_result['kdj_cross'] == 'death_cross':
                text_str += "本周期KDJ: 死叉\n"
            else:
                text_str += f"本周期KDJ: K={analysis_result['main_k_last']:.2f}, D={analysis_result['main_d_last']:.2f}\n"
            if analysis_result['signal']:
                text_str += f"交易信号: {analysis_result['signal']}"
            else:
                text_str += "交易信号: 暂无"
            
            plt.figtext(0.02, 0.02, text_str, fontsize=12, bbox=dict(facecolor='white', alpha=0.5))
            
            plt.tight_layout()
            plt.subplots_adjust(bottom=0.1)
            plt.show()
        except Exception as e:
            print(f"绘制图表时出错: {e}")
    
    def print_analysis_table(self, analysis_results):
        """打印分析结果表格"""
        print("\n" + "="*100)
        print(f"{'币种':<10} {'周期':<10} {'大周期MACD方向':<15} {'本周期KDJ状态':<15} {'交易信号':<40}")
        print("="*100)
        
        for symbol, result in analysis_results.items():
            if result['signal']:
                print(f"{symbol:<10} {result['interval']:<10} {result['direction']:<15} {result['kdj_status']:<15} {result['signal']:<40}")
            else:
                print(f"{symbol:<10} {result['interval']:<10} {result['direction']:<15} {result['kdj_status']:<15} {'暂无':<40}")
        print("="*100)
    
    def send_dingtalk_notification(self, message, title="加密货币分析提醒"):
        """发送钉钉通知"""
        if not self.dingtalk_webhook:
            print("未配置钉钉webhook，跳过通知发送")
            return False
            
        try:
            headers = {'Content-Type': 'application/json;charset=utf-8'}
            data = {
                "msgtype": "markdown",
                "markdown": {
                    "title": title,
                    "text": message
                }
            }
            response = requests.post(self.dingtalk_webhook, headers=headers, json=data)
            if response.status_code == 200 and response.json().get('errcode') == 0:
                print("钉钉通知发送成功")
                return True
            else:
                print(f"钉钉通知发送失败: {response.text}")
                return False
        except Exception as e:
            print(f"发送钉钉通知时出错: {e}")
            return False
            
    def send_telegram_notification(self, message, title="加密货币分析提醒"):
        """发送电报通知"""
        if not self.telegram_bot_token or not self.telegram_chat_id:
            print("未配置电报机器人token或chat_id，跳过通知发送")
            return False
            
        try:
            # 为电报格式化消息，将markdown转换为电报支持的格式
            telegram_message = f"*{title}*\n\n{message.replace('# ', '').replace('## ', '')}"
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            params = {
                "chat_id": self.telegram_chat_id,
                "text": telegram_message,
                "parse_mode": "Markdown"
            }
            response = requests.get(url, params=params)
            if response.status_code == 200 and response.json().get('ok'):
                print("电报通知发送成功")
                return True
            else:
                print(f"电报通知发送失败: {response.text}")
                return False
        except Exception as e:
            print(f"发送电报通知时出错: {e}")
            return False
    
    def run(self):
        """运行主程序"""
        print("欢迎使用币安合约币种筛选工具")
        print("功能：筛选USDT合约成交额前100名币种，按成交额排序，检测4小时MACD状态（多头左侧/右侧、空头左侧/右侧）和1小时KDJ信号")
        print("每小时整点自动运行一次，并将结果推送到电报")
        print("每5分钟检查一次持仓盈亏率")
        
        # 首次运行一次
        self.execute_filter()
        
        # 设置定时任务，每小时整点运行
        print("\n定时任务已设置，将在每小时整点自动运行...")
        schedule.every().hour.at(":00").do(self.execute_filter)
        
        # 设置每5分钟检查一次持仓盈亏
        print("定时任务已设置，将每5分钟检查一次持仓盈亏...")
        schedule.every(5).minutes.do(self.check_holdings_pnl_every_5min)
        
        try:
            while True:
                schedule.run_pending()
                time.sleep(10)  # 每10秒检查一次，提高响应速度
        except KeyboardInterrupt:
            print("\n程序已手动停止")
    
    def load_holdings(self):
        """加载持仓数据"""
        try:
            if os.path.exists(self.holdings_file):
                with open(self.holdings_file, 'r', encoding='utf-8') as f:
                    holdings = json.load(f)
                # 移除过滤逻辑，加载所有持仓数据，与telegram机器人保持一致
                return holdings
            else:
                print("持仓数据文件不存在")
                return {}
        except Exception as e:
            print(f"加载持仓数据出错: {e}")
            return {}
    
    def check_holdings_pnl_every_5min(self):
        """每5分钟检查持仓盈亏率"""
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始5分钟持仓盈亏检测...")
        print(f"当前跟踪的上次价格记录: {self.last_check_prices}")
        
        holdings = self.load_holdings()
        print(f"加载到的持仓数据: {holdings.keys() if holdings else '空'}")
        
        if not holdings:
            print("当前没有持仓数据，跳过检测")
            return
        
        # 初始化统计变量
        total_investment = 0
        total_value = 0
        has_alerts = False
        alert_content = f"### 持仓盈亏提醒 - {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        
        # 检查每个持仓的盈亏情况
        for symbol, position_info in holdings.items():
            try:
                print(f"\n处理持仓币种: {symbol}")
                # 获取当前价格
                current_price = self.get_crypto_price(symbol)
                print(f"{symbol} 获取到的价格: {current_price}")
                
                if current_price and 'entry_price' in position_info:
                    entry_price = position_info['entry_price']
                    position_type = position_info.get('position_type', 'long')
                    
                    # 计算盈亏率
                    if position_type == 'long':
                        pnl_rate = ((current_price - entry_price) / entry_price) * 100
                    else:  # short
                        pnl_rate = ((entry_price - current_price) / entry_price) * 100
                    
                    print(f"{symbol} 入场价: {entry_price}, 持仓类型: {position_type}, 当前盈亏率: {pnl_rate:.2f}%")
                    
                    # 计算5分钟涨幅（相对于上次检查）
                    five_min_growth = None
                    if symbol in self.last_check_prices:
                        last_price = self.last_check_prices[symbol]
                        five_min_growth = ((current_price - last_price) / last_price) * 100
                        print(f"{symbol} 上次价格: {last_price}, 当前价格: {current_price}, 5分钟涨幅: {five_min_growth:.2f}%")
                        # 添加详细日志，记录价格变化幅度
                        if abs(five_min_growth) >= 2:
                            print(f"⚠️ {symbol} 价格波动接近触发阈值: {five_min_growth:.2f}%")
                    else:
                        # 首次检查，存储当前价格作为基准
                        print(f"{symbol} 首次检查，存储基准价格: {current_price}")
                    
                    # 更新上次检查的价格
                    self.last_check_prices[symbol] = current_price
                    print(f"已更新{symbol}的基准价格")
                    
                    # 假设每个持仓的价值为1（简化计算），实际应用中可以根据持仓数量调整
                    investment = 1  # 可以替换为实际投资金额
                    value = investment * (1 + pnl_rate/100)
                    total_investment += investment
                    total_value += value
                    
                    # 检查5分钟涨幅是否超过3%，如果超过则启动疯狂推送
                    if five_min_growth is not None and abs(five_min_growth) >= 3:
                        direction = "上涨" if five_min_growth > 0 else "下跌"
                        has_alerts = True
                        alert_content += f"\n#### 🚨 {symbol} 5分钟内{direction}超过3%\n"
                        alert_content += f"- 当前价: {current_price:.4f}, 5分钟涨幅: {five_min_growth:.2f}%\n"
                        print(f"⚠️  检测到{symbol} 5分钟内{direction}超过3%: {five_min_growth:.2f}%")
                        print(f"准备启动疯狂推送，检查是否已在推送中: {symbol in self.active_mad_pushes}")
                        
                        # 检查该币种是否已经在推送中，避免重复推送
                        if symbol not in self.active_mad_pushes:
                            # 启动疯狂推送线程
                            print(f"启动{symbol}的疯狂推送线程")
                            threading.Thread(target=self.mad_push_to_dingtalk,
                                            args=(symbol, current_price, five_min_growth, position_type),
                                            daemon=True).start()
                    # 检查5分钟涨幅是否超过5%
                    elif five_min_growth is not None and abs(five_min_growth) >= 5:
                        has_alerts = True
                        direction = "上涨" if five_min_growth > 0 else "下跌"
                        alert_content += f"\n#### 🚨 {symbol} 5分钟内{direction}超过5%\n"
                        alert_content += f"- 当前价: {current_price:.4f}, 5分钟涨幅: {five_min_growth:.2f}%\n"
                        print(f"⚠️  检测到{symbol} 5分钟内{direction}超过5%: {five_min_growth:.2f}%")
                elif current_price is None:
                    print(f"⚠️  无法获取{symbol}的价格，无法计算5分钟涨幅")
                else:
                    print(f"{symbol} 持仓信息中缺少入场价格")
            except Exception as e:
                print(f"计算{symbol}盈亏时出错: {e}")
                import traceback
                traceback.print_exc()
        
        # 计算总体盈亏率
        if total_investment > 0:
            total_pnl_rate = ((total_value - total_investment) / total_investment) * 100
            print(f"📊 当前总体持仓盈亏率: {total_pnl_rate:.2f}%")
            
            # 检查总体盈亏率是否大于10%
            if total_pnl_rate >= 10 and self.previous_total_pnl < 10:
                has_alerts = True
                alert_content += f"\n#### 🟢 总体持仓盈亏率超过10%\n"
                alert_content += f"- 当前总体盈亏率: {total_pnl_rate:.2f}%\n"
                print(f"🎉 总体持仓盈亏率超过10%: {total_pnl_rate:.2f}%")
            
            # 更新历史盈亏率
            self.previous_total_pnl = total_pnl_rate
        
        # 如果有警报，发送通知
        if has_alerts:
            try:
                # 只发送到电报
                print("准备发送持仓盈亏提醒到电报")
                self.send_telegram_notification(alert_content, "持仓盈亏提醒")
                print("持仓盈亏提醒已发送到电报")
            except Exception as e:
                print(f"发送持仓盈亏提醒失败: {e}")
        else:
            print("本次检查未发现需要提醒的情况")
        
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 5分钟持仓盈亏检测完成")
    
    def get_crypto_price(self, symbol):
        """获取加密货币当前价格"""
        try:
            # 使用与telegram_commands_bot相同的API获取价格
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return float(data.get('price', 0))
            else:
                print(f"获取{symbol}价格失败: HTTP {response.status_code}")
                return None
        except Exception as e:
            print(f"获取{symbol}价格时出错: {e}")
            return None
            
    def mad_push_to_dingtalk(self, symbol, current_price, five_min_growth, position_type):
        """5分钟异动疯狂推送功能
        
        当持仓币出现5分钟异动3%以上时，3秒推送一个消息，连续推送2分钟
        """
        # 将币种添加到活跃推送集合中
        self.active_mad_pushes.add(symbol)
        print(f"🔔 启动{symbol}的5分钟异动疯狂推送功能")
        start_time = time.time()
        direction = "上涨" if five_min_growth > 0 else "下跌"
        profit_direction = "盈利" if (position_type == 'long' and five_min_growth > 0) or (position_type == 'short' and five_min_growth < 0) else "亏损"
        push_count = 0
        
        # 获取持仓信息，用于计算盈亏率
        holdings = self.load_holdings()
        entry_price = None
        if symbol in holdings:
            entry_price = holdings[symbol].get('entry_price')
        
        # 推送2分钟，每3秒推送一次
        while time.time() - start_time < 120:  # 120秒 = 2分钟
            try:
                # 获取最新价格（每次推送都获取最新价格）
                latest_price = self.get_crypto_price(symbol)
                if latest_price is None:
                    latest_price = current_price
                
                # 计算最新的5分钟涨幅（基于最新价格和初始价格）
                initial_price = current_price / (1 + five_min_growth/100)
                latest_growth = ((latest_price - initial_price) / initial_price) * 100
                
                # 计算盈亏率
                pnl_rate_text = "-"
                if entry_price is not None:
                    if position_type == 'long':
                        pnl_rate = ((latest_price - entry_price) / entry_price) * 100
                    else:  # short
                        pnl_rate = ((entry_price - latest_price) / entry_price) * 100
                    pnl_rate_text = f"{pnl_rate:.2f}%"
                    # 添加颜色标记
                    if pnl_rate > 0:
                        pnl_rate_text += " 🟢"
                    elif pnl_rate < 0:
                        pnl_rate_text += " 🔴"
                    else:
                        pnl_rate_text += " ⚪"
                
                # 构建推送消息，确保包含关键词"提醒"和"价格"
                push_content = f"""
### ⚠️⚠️⚠️ 提醒 - 紧急价格异动 ⚠️⚠️⚠️

#### 提醒: {symbol} 5分钟内{direction}超过3%

- **当前价格**: {latest_price:.4f}
- **价格5分钟涨幅**: {latest_growth:.2f}%
- **持仓方向**: {position_type}
- **盈亏状态**: {profit_direction}
- **当前盈亏率**: {pnl_rate_text}
- **推送次数**: {push_count + 1}
- **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🔔 提醒: 价格波动较大，请及时关注！
                """
                
                # 发送钉钉通知，标题也包含关键词
                self.send_dingtalk_notification(push_content, title=f"提醒: {symbol} 加密货币")
                push_count += 1
                
                # 等待3秒后再次推送
                time.sleep(3)
                
            except Exception as e:
                print(f"疯狂推送过程中出错: {e}")
                # 即使出错也继续推送，确保功能持续运行
                time.sleep(3)
        
        # 推送结束后，从活跃推送集合中移除
        if symbol in self.active_mad_pushes:
            self.active_mad_pushes.remove(symbol)
        
        print(f"✅ {symbol}的5分钟异动疯狂推送结束，共推送{push_count}条消息")
    
    def test_mad_push(self, symbol="BTCUSDT", growth_rate=3.5):
        """测试5分钟异动疯狂推送功能
        
        Args:
            symbol: 测试的币种，默认为BTCUSDT
            growth_rate: 测试的涨幅，默认为3.5%
        """
        print(f"📝 开始测试{symbol}的5分钟异动疯狂推送功能")
        
        # 获取当前价格
        current_price = self.get_crypto_price(symbol)
        if current_price is None:
            current_price = 40000.0  # 默认价格
            print(f"无法获取{symbol}的当前价格，使用默认价格: {current_price}")
        
        # 模拟持仓信息
        position_type = "long"  # 模拟做多
        
        # 启动测试推送（为了测试方便，只推送3次，每次间隔2秒）
        print(f"模拟{symbol} 5分钟上涨{growth_rate}%")
        
        # 使用较短的推送时间进行测试
        original_mad_push = self.mad_push_to_dingtalk
        
        def test_push_wrapper(*args, **kwargs):
            # 临时替换推送逻辑，只推送3次
            print("🔔 启动测试模式的5分钟异动推送")
            start_time = time.time()
            symbol = args[0]
            current_price = args[1]
            five_min_growth = args[2]
            position_type = args[3]
            direction = "上涨" if five_min_growth > 0 else "下跌"
            profit_direction = "盈利" if (position_type == 'long' and five_min_growth > 0) or (position_type == 'short' and five_min_growth < 0) else "亏损"
            push_count = 0
            
            # 获取持仓信息，用于计算盈亏率
            holdings = self.load_holdings()
            entry_price = None
            if symbol in holdings:
                entry_price = holdings[symbol].get('entry_price')
            
            # 只推送3次，每次间隔2秒
            while push_count < 3 and time.time() - start_time < 10:
                try:
                    # 计算盈亏率
                    pnl_rate_text = "-"
                    if entry_price is not None:
                        if position_type == 'long':
                            pnl_rate = ((current_price - entry_price) / entry_price) * 100
                        else:  # short
                            pnl_rate = ((entry_price - current_price) / entry_price) * 100
                        pnl_rate_text = f"{pnl_rate:.2f}%"
                        # 添加颜色标记
                        if pnl_rate > 0:
                            pnl_rate_text += " 🟢"
                        elif pnl_rate < 0:
                            pnl_rate_text += " 🔴"
                        else:
                            pnl_rate_text += " ⚪"
                    
                    # 构建推送消息，确保包含关键词"提醒"和"价格"
                    push_content = f"""
### ⚠️⚠️⚠️ 提醒 - 测试价格异动 ⚠️⚠️⚠️

#### 提醒: {symbol} 5分钟内{direction}超过3%

- **当前价格**: {current_price:.4f}
- **价格5分钟涨幅**: {five_min_growth:.2f}%
- **持仓方向**: {position_type}
- **盈亏状态**: {profit_direction}
- **当前盈亏率**: {pnl_rate_text}
- **推送次数**: {push_count + 1}
- **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🔔 提醒: 这是测试消息，价格波动较大，请及时关注！
                    """
                    
                    # 发送钉钉通知，标题也包含关键词
                    success = self.send_dingtalk_notification(push_content, title=f"提醒: [测试] {symbol} 价格异动")
                    print(f"测试推送 #{push_count + 1}: {'成功' if success else '失败'}")
                    push_count += 1
                    
                    # 等待2秒后再次推送
                    time.sleep(2)
                    
                except Exception as e:
                    print(f"测试推送过程中出错: {e}")
                    time.sleep(2)
            
            print(f"✅ 测试推送结束，共推送{push_count}条消息")
        
        # 临时替换方法
        self.mad_push_to_dingtalk = test_push_wrapper
        
        try:
            # 启动测试推送线程
            test_thread = threading.Thread(target=self.mad_push_to_dingtalk,
                                        args=(symbol, current_price, growth_rate, position_type),
                                        daemon=True)
            test_thread.start()
            test_thread.join(10)  # 等待测试完成
            print("📝 5分钟异动疯狂推送功能测试完成")
        finally:
            # 恢复原始方法
            self.mad_push_to_dingtalk = original_mad_push
            
    def check_holdings_signals(self, analysis_results):
        """根据持仓情况检查止盈止损信号"""
        holdings = self.load_holdings()
        
        if not holdings:
            print("当前没有持仓数据")
            return []
        
        holdings_signals = []
        
        for symbol, position_info in holdings.items():
            try:
                # 检查该币种是否在分析结果中
                if symbol in analysis_results:
                    result = analysis_results[symbol]
                    if result is not None and len(result) >= 9:
                        _, macd_status, is_golden_cross, _, kdj_cross, macd_bullish, _, _, kdj_interval = result
                        
                        # 获取持仓类型
                        position_type = position_info.get('position_type', 'long')
                        
                        # 计算MACD的多头/空头状态
                        macd_bullish_state = macd_bullish
                        macd_bearish_state = not macd_bullish
                        
                        # 检测KDJ死叉
                        is_death_cross = kdj_cross == 'death_cross'
                        
                        # 根据7天涨幅动态选择周期
                        seven_day_growth = self.calculate_7day_growth(symbol)
                        if seven_day_growth > 30:
                            macd_interval = '1h'  # MACD判断周期改为1小时
                            # 从分析结果中获取KDJ周期
                            if kdj_interval == '15m':
                                print(f"持仓检查 {symbol} 7天涨幅{seven_day_growth:.2f}% > 30%，使用15分钟KDJ和1小时MACD")
                        else:
                            # 否则使用原方法：1小时KDJ和4小时MACD
                            macd_interval = '4h'
                            # 从分析结果中获取KDJ周期
                            if kdj_interval == '1h':
                                print(f"持仓检查 {symbol} 7天涨幅{seven_day_growth:.2f}% ≤ 30%，使用1小时KDJ和4小时MACD")
                        
                        # 获取相应周期的MACD数据
                        macd_data = self.get_futures_klines(symbol, macd_interval, limit=50)
                        if macd_data is not None:
                            macd_line, macd_signal, _ = self.calculate_macd(macd_data)
                            current_dif = macd_line.iloc[-1] if macd_line is not None and len(macd_line) > 0 else 0
                            current_dea = macd_signal.iloc[-1] if macd_signal is not None and len(macd_signal) > 0 else 0
                        else:
                            current_dif = 0
                            current_dea = 0
                        
                        # 获取相应周期的KDJ数据
                        kdj_data = self.get_futures_klines(symbol, kdj_interval, limit=50)
                        if kdj_data is not None:
                            kdj_k, kdj_d, _ = self.calculate_kdj(kdj_data)
                        else:
                            kdj_k = None
                            kdj_d = None
                        
                        # 初始化信号变量
                        signal_type = None
                        trigger_condition = None
                        
                        # 多单持仓的止盈止损条件
                        if position_type == 'long' and kdj_k is not None and len(kdj_k) > 2:
                            if is_death_cross:
                                signal_type = "🚨 止盈止损"
                                trigger_condition = f"{kdj_interval} KDJ死叉 (K={kdj_k.iloc[-2]:.2f})"
                            elif macd_bearish_state:
                                signal_type = "⚠️  趋势转空"
                                trigger_condition = f"{macd_interval} MACD空头 (DIF={current_dif:.4f}, DEA={current_dea:.4f})"
                        
                        # 空单持仓的止盈止损条件
                        elif position_type == 'short' and kdj_k is not None and len(kdj_k) > 2:
                            if is_golden_cross:
                                signal_type = "🚨 止盈止损"
                                trigger_condition = f"{kdj_interval} KDJ金叉 (K={kdj_k.iloc[-2]:.2f})"
                            elif macd_bullish_state:
                                signal_type = "⚠️  趋势转多"
                                trigger_condition = f"{macd_interval} MACD多头 (DIF={current_dif:.4f}, DEA={current_dea:.4f})"
                        
                        if signal_type and trigger_condition:
                            holdings_signals.append({
                                'symbol': symbol,
                                'position_type': position_type,
                                'signal_type': signal_type,
                                'trigger_condition': trigger_condition
                            })
            except Exception as e:
                print(f"处理{symbol}持仓信号时出错: {e}")
        
        return holdings_signals
    

    
    def execute_filter(self):
        """执行筛选分析"""
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始筛选分析...")
        print("1. 获取成交额前50名的USDT合约币种...")
        
        # 初始化止盈止损信号列表
        stop_signals = []
        # 初始化分析结果字典
        analysis_results = {}
        
        # 获取成交额前100名的USDT合约币种及其成交额
        top_currencies = self.get_top_usdt_futures(top_n=100)
        
        if not top_currencies:
            print("错误：无法获取合约币种数据")
            return
        
        print(f"成功获取{len(top_currencies)}个合约币种")
        print("前10名币种及其成交额：")
        for i, (symbol, volume) in enumerate(top_currencies[:10], 1):
            print(f"   {i}. {symbol}: {volume:.2f} USDT")
        
        print("\n2. 开始分析每个币种的MACD和KDJ信号...")
        print("   注意：最近7天涨幅>30%的币种将使用15分钟KDJ和1小时MACD")
        print("   其他币种将使用1小时KDJ和4小时MACD")
        # 打印表头
        print("="*110)
        print(f"{'币种':<15} {'MACD状态':<15} {'MACD值':<12} {'KDJ状态':<15} {'信号':<25}")
        print("="*110)
        
        # 统计变量
        total_analyzed = 0
        bullish_left_count = 0  # 多头左侧计数
        bullish_right_count = 0  # 多头右侧计数
        bearish_left_count = 0  # 空头左侧计数
        bearish_right_count = 0  # 空头右侧计数
        golden_cross_count = 0
        death_cross_count = 0
        buy_signal_count = 0
        sell_signal_count = 0
        buy_signal_symbols = []
        sell_signal_symbols = []
        
        # 使用线程池并发分析多个币种
        max_workers = min(10, len(top_currencies))  # 限制最大线程数
        print(f"使用{max_workers}个线程并发分析...")
        
        # 创建线程安全的计数器
        lock = threading.Lock()
        
        # 使用线程池处理
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务
            future_to_symbol = {executor.submit(self.analyze_single_currency, symbol): symbol for symbol, _ in top_currencies}
            
            # 处理完成的任务
            for i, future in enumerate(as_completed(future_to_symbol), 1):
                symbol = future_to_symbol[future]
                print(f"分析进度: {i}/{len(top_currencies)}", end='\r')
                
                try:
                    # 更新变量接收以匹配新增的KDJ值和KDJ周期返回
                    symbol, macd_status, is_golden_cross, four_hour_macd_value, kdj_cross, four_hour_macd_bullish, k_value, d_value, kdj_interval = future.result()
                    
                    if four_hour_macd_bullish is None:
                        # 无法获取数据
                        print(f"{symbol:<15} {'数据获取失败':<15} {'N/A':<12} {'N/A':<15} {'跳过':<25}")
                        continue
                    
                    with lock:
                        total_analyzed += 1
                        
                        # 判断是否为主流币种或在重点关注列表中
                        # 重点关注列表中的币种和默认的BTC、ETH、SOL都能保留左侧信号
                        is_focus_coin = symbol in self.focus_list or symbol in self.default_focus_coins
                        
                        # 预处理左侧信号
                        original_macd_status = macd_status
                        if macd_status in ["多头左侧", "空头左侧"] and not is_focus_coin:
                            # 不在重点关注列表中的币种，左侧信号转为右侧
                            if macd_status == "多头左侧":
                                macd_status = "多头右侧"
                            else:
                                macd_status = "空头右侧"
                        
                        is_death_cross = kdj_cross == 'death_cross'
                        if is_golden_cross:
                            golden_cross_count += 1
                        elif is_death_cross:
                            death_cross_count += 1
                        
                        # 获取MACD指标值
                        current_dif = four_hour_macd_value
                        # 判断MACD是否为多头状态
                        macd_bullish = current_dif > 0
                        
                        # 更新统计（在判断信号后更新）
                        
                        # 判断信号类型
                        signal = "不满足"
                        # 判断是否为主流币种或在重点关注列表中
                        is_focus_coin = symbol in self.focus_list or symbol in self.default_focus_coins
                        # 只有右侧信号或重点关注列表中的左侧信号才能作为买入/卖出信号
                        if macd_bullish and is_golden_cross and (macd_status == "多头右侧" or (macd_status == "多头左侧" and is_focus_coin)):
                            signal = "买入信号"
                            buy_signal_count += 1
                            # 使用从方法返回的KDJ值
                            kdj_values = f"K={k_value:.2f}" if k_value is not None else "N/A"
                            # 存储原始K值用于排序
                            buy_signal_symbols.append((symbol, macd_status, kdj_values, k_value))
                        elif not macd_bullish and is_death_cross and (macd_status == "空头右侧" or (macd_status == "空头左侧" and is_focus_coin)):
                            signal = "卖出信号"
                            sell_signal_count += 1
                            # 使用从方法返回的KDJ值 - 死叉时也只输出K值
                            kdj_values = f"K={k_value:.2f}" if k_value is not None else "N/A"
                            # 存储原始K值用于排序
                            sell_signal_symbols.append((symbol, macd_status, kdj_values, k_value))
                        
                        # 更新统计计数
                        if macd_status == "多头左侧":
                            bullish_left_count += 1
                        elif macd_status == "多头右侧":
                            bullish_right_count += 1
                        elif macd_status == "空头左侧":
                            bearish_left_count += 1
                        else:  # 空头右侧
                            bearish_right_count += 1
                    
                    # 格式化输出
                    kdj_status = "金叉" if kdj_cross == 'golden_cross' else "死叉" if kdj_cross == 'death_cross' else "无交叉"
                    
                    # 存储分析结果，包含KDJ周期信息
                    analysis_results[symbol] = (symbol, macd_status, is_golden_cross, four_hour_macd_value, kdj_cross, macd_status in ['多头左侧', '多头右侧'], k_value, d_value, kdj_interval)
                    
                    # 打印详细信息
                    print(f"{symbol:<15} {macd_status:<15} {four_hour_macd_value:<12.4f} {kdj_status:<15} {signal:<25}")
                    
                except Exception as e:
                    print(f"处理{symbol}时出错: {e}")
        
        print("="*140)
        print(f"\n分析完成！总共分析了{total_analyzed}个币种")
        print(f"4小时MACD多头左侧币种: {bullish_left_count}个")
        print(f"4小时MACD多头右侧币种: {bullish_right_count}个")
        print(f"4小时MACD空头左侧币种: {bearish_left_count}个")
        print(f"4小时MACD空头右侧币种: {bearish_right_count}个")
        print(f"1小时KDJ金叉币种: {golden_cross_count}个")
        print(f"1小时KDJ死叉币种: {death_cross_count}个")
        print(f"买入信号币种: {buy_signal_count}个")
        print(f"卖出信号币种: {sell_signal_count}个")
        
        # 按KDJ周期分类信号列表
        # 多头信号分类
        buy_signal_15m = []  # 15分钟KDJ的买入信号
        buy_signal_1h = []   # 1小时KDJ的买入信号
        # 空头信号分类
        sell_signal_15m = [] # 15分钟KDJ的卖出信号
        sell_signal_1h = []  # 1小时KDJ的卖出信号
        
        # 重新构建包含KDJ周期的信号列表
        for symbol, _, _, _ in buy_signal_symbols:
            if symbol in analysis_results:
                result = analysis_results[symbol]
                if len(result) >= 9:
                    kdj_interval = result[8]
                    for i, (s, status, kdj, k_val) in enumerate(buy_signal_symbols):
                        if s == symbol:
                            if kdj_interval == '15m':
                                buy_signal_15m.append((symbol, status, kdj, k_val, kdj_interval))
                            else:
                                buy_signal_1h.append((symbol, status, kdj, k_val, kdj_interval))
                            break
        
        for symbol, _, _, _ in sell_signal_symbols:
            if symbol in analysis_results:
                result = analysis_results[symbol]
                if len(result) >= 9:
                    kdj_interval = result[8]
                    for i, (s, status, kdj, k_val) in enumerate(sell_signal_symbols):
                        if s == symbol:
                            if kdj_interval == '15m':
                                sell_signal_15m.append((symbol, status, kdj, k_val, kdj_interval))
                            else:
                                sell_signal_1h.append((symbol, status, kdj, k_val, kdj_interval))
                            break
        
        # 对分类后的信号列表进行排序
        buy_signal_15m.sort(key=lambda x: x[3] if x[3] is not None else float('inf'))
        buy_signal_1h.sort(key=lambda x: x[3] if x[3] is not None else float('inf'))
        sell_signal_15m.sort(key=lambda x: x[3] if x[3] is not None else float('-inf'), reverse=True)
        sell_signal_1h.sort(key=lambda x: x[3] if x[3] is not None else float('-inf'), reverse=True)
        
        # 生成钉钉通知内容
        dingtalk_content = f"### 加密货币信号提醒 - {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        
        # 分别输出15分钟和1小时KDJ的买入信号
        if buy_signal_15m or buy_signal_1h:
            print("\n⚠️  满足条件的买入信号币种：")
            
            if buy_signal_15m:
                print("\n15分钟KDJ买入信号：")
                for symbol, status, kdj, _, _ in buy_signal_15m:
                    print(f"   • {symbol} ({status}) - {kdj}")
                
                # 添加到钉钉通知
                dingtalk_content += "#### 🟢 15分钟KDJ多头信号：\n"
                for symbol, macd_status, kdj, _, _ in buy_signal_15m:
                    dingtalk_content += f"- {symbol} ({macd_status}) - KDJ: {kdj}\n"
            
            if buy_signal_1h:
                print("\n1小时KDJ买入信号：")
                for symbol, status, kdj, _, _ in buy_signal_1h:
                    print(f"   • {symbol} ({status}) - {kdj}")
                
                # 添加到钉钉通知
                dingtalk_content += "\n#### 🟢 1小时KDJ多头信号：\n"
                for symbol, macd_status, kdj, _, _ in buy_signal_1h:
                    dingtalk_content += f"- {symbol} ({macd_status}) - KDJ: {kdj}\n"
        
        # 分别输出15分钟和1小时KDJ的卖出信号
        if sell_signal_15m or sell_signal_1h:
            print("\n⚠️  满足条件的卖出信号币种：")
            
            if sell_signal_15m:
                print("\n15分钟KDJ卖出信号：")
                for symbol, status, kdj, _, _ in sell_signal_15m:
                    print(f"   • {symbol} ({status}) - {kdj}")
                
                # 添加到钉钉通知
                dingtalk_content += "\n#### 🔴 15分钟KDJ空头信号：\n"
                for symbol, macd_status, kdj, _, _ in sell_signal_15m:
                    dingtalk_content += f"- {symbol} ({macd_status}) - KDJ: {kdj}\n"
            
            if sell_signal_1h:
                print("\n1小时KDJ卖出信号：")
                for symbol, status, kdj, _, _ in sell_signal_1h:
                    print(f"   • {symbol} ({status}) - {kdj}")
                
                # 添加到钉钉通知
                dingtalk_content += "\n#### 🔴 1小时KDJ空头信号：\n"
                for symbol, macd_status, kdj, _, _ in sell_signal_1h:
                    dingtalk_content += f"- {symbol} ({macd_status}) - KDJ: {kdj}\n"
        
        if buy_signal_symbols or sell_signal_symbols:
            pass
        
        # 检查持仓币种的止盈止损信号
        stop_signals = self.check_holdings_signals(analysis_results)
        
        # 如果有止盈止损信号，添加到通知内容
        if stop_signals:
            dingtalk_content += "\n\n#### ⚠️  持仓止盈止损提醒：\n"
            print("\n⚠️  检测到以下持仓币种的止盈止损信号：")
            
            for signal in stop_signals:
                position_text = "多单" if signal['position_type'] == 'long' else "空单"
                dingtalk_content += f"- **{signal['symbol']}** ({position_text}) - {signal['signal_type']} - {signal['trigger_condition']}\n"
                print(f"   • {signal['symbol']} ({position_text}) - {signal['signal_type']} - {signal['trigger_condition']}")
        
        # 添加持仓和盈亏率信息
        holdings = self.load_holdings()
        if holdings:
            dingtalk_content += "\n\n#### 📊 持仓概览：\n"
            print("\n📊 当前持仓概览：")
            
            for symbol, position_info in holdings.items():
                try:
                    # 获取当前价格
                    current_price = self.get_crypto_price(symbol)
                    if current_price and 'entry_price' in position_info:
                        entry_price = position_info['entry_price']
                        position_type = position_info.get('position_type', 'long')
                        
                        # 计算盈亏率
                        if position_type == 'long':
                            pnl_rate = ((current_price - entry_price) / entry_price) * 100
                        else:  # short
                            pnl_rate = ((entry_price - current_price) / entry_price) * 100
                        
                        # 确定颜色和图标
                        if pnl_rate > 0:
                            color_icon = "🟢"
                        elif pnl_rate < 0:
                            color_icon = "🔴"
                        else:
                            color_icon = "⚪"
                        
                        # 添加到通知内容
                        position_text = "多单" if position_type == 'long' else "空单"
                        dingtalk_content += f"- {color_icon} **{symbol}** ({position_text}) - 入场价: {entry_price:.4f}, 当前价: {current_price:.4f}, 盈亏: {pnl_rate:.2f}%\n"
                        print(f"   • {symbol} ({position_text}) - 入场价: {entry_price:.4f}, 当前价: {current_price:.4f}, 盈亏: {pnl_rate:.2f}%")
                except Exception as e:
                    print(f"计算{symbol}盈亏时出错: {e}")
        
        # 发送通知 - 只有在有信号时才发送
        has_signals = buy_signal_symbols or sell_signal_symbols or stop_signals
        
        if has_signals:
            # 启用钉钉通知
            print("启用钉钉通知")
            try:
                # 发送钉钉通知
                self.send_dingtalk_notification(dingtalk_content, "加密货币交易信号提醒")
            except Exception as e:
                print(f"钉钉通知发送失败: {e}")
            # 发送Telegram通知
            try:
                # 同时发送到电报群
                self.send_telegram_notification(dingtalk_content, "加密货币交易信号提醒")
            except Exception as e:
                print(f"电报通知发送失败: {e}")
        else:
            print("没有交易信号，不发送通知")
        
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 筛选分析结束")
    
    def show_detailed_chart(self, symbol):
        """显示详细图表"""
        print(f"正在生成{symbol}的详细图表...")
        
        # 获取数据
        four_hour_data = self.get_futures_klines(symbol, '4h', limit=100)
        hourly_data = self.get_futures_klines(symbol, '1h', limit=200)
        
        if four_hour_data is None or hourly_data is None:
            print("无法获取数据，无法生成图表")
            return
        
        try:
            # 创建图表
            plt.figure(figsize=(16, 14))
            
            # 1. 4小时价格图
            plt.subplot(4, 2, 1)
            plt.plot(four_hour_data['open_time'], four_hour_data['close'], label='收盘价')
            plt.title(f'{symbol} - 4小时价格')
            plt.grid(True)
            plt.legend()
            plt.xticks(rotation=45)
            
            # 2. 4小时MACD
            four_hour_macd, four_hour_signal, four_hour_hist = self.calculate_macd(four_hour_data)
            plt.subplot(4, 2, 2)
            plt.plot(four_hour_data['open_time'], four_hour_macd, label='MACD')
            plt.plot(four_hour_data['open_time'], four_hour_signal, label='信号线')
            plt.bar(four_hour_data['open_time'], four_hour_hist, label='柱状图', alpha=0.5)
            plt.axhline(y=0, color='r', linestyle='-', linewidth=1)
            plt.title(f'{symbol} - 4小时MACD')
            plt.grid(True)
            plt.legend()
            plt.xticks(rotation=45)
            
            # 3. 1小时价格图
            plt.subplot(4, 2, 3)
            plt.plot(hourly_data['open_time'], hourly_data['close'], label='收盘价')
            plt.title(f'{symbol} - 1小时价格')
            plt.grid(True)
            plt.legend()
            plt.xticks(rotation=45)
            
            # 4. 1小时KDJ
            hourly_k, hourly_d, hourly_j = self.calculate_kdj(hourly_data)
            plt.subplot(4, 2, 4)
            plt.plot(hourly_data['open_time'], hourly_k, label='K线')
            plt.plot(hourly_data['open_time'], hourly_d, label='D线')
            plt.plot(hourly_data['open_time'], hourly_j, label='J线')
            plt.axhline(y=80, color='r', linestyle='--')
            plt.axhline(y=20, color='g', linestyle='--')
            plt.title(f'{symbol} - 1小时KDJ')
            plt.grid(True)
            plt.legend()
            plt.xticks(rotation=45)
            
            # 5. 最近20根1小时K线放大图
            plt.subplot(4, 1, 3)
            recent_hourly = hourly_data.tail(20)
            plt.plot(recent_hourly['open_time'], recent_hourly['close'], label='收盘价')
            plt.title(f'{symbol} - 最近20根1小时K线')
            plt.grid(True)
            plt.legend()
            plt.xticks(rotation=45)
            
            # 6. 最近20根1小时KDJ放大图
            plt.subplot(4, 1, 4)
            recent_k = hourly_k.tail(20)
            recent_d = hourly_d.tail(20)
            recent_j = hourly_j.tail(20)
            plt.plot(recent_hourly['open_time'], recent_k, label='K线')
            plt.plot(recent_hourly['open_time'], recent_d, label='D线')
            plt.plot(recent_hourly['open_time'], recent_j, label='J线')
            plt.axhline(y=50, color='k', linestyle='-', linewidth=0.8)
            plt.title(f'{symbol} - 最近20根1小时KDJ')
            plt.grid(True)
            plt.legend()
            plt.xticks(rotation=45)
            
            # 添加分析摘要
            macd_bullish = four_hour_macd.iloc[-1] > 0
            kdj_cross = self.detect_kdj_cross(hourly_k, hourly_d)
            is_golden_cross = kdj_cross == 'golden_cross'
            
            text_str = f"分析摘要:\n"
            text_str += f"4小时MACD值: {four_hour_macd.iloc[-1]:.4f} ({'多头' if macd_bullish else '空头'})\n"
            text_str += f"1小时KDJ: K={hourly_k.iloc[-1]:.2f}, D={hourly_d.iloc[-1]:.2f} ({'金叉' if is_golden_cross else '死叉' if kdj_cross == 'death_cross' else '无交叉'})\n"
            text_str += f"信号确认: {'满足4小时多头+1小时金叉' if macd_bullish and is_golden_cross else '不满足信号条件'}"
            
            plt.figtext(0.5, 0.01, text_str, ha='center', fontsize=12, bbox=dict(facecolor='white', alpha=0.8))
            
            plt.tight_layout(rect=[0, 0.03, 1, 1])
            plt.show()
            
        except Exception as e:
            print(f"生成图表时出错: {e}")
    
    def print_analysis_table(self, analysis_results):
        """打印分析结果表格"""
        print("\n" + "="*100)
        print(f"{'币种':<10} {'周期':<10} {'大周期MACD方向':<15} {'本周期KDJ状态':<15} {'交易信号':<40}")
        print("="*100)
        
        for symbol, result in analysis_results.items():
            if result['signal']:
                print(f"{symbol:<10} {result['interval']:<10} {result['direction']:<15} {result['kdj_status']:<15} {result['signal']:<40}")
            else:
                print(f"{symbol:<10} {result['interval']:<10} {result['direction']:<15} {result['kdj_status']:<15} {'暂无':<40}")
        print("="*100)

def send_urgent_notification(symbol="BTCUSDT", message="紧急提醒"):
    """发送紧急推送通知"""
    from datetime import datetime
    import threading
    
    # 配置参数
    DINGTALK_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=02fcc926215099c4d0315e453e86aa6d9af934ad538de89b13f67bc3d131ee07"
    
    print(f"正在发送{symbol}的紧急推送...")
    
    # 创建分析器实例
    analyzer = CryptoAnalyzer(dingtalk_webhook=DINGTALK_WEBHOOK)
    
    # 直接使用mad_push_to_dingtalk方法进行紧急推送
    current_price = analyzer.get_crypto_price(symbol) or 40000.0
    five_min_growth = 5.0  # 使用较大的涨幅触发推送
    position_type = "long"
    
    # 立即发送一次推送，模拟5分钟异动推送
    try:
        # 直接调用mad_push_to_dingtalk方法，因为这个方法已经包含了正确的关键词格式
        # 为了立即触发且避免2分钟持续推送，我们临时修改mad_push_to_dingtalk方法
        original_mad_push = analyzer.mad_push_to_dingtalk
        
        def urgent_push_wrapper(*args, **kwargs):
            """临时包装器，只推送一次紧急消息"""
            symbol = args[0]
            current_price = args[1]
            five_min_growth = args[2]
            position_type = args[3]
            direction = "上涨" if five_min_growth > 0 else "下跌"
            profit_direction = "盈利" if (position_type == 'long' and five_min_growth > 0) or (position_type == 'short' and five_min_growth < 0) else "亏损"
            
            print(f"🔔 发送紧急推送: {symbol} - {message}")
            
            # 使用mad_push_to_dingtalk中的消息格式
            push_content = f"""
### ⚠️⚠️⚠️ 提醒 - 紧急价格异动 ⚠️⚠️⚠️

#### 提醒: {symbol} 紧急价格通知

- **当前价格**: {current_price:.4f}
- **价格5分钟涨幅**: {five_min_growth:.2f}%
- **持仓方向**: {position_type}
- **盈亏状态**: {profit_direction}
- **提醒原因**: {message}
- **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🔔 提醒: 价格紧急波动，请及时关注！
            """
            
            # 发送钉钉通知
            success = analyzer.send_dingtalk_notification(push_content, title=f"提醒: {symbol} 加密货币")
            
            if success:
                print(f"✅ {symbol}的紧急推送发送成功")
            else:
                print(f"❌ {symbol}的紧急推送发送失败")
            
            return success
        
        # 替换方法
        analyzer.mad_push_to_dingtalk = urgent_push_wrapper
        
        # 执行推送
        analyzer.mad_push_to_dingtalk(symbol, current_price, five_min_growth, position_type)
        
        # 恢复原始方法
        analyzer.mad_push_to_dingtalk = original_mad_push
            
    except Exception as e:
        print(f"发送紧急推送时出错: {e}")
        # 确保恢复原始方法
        analyzer.mad_push_to_dingtalk = original_mad_push

if __name__ == "__main__":
    import sys
    
    # 配置参数
    DINGTALK_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=02fcc926215099c4d0315e453e86aa6d9af934ad538de89b13f67bc3d131ee07"  # 请在此处填入您的钉钉webhook地址
    TELEGRAM_BOT_TOKEN = "7708753284:AAEYV4WRHfJQR4tCb5uQ8ye-T29IEf6X9qE"  # 请在此处填入您的电报机器人token
    TELEGRAM_CHAT_ID = "-4611171283"  # 请在此处填入您的电报群chat_id
    
    # 检查命令行参数
    if len(sys.argv) > 1:
        if sys.argv[1] == "--test-mad-push":
            # 运行测试
            print("\n=== 5分钟异动疯狂推送功能测试 ===\n")
            symbol = sys.argv[2] if len(sys.argv) > 2 else "BTCUSDT"
            growth_rate = float(sys.argv[3]) if len(sys.argv) > 3 else 3.5
            analyzer = CryptoAnalyzer(
                dingtalk_webhook=DINGTALK_WEBHOOK,
                telegram_bot_token=TELEGRAM_BOT_TOKEN,
                telegram_chat_id=TELEGRAM_CHAT_ID
            )
            analyzer.test_mad_push(symbol=symbol, growth_rate=growth_rate)
            print("\n=== 测试完成 ===")
        elif sys.argv[1] == "--urgent-push":
            # 发送紧急推送
            print("\n=== 发送紧急推送 ===\n")
            symbol = sys.argv[2] if len(sys.argv) > 2 else "BTCUSDT"
            message = " ".join(sys.argv[3:]) if len(sys.argv) > 3 else "紧急提醒"
            send_urgent_notification(symbol, message)
            print("\n=== 推送完成 ===")
    else:
        # 正常运行
        analyzer = CryptoAnalyzer(
            dingtalk_webhook=DINGTALK_WEBHOOK,
            telegram_bot_token=TELEGRAM_BOT_TOKEN,
            telegram_chat_id=TELEGRAM_CHAT_ID
        )
        analyzer.run()