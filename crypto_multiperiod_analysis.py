import requests
from requests.adapters import HTTPAdapter, Retry
import urllib3
# 抑制urllib3的不安全请求警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
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
        # 主要API URL
        self.binance_spot_url = 'https://api.binance.com/api/v3/klines'
        self.binance_futures_url = 'https://fapi.binance.com/fapi/v1/klines'  # 合约API
        self.binance_ticker_url = 'https://fapi.binance.com/fapi/v1/ticker/24hr'  # 合约行情数据
        
        # 备用API URL，用于解决451错误（地理位置限制）
        self.binance_futures_url_backup = 'https://binance.fapi.com/fapi/v1/klines'
        self.binance_ticker_url_backup = 'https://binance.fapi.com/fapi/v1/ticker/24hr'
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
        
    def get_futures_klines(self, symbol, interval, limit=500, max_retries=3):
        """从Binance合约API获取K线数据，带重试机制和SSL错误处理"""
        params = {
            'symbol': symbol,
            'interval': interval,
            'limit': limit
        }
        
        # 设置超时和重试
        session = requests.Session()
        
        # 处理Retry参数兼容性问题
        retry_kwargs = {
            'total': max_retries,
            'backoff_factor': 0.3,  # 减少重试间隔
            'status_forcelist': [429, 451, 500, 502, 503, 504]  # 添加451状态码到重试列表
        }
        
        # 尝试使用allowed_methods（新版本），如果失败则回退
        try:
            # 测试Retry是否接受allowed_methods参数
            test_retry = Retry(**retry_kwargs, allowed_methods=["GET"])
            retry_kwargs['allowed_methods'] = ["GET"]
        except TypeError:
            # 旧版本使用method_whitelist
            retry_kwargs['method_whitelist'] = ["GET"]
        
        retry = Retry(**retry_kwargs)
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('https://', adapter)
        session.mount('http://', adapter)
        # 添加请求头和超时优化
        headers = {
            'Accept-Encoding': 'gzip, deflate',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        try:
            # 添加SSL验证设置和延长超时
            # 优先使用主URL
            current_url = self.binance_futures_url
            response = session.get(
                current_url, 
                params=params, 
                timeout=15,
                headers=headers,
                verify=False  # 禁用SSL验证以解决证书问题
            )
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
            
        except requests.exceptions.SSLError:
            print(f"获取{symbol}的{interval}合约数据时遇到SSL错误，已禁用SSL验证")
            # SSL错误时再次尝试，确保verify=False生效
            try:
                response = session.get(
                    self.binance_futures_url, 
                    params=params, 
                    timeout=15,
                    headers=headers,
                    verify=False
                )
                response.raise_for_status()
                data = response.json()
                
                df = pd.DataFrame(data, columns=[
                    'open_time', 'open', 'high', 'low', 'close', 'volume',
                    'close_time', 'quote_volume', 'trades', 'taker_base_vol', 'taker_quote_vol', 'ignore'
                ])
                
                df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
                df['close_time'] = pd.to_datetime(df['close_time'], unit='ms')
                numeric_columns = ['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trades', 'taker_base_vol', 'taker_quote_vol']
                df[numeric_columns] = df[numeric_columns].astype(float)
                
                return df
                
            except Exception as inner_e:
                print(f"SSL错误重试后仍获取失败: {inner_e}")
                return None
                
        except Exception as e:
            print(f"获取{symbol}的{interval}合约数据时出错: {e}")
            # 对于非SSL错误，尝试多次重试
            for attempt in range(1, max_retries):
                try:
                    print(f"正在重试... (尝试 {attempt+1}/{max_retries})")
                    time.sleep(1)
                    # 首次重试时使用备用URL
                    current_url = self.binance_futures_url_backup
                    print(f"遇到错误，切换到备用URL: {current_url}")
                    
                    response = session.get(
                        current_url, 
                        params=params, 
                        timeout=15,
                        headers=headers,
                        verify=False
                    )
                    response.raise_for_status()
                    data = response.json()
                    
                    df = pd.DataFrame(data, columns=[
                        'open_time', 'open', 'high', 'low', 'close', 'volume',
                        'close_time', 'quote_volume', 'trades', 'taker_base_vol', 'taker_quote_vol', 'ignore'
                    ])
                    
                    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
                    df['close_time'] = pd.to_datetime(df['close_time'], unit='ms')
                    numeric_columns = ['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trades', 'taker_base_vol', 'taker_quote_vol']
                    df[numeric_columns] = df[numeric_columns].astype(float)
                    
                    return df
                    
                except Exception as retry_e:
                    print(f"重试失败 (尝试 {attempt+1}/{max_retries}): {retry_e}")
                    
        print(f"获取{symbol}的{interval}合约数据失败，已达到最大重试次数")
        return None
        
        # 确保在函数结束时关闭session
        session.close()
    
    def get_top_usdt_futures(self, top_n=50, max_retries=3):
        """获取成交额前N名的USDT合约币种及其成交额，添加SSL错误处理"""
        # 设置超时和重试
        session = requests.Session()
        
        # 处理Retry参数兼容性问题
        retry_kwargs = {
            'total': max_retries,
            'backoff_factor': 0.5,
            'status_forcelist': [429, 451, 500, 502, 503, 504]  # 添加451状态码到重试列表
        }
        
        # 尝试使用allowed_methods（新版本），如果失败则回退
        try:
            # 测试Retry是否接受allowed_methods参数
            test_retry = Retry(**retry_kwargs, allowed_methods=["GET"])
            retry_kwargs['allowed_methods'] = ["GET"]
        except TypeError:
            # 旧版本使用method_whitelist
            retry_kwargs['method_whitelist'] = ["GET"]
        
        retry = Retry(**retry_kwargs)
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('https://', adapter)
        session.mount('http://', adapter)
        
        try:
            # 添加SSL验证设置和超时控制
            # 添加请求头
            headers = {
                'Accept-Encoding': 'gzip, deflate',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            # 优先使用主URL
            current_url = self.binance_ticker_url
            response = session.get(
                current_url, 
                timeout=15,
                headers=headers,
                verify=False  # 禁用SSL验证以解决证书问题
            )
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
            
        except requests.exceptions.SSLError:
            print("获取合约币种数据时遇到SSL错误，已禁用SSL验证")
            # SSL错误时再次尝试
            try:
                # 如果是451错误，切换到备用URL
                        if '451' in str(inner_e):
                            current_url = self.binance_ticker_url_backup
                            print(f"遇到451错误，切换到备用URL: {current_url}")
                        
                        response = session.get(
                            current_url, 
                            timeout=15,
                            headers=headers,
                            verify=False
                        )
                        response.raise_for_status()
                        tickers = response.json()
                        
                        usdt_pairs = []
                        for ticker in tickers:
                            if ticker['symbol'].endswith('USDT') and 'quoteVolume' in ticker:
                                try:
                                    quote_volume = float(ticker['quoteVolume'])
                                    usdt_pairs.append((ticker['symbol'], quote_volume))
                                except ValueError:
                                    continue
                        
                        usdt_pairs.sort(key=lambda x: x[1], reverse=True)
                        return usdt_pairs[:top_n]
                
            except Exception as inner_e:
                print(f"SSL错误重试后仍获取失败: {inner_e}")
                return []
                
        except Exception as e:
            print(f"获取合约币种数据时出错: {e}")
            # 对于非SSL错误，尝试多次重试
            for attempt in range(1, max_retries):
                try:
                    print(f"正在重试... (尝试 {attempt+1}/{max_retries})")
                    time.sleep(2)
                    # 首次重试时使用备用URL
                    current_url = self.binance_ticker_url_backup
                    print(f"遇到错误，切换到备用URL: {current_url}")
                    
                    response = session.get(
                        current_url, 
                        timeout=15,
                        headers=headers,
                        verify=False
                    )
                    response.raise_for_status()
                    tickers = response.json()
                    
                    usdt_pairs = []
                    for ticker in tickers:
                        if ticker['symbol'].endswith('USDT') and 'quoteVolume' in ticker:
                            try:
                                quote_volume = float(ticker['quoteVolume'])
                                usdt_pairs.append((ticker['symbol'], quote_volume))
                            except ValueError:
                                continue
                    
                    usdt_pairs.sort(key=lambda x: x[1], reverse=True)
                    return usdt_pairs[:top_n]
                    
                except Exception as retry_e:
                    print(f"重试失败 (尝试 {attempt+1}/{max_retries}): {retry_e}")
                    
        print("获取合约币种数据失败，已达到最大重试次数")
        return []
        
        # 确保在函数结束时关闭session
        session.close()
    
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
    
    # 删除KDJ相关函数，使用MACD交叉替代
    
    def detect_macd_cross(self, macd_line, signal_line, check_zero_line=False):
        """检测MACD金叉死叉，支持检查0轴位置
        
        Args:
            macd_line: MACD线数据
            signal_line: 信号线数据
            check_zero_line: 是否检查MACD值相对于0轴的位置
            
        Returns:
            str: 'golden_cross'(金叉), 'death_cross'(死叉) 或 None
        """
        # 添加详细日志
        print(f"检测MACD交叉 - 数据点数量: {len(macd_line)}")
        
        # 降低数据点要求，便于检测交叉
        if len(macd_line) < 2:
            print("MACD交叉检测失败：数据点不足")
            return None
        
        # 使用最近两个数据点检测交叉，更加宽松
        prev_macd, curr_macd = macd_line.iloc[-2], macd_line.iloc[-1]
        prev_signal, curr_signal = signal_line.iloc[-2], signal_line.iloc[-1]
        
        # 计算差异百分比
        prev_diff_pct = abs(prev_macd - prev_signal) / max(abs(prev_signal), 0.0001) * 100
        curr_diff_pct = abs(curr_macd - curr_signal) / max(abs(curr_signal), 0.0001) * 100
        
        print(f"MACD交叉检测 - 前值: {prev_macd:.6f}, 前信号: {prev_signal:.6f}, 差异: {prev_diff_pct:.4f}%")
        print(f"MACD交叉检测 - 当前值: {curr_macd:.6f}, 当前信号: {curr_signal:.6f}, 差异: {curr_diff_pct:.4f}%")
        
        # 检测金叉（MACD线上穿信号线）
        if prev_macd < prev_signal and curr_macd > curr_signal:
            print(f"检测到金叉信号")
            return 'golden_cross'
        
        # 检测死叉（MACD线下穿信号线）
        elif prev_macd > prev_signal and curr_macd < curr_signal:
            print(f"检测到死叉信号")
            return 'death_cross'
        
        # 添加近交叉检测，当MACD和信号线非常接近时也提示
        elif abs(curr_macd - curr_signal) / max(abs(curr_signal), 0.0001) * 100 < 0.5:
            print(f"MACD和信号线非常接近，可能即将交叉")
        
        return None
        
    def check_buy_signal(self, macd_line, signal_line, price_data=None):
        """检查买入信号（简化版本）
        
        Args:
            macd_line: MACD线数据
            signal_line: 信号线数据
            price_data: 价格数据，包含收盘价信息
            
        Returns:
            bool: 是否满足买入信号条件
        """
        try:
            # 检测MACD交叉
            macd_cross = self.detect_macd_cross(macd_line, signal_line)
            
            # 检查是否为金叉
            is_golden_cross = macd_cross == 'golden_cross'
            
            # 添加详细日志
            print(f"买入信号检查 - 金叉状态: {is_golden_cross}")
            
            # 简化逻辑：只要检测到金叉就返回True
            if is_golden_cross:
                print(f"满足简化后的买入信号条件")
                return True
            
            # 额外检查：即使没有严格金叉，如果MACD线正在上穿信号线且两者非常接近，也考虑为潜在买入信号
            if not is_golden_cross and len(macd_line) > 2:
                # 检查最近几个数据点MACD线是否在上升且接近信号线
                recent_macd_trend = (macd_line.iloc[-1] > macd_line.iloc[-2] > macd_line.iloc[-3])
                close_to_signal = abs(macd_line.iloc[-1] - signal_line.iloc[-1]) / max(abs(signal_line.iloc[-1]), 0.0001) * 100 < 0.3
                
                if recent_macd_trend and close_to_signal:
                    print(f"检测到潜在买入信号：MACD线上升趋势且接近信号线")
                    return True
            
            return False
        except Exception as e:
            print(f"买入信号检查错误: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def check_sell_signal(self, macd_line, signal_line, price_data=None):
        """检查卖出信号（简化版本）
        
        Args:
            macd_line: MACD线数据
            signal_line: 信号线数据
            price_data: 价格数据，包含收盘价信息
            
        Returns:
            bool: 是否满足卖出信号条件
        """
        try:
            # 检测MACD交叉
            macd_cross = self.detect_macd_cross(macd_line, signal_line)
            
            # 检查是否为死叉
            is_death_cross = macd_cross == 'death_cross'
            
            # 添加详细日志
            print(f"卖出信号检查 - 死叉状态: {is_death_cross}")
            
            # 简化逻辑：只要检测到死叉就返回True
            if is_death_cross:
                print(f"满足简化后的卖出信号条件")
                return True
            
            # 额外检查：即使没有严格死叉，如果MACD线正在下穿信号线且两者非常接近，也考虑为潜在卖出信号
            if not is_death_cross and len(macd_line) > 2:
                # 检查最近几个数据点MACD线是否在下降且接近信号线
                recent_macd_trend = (macd_line.iloc[-1] < macd_line.iloc[-2] < macd_line.iloc[-3])
                close_to_signal = abs(macd_line.iloc[-1] - signal_line.iloc[-1]) / max(abs(signal_line.iloc[-1]), 0.0001) * 100 < 0.3
                
                if recent_macd_trend and close_to_signal:
                    print(f"检测到潜在卖出信号：MACD线下降趋势且接近信号线")
                    return True
            
            return False
        except Exception as e:
            print(f"卖出信号检查错误: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def check_macd_golden_cross_rule(self, macd_line, signal_line):
        """
        检查MACD金叉是否符合新规则：
        1. 寻找上一个0轴以下的金叉B
        2. 寻找A和B中间MACD值的最大值C
        3. 如果A的值小于C的五分之一，则符合条件
        
        Args:
            macd_line: MACD线数据
            signal_line: 信号线数据
            
        Returns:
            bool: 是否符合新规则
        """
        # 确保有足够的数据点
        if len(macd_line) < 50:
            return False
        
        # 检查是否刚发生金叉
        current_cross = self.detect_macd_cross(macd_line, signal_line)
        if current_cross != 'golden_cross':
            return False
        
        # 金叉A的值
        macd_value_a = macd_line.iloc[-2]  # 使用交叉发生位置的值
        
        # 寻找上一个0轴以下的金叉B
        last_below_zero_golden_cross_idx = None
        
        # 从当前位置向前查找
        for i in range(len(macd_line) - 4, 0, -1):
            # 检查是否在i位置发生金叉（使用与detect_macd_cross相同的逻辑）
            cross_at_i = (macd_line.iloc[i-1] < signal_line.iloc[i-1] and 
                         macd_line.iloc[i] > signal_line.iloc[i])
            
            # 检查金叉时MACD值是否在0轴以下
            if cross_at_i and macd_line.iloc[i] <= 0:
                last_below_zero_golden_cross_idx = i
                break
        
        # 如果没有找到上一个0轴以下的金叉，返回False
        if last_below_zero_golden_cross_idx is None:
            return False
        
        # 计算A和B之间MACD线的最大值C
        macd_values_between = macd_line.iloc[last_below_zero_golden_cross_idx+1:-2]
        if len(macd_values_between) == 0:
            return False
        
        max_macd_value_c = macd_values_between.max()
        
        # 检查A的值是否小于C的五分之一
        return macd_value_a < (max_macd_value_c / 5)
    
    # KDJ交叉检测函数已删除
    
    def analyze_signal(self, main_period_data, four_x_period_data):
        """分析交易信号"""
        # 计算指标
        main_macd, main_signal, main_hist = self.calculate_macd(main_period_data)
        four_x_macd, four_x_signal, four_x_hist = self.calculate_macd(four_x_period_data)
        
        # 判断大周期MACD方向（多头：dif > dea，空头：dif < dea）
        four_x_macd_direction = 'bullish' if four_x_macd.iloc[-1] > four_x_signal.iloc[-1] else 'bearish'
        
        # 检测MACD交叉
        macd_cross = self.detect_macd_cross(main_macd, main_signal)
        
        # 生成信号
        signal = None
        if four_x_macd_direction == 'bullish' and macd_cross == 'golden_cross':
            signal = '买入信号：大周期多头+小周期MACD金叉'
        elif four_x_macd_direction == 'bearish' and macd_cross == 'death_cross':
            signal = '卖出信号：大周期空头+小周期MACD死叉'
        
        return {
            'four_x_macd_direction': four_x_macd_direction,
            'four_x_macd_value': four_x_macd.iloc[-1],
            'macd_cross': macd_cross,
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
    
    def detect_pinbar(self, data, index):
        """检测Pinbar形态（更严格的条件）"""
        if index < 1:
            return False, None
            
        candle = data.iloc[index]
        prev_candle = data.iloc[index-1]
        
        # 计算实体和影线长度
        body_size = abs(candle['close'] - candle['open'])
        high_low_range = candle['high'] - candle['low']
        
        # 实体必须很小，影线必须很长
        if body_size < high_low_range * 0.25:  # 降低实体比例要求，使条件更严格
            upper_shadow = candle['high'] - max(candle['close'], candle['open'])
            lower_shadow = min(candle['close'], candle['open']) - candle['low']
            
            # 看涨Pinbar：下影线远长于上影线
            if lower_shadow > upper_shadow * 3 and lower_shadow > body_size * 3:  # 提高倍数要求
                return True, "bullish_pinbar"
            # 看跌Pinbar：上影线远长于下影线（更严格）
            elif upper_shadow > lower_shadow * 3 and upper_shadow > body_size * 3:  # 提高倍数要求
                return True, "bearish_pinbar"
        
        return False, None
    
    def detect_engulfing(self, data, index):
        """检测吞没形态（非常严格的条件）"""
        if index < 1:
            return False, None
            
        current = data.iloc[index]
        previous = data.iloc[index-1]
        
        # 计算实体大小
        current_body = abs(current['close'] - current['open'])
        previous_body = abs(previous['close'] - previous['open'])
        
        # 只有实体足够大的K线才考虑
        if current_body < previous_body * 0.8:  # 进一步提高要求：当前实体至少是前一根的80%
            return False, None
        
        # 看涨吞没：当前阳线吞没前一根阴线
        if current['close'] > current['open'] and previous['close'] < previous['open']:
            # 收盘价高于前一根K线实体的75%位置，且开盘价低于前一根的收盘价
            prev_mid = (previous['open'] + previous['close']) / 2
            prev_75 = previous['open'] * 0.75 + previous['close'] * 0.25
            if current['close'] > prev_75 and current['open'] < previous['close']:
                # 添加额外验证：确保当前K线的高点高于前一根，低点低于前一根
                if current['high'] > previous['high'] and current['low'] < previous['low']:
                    print(f"检测到看涨吞没形态：当前实体={current_body:.4f}, 前实体={previous_body:.4f}")
                    return True, "bullish_engulfing"
        
        # 看跌吞没：当前阴线吞没前一根阳线（特别严格的条件）
        elif current['close'] < current['open'] and previous['close'] > previous['open']:
            # 收盘价低于前一根K线实体的25%位置，且开盘价高于前一根的收盘价
            prev_25 = previous['open'] * 0.25 + previous['close'] * 0.75
            # 看跌吞没需要更严格的条件，避免误判
            if current['close'] < prev_25 and current['open'] > previous['close']:
                # 添加额外验证：确保当前K线的高点高于前一根，低点低于前一根
                if current['high'] > previous['high'] and current['low'] < previous['low']:
                    # 再增加一个条件：当前K线实体必须显著大于前一根
                    if current_body > previous_body * 1.2:
                        print(f"检测到看跌吞没形态：当前实体={current_body:.4f}, 前实体={previous_body:.4f}")
                        return True, "bearish_engulfing"
        
        return False, None
    
    def detect_morning_evening_star(self, data, index):
        """检测黄昏星和黎明星形态"""
        if index < 2:
            return False, None
            
        # 获取三根K线
        first = data.iloc[index-2]
        second = data.iloc[index-1]
        third = data.iloc[index]
        
        # 黎明星（看涨反转）：第一根阴线，第二根星线，第三根阳线
        if first['close'] < first['open'] and third['close'] > third['open']:
            # 第二根K线是星线（实体小，上下影线明显）
            second_body = abs(second['close'] - second['open'])
            first_body = abs(first['close'] - first['open'])
            
            # 星线实体较小，且明显高开
            if second_body < first_body * 0.5 and second['close'] > first['close']:
                # 第三根阳线收盘价超过第一根阴线的一半
                first_mid = (first['open'] + first['close']) / 2
                if third['close'] > first_mid:
                    return True, "morning_star"
        
        # 黄昏星（看跌反转）：第一根阳线，第二根星线，第三根阴线
        elif first['close'] > first['open'] and third['close'] < third['open']:
            # 第二根K线是星线（实体小，上下影线明显）
            second_body = abs(second['close'] - second['open'])
            first_body = abs(first['close'] - first['open'])
            
            # 星线实体较小，且明显低开
            if second_body < first_body * 0.5 and second['close'] < first['close']:
                # 第三根阴线收盘价低于第一根阳线的一半
                first_mid = (first['open'] + first['close']) / 2
                if third['close'] < first_mid:
                    return True, "evening_star"
        
        return False, None
    
    def get_pattern_name(self, pattern_type):
        """获取蜡烛图形态的中文名称"""
        pattern_names = {
            'bullish_pinbar': '看涨Pinbar',
            'bearish_pinbar': '看跌Pinbar',
            'bullish_engulfing': '看涨吞没',
            'bearish_engulfing': '看跌吞没',
            'morning_star': '黎明星',
            'evening_star': '黄昏星'
        }
        return pattern_names.get(pattern_type, pattern_type)
    
    def detect_candle_patterns(self, data):
        """检测所有蜡烛图形态（使用信号K和确认K机制）
        
        信号K定义：反包吞没、黄昏星、黎明星、Pinbar
        确认K定义：阳线、阴线、十字星、Pinbar
        规则：出现信号K后马上出现确认K，才触发信号
        """
        if len(data) < 10:  # 需要足够的K线数据
            print(f"数据量不足，需要至少10根K线，当前只有{len(data)}根")
            return None
            
        last_index = len(data) - 1
        
        # 主要检测场景：倒数第二根是信号K，最后一根是确认K
        signal_index = last_index - 1
        confirmation_index = last_index
        
        if signal_index >= 2:  # 确保信号K有足够的前K线用于检测形态
            # 检测信号K - 所有可能的信号形态
            # 1. 检测Pinbar
            is_pinbar, pinbar_type = self.detect_pinbar(data, signal_index)
            # 2. 检测吞没形态
            is_engulfing, engulfing_type = self.detect_engulfing(data, signal_index)
            # 3. 检测星线形态（黎明星和黄昏星）
            is_star, star_type = self.detect_morning_evening_star(data, signal_index)
            
            # 确定信号类型
            signal_type = None
            if is_pinbar:
                signal_type = pinbar_type
            elif is_engulfing:
                signal_type = engulfing_type
            elif is_star:
                signal_type = star_type
            
            # 如果检测到信号K
            if signal_type:
                print(f"检测到信号K: {signal_type} 在索引 {signal_index}")
                
                # 对所有信号K类型进行极值检查（包括Pinbar、吞没形态、黎明星和黄昏星）
                is_extreme = self._is_recent_extreme(data, signal_index, signal_type)
                print(f"信号K极值检查 - 类型: {signal_type}, 是否极值: {is_extreme}")
                if not is_extreme:
                    print(f"信号K不是近期极值，忽略该信号")
                    return None
                
                # 检查确认K
                if confirmation_index < len(data):
                    is_confirmation = self._is_confirmation_candle(data, confirmation_index, signal_type)
                    print(f"确认K检查 - 索引: {confirmation_index}, 是否确认: {is_confirmation}")
                    if is_confirmation:
                        print(f"信号确认成功: {signal_type}")
                        return signal_type
        
        # 没有检测到任何形态
        print("未检测到符合要求的信号K+确认K组合")
        return None
    
    def _is_recent_extreme(self, data, signal_index, signal_type):
        """判断信号K的极点是否为近期极值点
        
        对于看空信号（bearish_pinbar, bearish_engulfing, evening_star）：判断信号K的高点是否为最近10根K线的最高点
        对于看多信号（bullish_pinbar, bullish_engulfing, morning_star）：判断信号K的低点是否为最近10根K线的最低点
        """
        # 计算起始索引（取信号K往前9根K线，总共10根）
        start_index = max(0, signal_index - 9)
        
        # 获取最近10根K线的子数据
        recent_data = data.iloc[start_index:signal_index+1]
        
        # 获取信号K的极点值
        signal_candle = data.iloc[signal_index]
        
        # 根据信号类型判断是否为近期极值
        if signal_type in ['bearish_pinbar', 'bearish_engulfing', 'evening_star']:
            # 看空信号：判断高点是否为最近10根K线的最高点
            signal_high = signal_candle['high']
            recent_highs = recent_data['high']
            is_highest = signal_high == recent_highs.max()
            # 增加日志
            if is_highest:
                print(f"极值检查 - 看空信号[{signal_type}] 信号K高点({signal_high:.4f})是最近10根K线的最高点")
            else:
                print(f"极值检查失败 - 看空信号[{signal_type}] 信号K高点({signal_high:.4f})不是最近10根K线的最高点，最高值为({recent_highs.max():.4f})")
            return is_highest
        
        elif signal_type in ['bullish_pinbar', 'bullish_engulfing', 'morning_star']:
            # 看多信号：判断低点是否为最近10根K线的最低点
            signal_low = signal_candle['low']
            recent_lows = recent_data['low']
            is_lowest = signal_low == recent_lows.min()
            # 增加日志
            if is_lowest:
                print(f"极值检查 - 看多信号[{signal_type}] 信号K低点({signal_low:.4f})是最近10根K线的最低点")
            else:
                print(f"极值检查失败 - 看多信号[{signal_type}] 信号K低点({signal_low:.4f})不是最近10根K线的最低点，最低值为({recent_lows.min():.4f})")
            return is_lowest
        
        # 其他情况返回False
        print(f"极值检查 - 未知信号类型[{signal_type}]，返回False")
        return False
    
    def _is_confirmation_candle(self, data, index, signal_type):
        """判断是否为确认K线
        
        确认K的定义：
        1. 单根同向pinbar
        2. 十字星
        3. 多头信号则阳线，空头信号则阴线，但不能是反向的pinbar
        """
        if index < 1 or index >= len(data):
            return False
        
        current = data.iloc[index]
        prev = data.iloc[index-1]
        
        # 检查是否为同向pinbar
        is_pinbar, pinbar_type = self.detect_pinbar(data, index)
        if is_pinbar:
            # 判断pinbar方向是否与信号方向一致
            is_bullish_signal = signal_type == 'bullish_pinbar' or signal_type == 'bullish_engulfing'
            is_bullish_pinbar = pinbar_type == 'bullish_pinbar'
            
            if (is_bullish_signal and is_bullish_pinbar) or (not is_bullish_signal and not is_bullish_pinbar):
                return True
        
        # 检查是否为十字星（实体很小，影线不考虑）
        body_size = abs(current['close'] - current['open'])
        range_size = current['high'] - current['low']
        is_doji = body_size / range_size < 0.2  # 实体小于总范围的20%
        if is_doji:
            return True
        
        # 检查是否为同向K线，但不是反向pinbar
        is_bullish_signal = signal_type == 'bullish_pinbar' or signal_type == 'bullish_engulfing'
        is_bullish_candle = current['close'] > current['open']
        
        # 判断是否为同向K线
        is_same_direction = (is_bullish_signal and is_bullish_candle) or (not is_bullish_signal and not is_bullish_candle)
        
        # 确保不是反向pinbar
        if is_pinbar:
            is_bullish_pinbar = pinbar_type == 'bullish_pinbar'
            is_opposite_direction = (is_bullish_signal and not is_bullish_pinbar) or (not is_bullish_signal and is_bullish_pinbar)
            if is_opposite_direction:
                return False
        
        return is_same_direction
    
    def analyze_single_currency(self, symbol, rank=21):
        """分析单个币种，返回分析结果"""
        try:
            print(f"开始分析币种: {symbol} (排名: {rank})")
            
            # 大周期是4h，小周期根据排名选择：前20用1h，后20用15m
            four_hour_interval = '4h'  # 大周期
            # 根据排名选择小周期：市值前20用1h，后面的用15m
            if rank <= 20:
                small_interval = '1h'
                print(f"{symbol} 排名前20，使用1小时周期分析")
            else:
                small_interval = '15m'
                print(f"{symbol} 排名20以后，使用15分钟周期分析")
            
            # 获取4小时周期数据（大周期）
            print(f"正在获取{symbol}的4小时K线数据...")
            four_hour_data = self.get_futures_klines(symbol, four_hour_interval, limit=50)
            # 获取小周期数据（根据排名选择的周期）
            print(f"正在获取{symbol}的{small_interval}K线数据...")
            small_data = self.get_futures_klines(symbol, small_interval, limit=100)
            
            if four_hour_data is None or small_data is None:
                print(f"无法获取{symbol}的完整数据，跳过")
                return symbol, None, False, None, None, None, False, False, small_interval
            
            # 降低数据量要求
            if len(four_hour_data) < 20 or len(small_data) < 20:
                print(f"{symbol}数据量不足，跳过")
                return symbol, None, False, None, None, None, False, False, small_interval
            
            # 计算大周期4小时MACD - 只需要dif值
            four_hour_macd_line, _, _ = self.calculate_macd(four_hour_data)
            
            # 新的大周期判定方式：dif > 0 多头，dif < 0 空头
            four_hour_macd_value = four_hour_macd_line.iloc[-1]
            four_hour_macd_bullish = four_hour_macd_value > 0
            macd_status = "多头" if four_hour_macd_bullish else "空头"
            
            # 添加详细日志
            print(f"{symbol} 4小时MACD(DIF)值: {four_hour_macd_value:.6f}, 状态: {macd_status}")
            
            # 检测小周期的裸K信号（根据排名选择的周期）
            candle_pattern = self.detect_candle_patterns(small_data)
            print(f"{symbol} {small_interval}K线形态: {candle_pattern}")
            
            # 增加额外的价格信息日志，帮助调试
            if len(small_data) >= 3:
                last_candle = small_data.iloc[-1]
                prev_candle = small_data.iloc[-2]
                print(f"{symbol} 最近两根{small_interval}K线:\n  倒数第二根: 开={prev_candle['open']:.4f}, 收={prev_candle['close']:.4f}, 高={prev_candle['high']:.4f}, 低={prev_candle['low']:.4f}\n  最后一根: 开={last_candle['open']:.4f}, 收={last_candle['close']:.4f}, 高={last_candle['high']:.4f}, 低={last_candle['low']:.4f}")
            
            # 基于小周期信号和大周期方向生成交易信号
            is_buy_signal = False
            is_sell_signal = False
            pattern_type = None
            
            # 买入信号：小周期多头裸K信号 + 大周期多头
            if candle_pattern in ['bullish_pinbar', 'bullish_engulfing', 'morning_star'] and four_hour_macd_bullish:
                print(f"{symbol} 检测到买入信号：小周期出现{self.get_pattern_name(candle_pattern)} + 大周期多头")
                is_buy_signal = True
                pattern_type = candle_pattern
            # 卖出信号：小周期空头裸K信号 + 大周期空头
            elif candle_pattern in ['bearish_pinbar', 'bearish_engulfing', 'evening_star'] and not four_hour_macd_bullish:
                print(f"{symbol} 检测到卖出信号：小周期出现{self.get_pattern_name(candle_pattern)} + 大周期空头")
                is_sell_signal = True
                pattern_type = candle_pattern
            # 小周期有信号但大周期方向不匹配
            elif candle_pattern in ['bullish_pinbar', 'bullish_engulfing', 'morning_star'] and not four_hour_macd_bullish:
                print(f"{symbol} 小周期出现{self.get_pattern_name(candle_pattern)}，但大周期不是多头，不生成买入信号")
            elif candle_pattern in ['bearish_pinbar', 'bearish_engulfing', 'evening_star'] and four_hour_macd_bullish:
                print(f"{symbol} 小周期出现{self.get_pattern_name(candle_pattern)}，但大周期不是空头，不生成卖出信号")
            else:
                print(f"{symbol} 未检测到明确的小周期形态信号")
            
            # 输出大周期信息
            print(f"{symbol} 大周期4小时MACD状态: {macd_status} (DIF={four_hour_macd_value:.6f})")
            
            # 添加详细的信号检查结果日志
            print(f"{symbol} 信号检查结果 - 买入信号: {is_buy_signal}, 卖出信号: {is_sell_signal}, 最终形态类型: {pattern_type}")
            
            # 分析完成，返回结果（保持原返回格式以兼容其他代码）
            return symbol, macd_status, is_buy_signal, four_hour_macd_value, pattern_type, four_hour_macd_bullish, is_buy_signal, is_sell_signal, small_interval
        except Exception as e:
            print(f"分析{symbol}时出错: {e}")
            import traceback
            traceback.print_exc()
            return symbol, None, False, None, None, None, False, False, small_interval
            
    def get_pattern_name(self, pattern_type):
        """获取K线形态的中文名称"""
        pattern_names = {
            'bullish_pinbar': '看涨Pinbar',
            'bearish_pinbar': '看跌Pinbar',
            'bullish_engulfing': '看涨吞没',
            'bearish_engulfing': '看跌吞没',
            'morning_star': '黎明星',
            'evening_star': '黄昏星'
        }
        return pattern_names.get(pattern_type, pattern_type)
    
    def check_4h_bullish_1h_goldencross(self, symbol, rank=21):
        """检查特定信号：大周期MACD状态和小周期裸K形态"""
        symbol, macd_status, is_golden_cross, four_hour_macd_value, pattern_type, four_hour_macd_bullish = self.analyze_single_currency(symbol, rank)
        return macd_status, is_golden_cross, four_hour_macd_value, pattern_type, four_hour_macd_bullish
    
    def plot_chart(self, symbol, main_interval, main_data, four_x_data, analysis_result):
        """绘制图表"""
        try:
            # 设置图表大小
            plt.figure(figsize=(15, 12))
            
            # 计算指标
            main_macd, main_signal, main_hist = self.calculate_macd(main_data)
            four_x_macd, four_x_signal, four_x_hist = self.calculate_macd(four_x_data)
            
            # 绘制价格图
            plt.subplot(3, 1, 1)
            plt.plot(main_data['open_time'], main_data['close'], label='收盘价')
            plt.title(f'{symbol} - {self.interval_map[main_interval]["name"]}价格')
            plt.grid(True)
            plt.legend()
            
            # 绘制主周期MACD
            plt.subplot(3, 1, 2)
            plt.plot(main_data['open_time'], main_macd, label='MACD')
            plt.plot(main_data['open_time'], main_signal, label='信号线')
            plt.bar(main_data['open_time'], main_hist, label='柱状图', alpha=0.5)
            plt.axhline(y=0, color='k', linestyle='-', linewidth=0.5)
            plt.title(f'MACD指标 - {self.interval_map[main_interval]["name"]}')
            plt.grid(True)
            plt.legend()
            
            # 绘制4倍周期MACD
            four_x_interval = self.interval_map[main_interval]['four_x']
            plt.subplot(3, 1, 3)
            plt.plot(four_x_data['open_time'], four_x_macd, label='MACD')
            plt.plot(four_x_data['open_time'], four_x_signal, label='信号线')
            plt.bar(four_x_data['open_time'], four_x_hist, label='柱状图', alpha=0.5)
            plt.axhline(y=0, color='k', linestyle='-', linewidth=0.5)
            plt.title(f'MACD指标 - {self.interval_map[four_x_interval]["name"]} (4倍周期)')
            plt.grid(True)
            plt.legend()
            
            # 添加分析结果文本
            text_str = f"分析结果:\n"
            text_str += f"大周期MACD方向: {'多头' if analysis_result.get('four_x_macd_direction') == 'bullish' else '空头'} (值: {analysis_result.get('four_x_macd_value', 0):.4f})\n"
            macd_cross = analysis_result.get('macd_cross')
            if macd_cross == 'golden_cross':
                text_str += "本周期MACD: 金叉\n"
            elif macd_cross == 'death_cross':
                text_str += "本周期MACD: 死叉\n"
            else:
                text_str += "本周期MACD: 无交叉\n"
            if analysis_result.get('signal'):
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
        print(f"{'币种':<10} {'周期':<10} {'大周期MACD方向':<15} {'MACD交叉状态':<15} {'交易信号':<40}")
        print("="*100)
        
        for symbol, result in analysis_results.items():
            # 检查result的类型，如果是元组则转换为字典格式
            if isinstance(result, tuple) and len(result) >= 9:
                symbol, macd_status, is_golden_cross, macd_value, macd_cross, macd_bullish, _, _, cross_interval = result
                # 构建字典格式
                result_dict = {
                    'signal': '买入信号' if is_golden_cross and macd_bullish else '卖出信号' if not is_golden_cross and not macd_bullish else None,
                    'interval': cross_interval,
                    'direction': '多头' if macd_bullish else '空头',
                    'macd_cross_status': '金叉' if macd_cross == 'golden_cross' else '死叉' if macd_cross == 'death_cross' else '无交叉'
                }
                if result_dict['signal']:
                    print(f"{symbol:<10} {result_dict['interval']:<10} {result_dict['direction']:<15} {result_dict['macd_cross_status']:<15} {result_dict['signal']:<40}")
                else:
                    print(f"{symbol:<10} {result_dict['interval']:<10} {result_dict['direction']:<15} {result_dict['macd_cross_status']:<15} {'暂无':<40}")
        print("="*100)
    
    def send_dingtalk_notification(self, message, title="加密货币分析提醒"):
        """发送钉钉通知，添加重试机制和SSL错误处理"""
        if not self.dingtalk_webhook:
            print("未配置钉钉webhook，跳过通知发送")
            return False
            
        # 创建会话并配置重试机制
        session = requests.Session()
        
        # 处理Retry参数兼容性问题
        retry_kwargs = {
            'total': 3,  # 总重试次数
            'status_forcelist': [429, 500, 502, 503, 504],  # 需要重试的HTTP状态码
            'backoff_factor': 1  # 重试间隔时间因子
        }
        
        # 尝试使用allowed_methods（新版本），如果失败则回退
        try:
            # 测试Retry是否接受allowed_methods参数
            test_retry = Retry(**retry_kwargs, allowed_methods=["POST"])
            retry_kwargs['allowed_methods'] = ["POST"]
        except TypeError:
            # 旧版本使用method_whitelist
            retry_kwargs['method_whitelist'] = ["POST"]
        
        retry_strategy = Retry(**retry_kwargs)
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        
        try:
            headers = {'Content-Type': 'application/json;charset=utf-8'}
            data = {
                "msgtype": "markdown",
                "markdown": {
                    "title": title,
                    "text": message
                }
            }
            # 添加超时设置和SSL验证选项
            response = session.post(
                self.dingtalk_webhook, 
                headers=headers, 
                json=data,
                timeout=10,  # 设置超时时间为10秒
                verify=False  # 禁用SSL验证以解决证书问题
            )
            response.raise_for_status()  # 抛出HTTP错误
            
            if response.status_code == 200 and response.json().get('errcode') == 0:
                print("钉钉通知发送成功")
                return True
            else:
                print(f"钉钉通知发送失败: {response.text}")
                return False
        except requests.exceptions.SSLError:
            print("SSL连接错误，已禁用SSL验证")
            # SSL错误时再次尝试，确保verify=False生效
            try:
                response = session.post(
                    self.dingtalk_webhook, 
                    headers=headers, 
                    json=data,
                    timeout=10,
                    verify=False
                )
                if response.status_code == 200 and response.json().get('errcode') == 0:
                    print("禁用SSL验证后钉钉通知发送成功")
                    return True
                else:
                    print(f"禁用SSL验证后钉钉通知发送失败: {response.text}")
                    return False
            except Exception as inner_e:
                print(f"禁用SSL验证后仍发送失败: {inner_e}")
                return False
        except Exception as e:
            print(f"发送钉钉通知时出错: {e}")
            return False
        finally:
            session.close()
            
    def send_telegram_notification(self, message, title="加密货币分析提醒"):
        """发送电报通知，添加重试机制和SSL错误处理"""
        if not self.telegram_bot_token or not self.telegram_chat_id:
            print("未配置电报机器人token或chat_id，跳过通知发送")
            return False
            
        # 创建会话并配置重试机制
        session = requests.Session()
        
        # 处理Retry参数兼容性问题
        retry_kwargs = {
            'total': 3,  # 总重试次数
            'status_forcelist': [429, 500, 502, 503, 504],  # 需要重试的HTTP状态码
            'backoff_factor': 1  # 重试间隔时间因子
        }
        
        # 尝试使用allowed_methods（新版本），如果失败则回退
        try:
            # 测试Retry是否接受allowed_methods参数
            test_retry = Retry(**retry_kwargs, allowed_methods=["GET"])
            retry_kwargs['allowed_methods'] = ["GET"]
        except TypeError:
            # 旧版本使用method_whitelist
            retry_kwargs['method_whitelist'] = ["GET"]
        
        retry_strategy = Retry(**retry_kwargs)
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
            
        try:
            # 为电报格式化消息，将markdown转换为电报支持的格式
            telegram_message = f"*{title}*\n\n{message.replace('# ', '').replace('## ', '')}"
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            params = {
                "chat_id": self.telegram_chat_id,
                "text": telegram_message,
                "parse_mode": "Markdown"
            }
            # 添加超时设置和SSL验证选项
            response = session.get(
                url, 
                params=params,
                timeout=10,  # 设置超时时间为10秒
                verify=False  # 禁用SSL验证以解决证书问题
            )
            response.raise_for_status()  # 抛出HTTP错误
            
            if response.status_code == 200 and response.json().get('ok'):
                print("电报通知发送成功")
                return True
            else:
                print(f"电报通知发送失败: {response.text}")
                return False
        except requests.exceptions.SSLError:
            print("SSL连接错误，已禁用SSL验证")
            # SSL错误时再次尝试，确保verify=False生效
            try:
                response = session.get(
                    url, 
                    params=params,
                    timeout=10,
                    verify=False
                )
                if response.status_code == 200 and response.json().get('ok'):
                    print("禁用SSL验证后电报通知发送成功")
                    return True
                else:
                    print(f"禁用SSL验证后电报通知发送失败: {response.text}")
                    return False
            except Exception as inner_e:
                print(f"禁用SSL验证后仍发送失败: {inner_e}")
                return False
        except Exception as e:
            print(f"发送电报通知时出错: {e}")
            return False
        finally:
            session.close()
    
    def run(self):
        """运行主程序"""
        print("欢迎使用币安合约币种筛选工具")
        print("功能：筛选USDT合约成交额前100名币种，按成交额排序，检测4小时MACD(DIF)状态（多头>0/空头<0）和15分钟裸K信号（Pinbar、吞没、黄昏星/黎明星）")
        print("每15分钟自动运行一次（在0分、15分、30分、45分），并将结果推送到电报")
        print("每5分钟检查一次持仓盈亏率")
        
        # 首次运行一次
        self.execute_filter()
        
        # 设置定时任务，每小时的0分、15分、30分、45分运行
        print("\n定时任务已设置，将在每小时的0分、15分、30分、45分自动运行...")
        schedule.every().hour.at(":00").do(self.execute_filter)
        schedule.every().hour.at(":15").do(self.execute_filter)
        schedule.every().hour.at(":30").do(self.execute_filter)
        schedule.every().hour.at(":45").do(self.execute_filter)
        
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
                        _, macd_status, is_golden_cross, _, pattern_type, macd_bullish, _, _, cross_interval = result
                        
                        # 获取持仓类型
                        position_type = position_info.get('position_type', 'long')
                        
                        # 计算MACD的多头/空头状态
                        macd_bullish_state = macd_bullish
                        macd_bearish_state = not macd_bullish
                        
                        # 检测卖出信号（看跌形态）
                        is_sell_signal = pattern_type in ['bearish_pinbar', 'bearish_engulfing', 'evening_star']
                        
                        # 统一使用4小时MACD判断和15分钟MACD交叉
                        macd_interval = '4h'  # MACD判断周期
                        
                        # 获取相应周期的MACD数据
                        macd_data = self.get_futures_klines(symbol, macd_interval, limit=50)
                        if macd_data is not None:
                            macd_line, macd_signal, _ = self.calculate_macd(macd_data)
                            current_dif = macd_line.iloc[-1] if macd_line is not None and len(macd_line) > 0 else 0
                            current_dea = macd_signal.iloc[-1] if macd_signal is not None and len(macd_signal) > 0 else 0
                        else:
                            current_dif = 0
                            current_dea = 0
                        
                        # 初始化信号变量
                        signal_type = None
                        trigger_condition = None
                        
                        # 多单持仓的止盈止损条件
                        if position_type == 'long':
                            if is_sell_signal:
                                signal_type = "🚨 止盈止损"
                                trigger_condition = f"{cross_interval} {self.get_pattern_name(pattern_type)}"
                            elif macd_bearish_state:
                                signal_type = "⚠️  趋势转空"
                                trigger_condition = f"{macd_interval} MACD空头 (DIF={current_dif:.4f}, DEA={current_dea:.4f})"
                        
                        # 空单持仓的止盈止损条件
                        elif position_type == 'short':
                            if is_golden_cross:
                                signal_type = "🚨 止盈止损"
                                trigger_condition = f"{cross_interval} MACD金叉"
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
        
        print("\n2. 开始分析每个币种的MACD信号...")
        print("   统一使用15分钟MACD交叉和4小时MACD进行分析")
        # 打印表头
        print("="*110)
        print(f"{'币种':<15} {'MACD状态':<15} {'MACD值':<12} {'MACD交叉状态':<15} {'信号':<25}")
        print("="*110)
        
        # 统计变量
        total_analyzed = 0
        bullish_count = 0  # 多头计数
        bearish_count = 0  # 空头计数
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
            # 提交所有任务，传递排名信息（i+1作为排名）
            future_to_symbol = {executor.submit(self.analyze_single_currency, symbol, i+1): symbol for i, (symbol, _) in enumerate(top_currencies)}
            
            # 处理完成的任务
            for i, future in enumerate(as_completed(future_to_symbol), 1):
                symbol = future_to_symbol[future]
                print(f"分析进度: {i}/{len(top_currencies)}", end='\r')
                
                try:
                    # 接收分析结果，包含是否满足买入/卖出信号和裸K形态
                    symbol, macd_status, is_golden_cross, four_hour_macd_value, pattern_type, four_hour_macd_bullish, is_buy_signal, is_sell_signal, cross_interval = future.result()
                    
                    if four_hour_macd_bullish is None:
                        # 无法获取数据
                        print(f"{symbol:<15} {'数据获取失败':<15} {'N/A':<12} {'N/A':<15} {'跳过':<25}")
                        continue
                    
                    with lock:
                        total_analyzed += 1
                        
                        # 更新计数逻辑以适应裸K形态信号
                        if is_golden_cross:
                            golden_cross_count += 1
                        if is_sell_signal:
                            death_cross_count += 1
                        
                        # 判断信号类型
                        signal = "不满足"
                        
                        # 使用analyze_single_currency中计算好的信号（小周期信号+大周期方向匹配）
                        if is_buy_signal:
                            pattern_name = self.get_pattern_name(pattern_type) if hasattr(self, 'get_pattern_name') else pattern_type
                            signal = f"买入信号：大周期多头+{cross_interval}{pattern_name}"
                            buy_signal_count += 1
                            buy_signal_symbols.append((symbol, macd_status, pattern_name, four_hour_macd_value, pattern_type))
                        elif is_sell_signal:
                            pattern_name = self.get_pattern_name(pattern_type) if hasattr(self, 'get_pattern_name') else pattern_type
                            signal = f"卖出信号：大周期空头+{cross_interval}{pattern_name}"
                            sell_signal_count += 1
                            sell_signal_symbols.append((symbol, macd_status, pattern_name, four_hour_macd_value, pattern_type))
                        
                        # 更新统计计数
                        if macd_status == "多头":
                            bullish_count += 1
                        else:  # 空头
                            bearish_count += 1
                    
                    # 格式化输出 - 根据裸K形态和信号判断状态
                    if is_buy_signal:
                        pattern_name = self.get_pattern_name(pattern_type) if pattern_type else "看涨信号"
                        macd_cross_status = f"看涨{pattern_name}"
                    elif is_sell_signal:
                        pattern_name = self.get_pattern_name(pattern_type) if pattern_type else "看跌信号"
                        macd_cross_status = f"看跌{pattern_name}"
                    else:
                        macd_cross_status = "无信号"
                    
                    # 存储分析结果，包含裸K形态信息
                    analysis_results[symbol] = (symbol, macd_status, is_golden_cross, four_hour_macd_value, pattern_type, four_hour_macd_bullish, is_buy_signal, is_sell_signal, cross_interval)
                    
                    # 打印详细信息 - 只有在满足买入/卖出信号时才显示交叉信息
                    if signal == "买入信号" or signal == "卖出信号":
                        print(f"{symbol:<15} {macd_status:<15} {four_hour_macd_value:<12.4f} {macd_cross_status:<15} {signal:<25}")
                    else:
                        # 不满足信号条件时，不显示交叉状态
                        print(f"{symbol:<15} {macd_status:<15} {four_hour_macd_value:<12.4f} {'-':<15} {signal:<25}")
                    
                except Exception as e:
                    print(f"处理{symbol}时出错: {e}")
        
        print("="*140)
        print(f"\n分析完成！总共分析了{total_analyzed}个币种")
        print(f"15分钟MACD多头币种: {bullish_count}个")
        print(f"15分钟MACD空头币种: {bearish_count}个")
        print(f"MACD金叉币种: {golden_cross_count}个")
        print(f"MACD死叉币种: {death_cross_count}个")
        print(f"买入信号币种: {buy_signal_count}个")
        print(f"卖出信号币种: {sell_signal_count}个")
        
        # 按分析周期分类信号列表
        # 多头信号分类
        buy_signal_1h = []  # 1小时裸K信号的买入信号
        
        sell_signal_1h = [] # 1小时裸K信号的卖出信号
        
        # 重新构建包含分析周期的信号列表
        for symbol, status, pattern_name, m_val, pattern_type in buy_signal_symbols:
            if symbol in analysis_results:
                result = analysis_results[symbol]
                if len(result) >= 9:
                    cross_interval = result[8]
                    buy_signal_1h.append((symbol, status, pattern_name, m_val, cross_interval, pattern_type))

        for symbol, status, pattern_name, m_val, pattern_type in sell_signal_symbols:
            if symbol in analysis_results:
                result = analysis_results[symbol]
                if len(result) >= 9:
                    cross_interval = result[8]
                    sell_signal_1h.append((symbol, status, pattern_name, m_val, cross_interval, pattern_type))
        
        # 对分类后的信号列表进行排序
        buy_signal_1h.sort(key=lambda x: x[3] if x[3] is not None else float('inf'))
        sell_signal_1h.sort(key=lambda x: x[3] if x[3] is not None else float('-inf'), reverse=True)
        
        # 生成钉钉通知内容
        dingtalk_content = f"### 加密货币信号提醒 - {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        
        # 输出裸K信号的买入信号（根据市值排名使用不同周期）
        if buy_signal_1h:
            print("\n⚠️  满足条件的买入信号币种：")
            print("\n裸K买入信号：")
            for symbol, status, pattern_name, _, _, _ in buy_signal_1h:
                print(f"   • {symbol} ({status}) - {pattern_name}")
            
            # 添加到钉钉通知
            dingtalk_content += "#### 🟢 裸K多头信号：\n"
            for symbol, macd_status, pattern_name, macd_value, _, _ in buy_signal_1h:
                dingtalk_content += f"- {symbol} ({macd_status}) - {pattern_name} - DIF: {macd_value:.4f}\n"
        
        # 输出裸K信号的卖出信号（根据市值排名使用不同周期）
        if sell_signal_1h:
            print("\n⚠️  满足条件的卖出信号币种：")
            print("\n裸K卖出信号：")
            for symbol, status, pattern_name, _, _, _ in sell_signal_1h:
                print(f"   • {symbol} ({status}) - {pattern_name}")
            
            # 添加到钉钉通知
            dingtalk_content += "\n#### 🔴 裸K空头信号：\n"
            for symbol, macd_status, pattern_name, macd_value, _, _ in sell_signal_1h:
                dingtalk_content += f"- {symbol} ({macd_status}) - {pattern_name} - DIF: {macd_value:.4f}\n"
        
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
        one_hour_data = self.get_futures_klines(symbol, '1h', limit=200)
        
        if four_hour_data is None or one_hour_data is None:
            print("无法获取数据，无法生成图表")
            return
        
        try:
            # 创建图表
            plt.figure(figsize=(16, 14))
            
            # 1. 4小时价格图
            plt.subplot(3, 1, 1)
            plt.plot(four_hour_data['open_time'], four_hour_data['close'], label='收盘价')
            plt.title(f'{symbol} - 4小时价格')
            plt.grid(True)
            plt.legend()
            plt.xticks(rotation=45)
            
            # 1. 合并4小时价格和MACD到同一子图
            ax1 = plt.subplot(3, 1, 1)
            ax1.plot(four_hour_data['open_time'], four_hour_data['close'], label='收盘价', color='blue')
            ax1.set_title(f'{symbol} - 4小时价格和MACD')
            ax1.set_ylabel('价格')
            ax1.grid(True)
            ax1.legend(loc='upper left')
            ax1.tick_params(axis='x', rotation=45)
            
            # 在同一子图添加MACD
            ax2 = ax1.twinx()
            four_hour_macd, four_hour_signal, four_hour_hist = self.calculate_macd(four_hour_data)
            ax2.plot(four_hour_data['open_time'], four_hour_macd, label='MACD', color='green')
            ax2.plot(four_hour_data['open_time'], four_hour_signal, label='信号线', color='red')
            ax2.bar(four_hour_data['open_time'], four_hour_hist, label='柱状图', alpha=0.3, color='purple')
            ax2.axhline(y=0, color='black', linestyle='-', linewidth=0.8)
            ax2.set_ylabel('MACD值')
            ax2.legend(loc='upper right')
            
            # 2. 合并1小时价格和MACD到同一子图
            ax3 = plt.subplot(3, 1, 2)
            ax3.plot(one_hour_data['open_time'], one_hour_data['close'], label='收盘价', color='blue')
            ax3.set_title(f'{symbol} - 1小时价格和MACD')
            ax3.set_ylabel('价格')
            ax3.grid(True)
            ax3.legend(loc='upper left')
            ax3.tick_params(axis='x', rotation=45)
            
            # 在同一子图添加MACD
            ax4 = ax3.twinx()
            one_hour_macd_line, one_hour_signal_line, one_hour_histogram = self.calculate_macd(one_hour_data)
            ax4.plot(one_hour_data['open_time'], one_hour_macd_line, label='MACD', color='green')
            ax4.plot(one_hour_data['open_time'], one_hour_signal_line, label='信号线', color='red')
            ax4.bar(one_hour_data['open_time'], one_hour_histogram, label='柱状图', alpha=0.3, color='purple')
            ax4.axhline(y=0, color='black', linestyle='-', linewidth=0.8)
            ax4.set_ylabel('MACD值')
            ax4.legend(loc='upper right')
            

            
            # 3. 最近20根1小时K线放大图
            plt.subplot(3, 1, 3)
            recent_one_hour = one_hour_data.tail(20)
            plt.plot(recent_one_hour['open_time'], recent_one_hour['close'], label='收盘价')
            plt.title(f'{symbol} - 最近20根1小时K线')
            plt.grid(True)
            plt.legend()
            plt.xticks(rotation=45)
            
            # 添加分析摘要
            macd_bullish = four_hour_macd.iloc[-1] > 0
            # 计算1小时MACD交叉
            one_hour_macd, one_hour_signal, _ = self.calculate_macd(one_hour_data)
            macd_cross = self.detect_macd_cross(one_hour_macd, one_hour_signal)
            is_golden_cross = macd_cross == 'golden_cross'
            
            text_str = f"分析摘要:\n"
            text_str += f"4小时MACD值: {four_hour_macd.iloc[-1]:.4f} ({'多头' if macd_bullish else '空头'})\n"
            text_str += f"1小时MACD交叉: {'金叉' if is_golden_cross else '死叉' if macd_cross == 'death_cross' else '无交叉'}\n"
            text_str += f"信号确认: {'满足4小时多头+1小时金叉' if macd_bullish and is_golden_cross else '不满足信号条件'}"
            
            plt.figtext(0.5, 0.01, text_str, ha='center', fontsize=12, bbox=dict(facecolor='white', alpha=0.8))
            
            plt.tight_layout(rect=[0, 0.03, 1, 1])
            plt.show()
            
        except Exception as e:
            print(f"生成图表时出错: {e}")
    
    def print_analysis_table(self, analysis_results):
        """打印分析结果表格"""
        print("\n" + "="*100)
        print(f"{'币种':<10} {'周期':<10} {'大周期MACD方向':<15} {'MACD交叉状态':<15} {'交易信号':<40}")
        print("="*100)
        
        for symbol, result in analysis_results.items():
            # 检查是否有kdj_status，如果有则转换为MACD交叉状态，否则使用macd_cross或默认值
            if 'kdj_status' in result:
                macd_status = "金叉" if "金叉" in result['kdj_status'] else "死叉" if "死叉" in result['kdj_status'] else "无交叉"
            else:
                macd_status = result.get('macd_cross', "无交叉")
                # 转换macd_cross的格式
                if macd_status == 'golden_cross':
                    macd_status = "金叉"
                elif macd_status == 'death_cross':
                    macd_status = "死叉"
            
            if result['signal']:
                print(f"{symbol:<10} {result['interval']:<10} {result['direction']:<15} {macd_status:<15} {result['signal']:<40}")
            else:
                print(f"{symbol:<10} {result['interval']:<10} {result['direction']:<15} {macd_status:<15} {'暂无':<40}")
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

def test_signal_generation():
    """测试信号生成逻辑的函数"""
    print("\n===== 开始测试信号生成逻辑 =====")
    print("当前策略：大周期4小时MACD(DIF>0多头/DIF<0空头) + 小周期1小时裸K信号")
    
    # 配置参数
    DINGTALK_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=02fcc926215099c4d0315e453e86aa6d9af934ad538de89b13f67bc3d131ee07"
    TELEGRAM_BOT_TOKEN = "7708753284:AAEYV4WRHfJQR4tCb5uQ8ye-T29IEf6X9qE"
    TELEGRAM_CHAT_ID = "-4611171283"
    
    analyzer = CryptoAnalyzer(
        dingtalk_webhook=DINGTALK_WEBHOOK,
        telegram_bot_token=TELEGRAM_BOT_TOKEN,
        telegram_chat_id=TELEGRAM_CHAT_ID
    )
    
    # 只测试几个主要币种，避免输出过多
    test_symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
    
    for symbol in test_symbols:
        print(f"\n正在测试 {symbol} 的信号生成...")
        result = analyzer.analyze_single_currency(symbol)
        if result:
            # 根据实际返回值数量解包
            if len(result) >= 9:
                symbol, macd_status, is_golden_cross, four_hour_macd_value, pattern_type, four_hour_macd_bullish, is_buy_signal, is_sell_signal, interval = result
                
                print(f"\n{symbol} 分析结果:")
                print(f"大周期状态: {macd_status} (MACD DIF值: {four_hour_macd_value:.6f})")
                print(f"小周期K线形态: {pattern_type}")
                print(f"小周期分析周期: {interval}")
                print(f"买入信号: {is_buy_signal}")
                print(f"卖出信号: {is_sell_signal}")
                
                # 添加策略逻辑说明
                if is_buy_signal:
                    print(f"信号触发原因: 大周期{macd_status} + 小周期出现看涨裸K信号")
                elif is_sell_signal:
                    print(f"信号触发原因: 大周期{macd_status} + 小周期出现看跌裸K信号")
                else:
                    print("未触发信号: 未满足大周期方向与小周期裸K信号的匹配条件")
                
                if is_buy_signal:
                    print(f"✅ {symbol} 生成了买入信号！")
                elif is_sell_signal:
                    print(f"⚠️ {symbol} 生成了卖出信号！")
                else:
                    print(f"❌ {symbol} 未生成交易信号")
    
    print("\n===== 信号生成测试完成 =====\n")

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
        elif sys.argv[1] == "--test-signals":
            # 测试信号生成逻辑
            test_signal_generation()
    else:
        # 正常运行
        analyzer = CryptoAnalyzer(
            dingtalk_webhook=DINGTALK_WEBHOOK,
            telegram_bot_token=TELEGRAM_BOT_TOKEN,
            telegram_chat_id=TELEGRAM_CHAT_ID
        )
        analyzer.run()