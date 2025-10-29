import requests
from requests.adapters import HTTPAdapter, Retry
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta

class BTCHistoryAnalyzer:
    def __init__(self):
        self.binance_futures_url = "https://fapi.binance.com/fapi/v1/klines"
    
    def get_futures_klines(self, symbol, interval, limit=500, startTime=None, max_retries=5):
        try:
            session = requests.Session()
            retries = Retry(total=max_retries, backoff_factor=1.0, status_forcelist=[429, 500, 502, 503, 504])
            adapter = HTTPAdapter(max_retries=retries)
            session.mount('https://', adapter)
            
            params = {
                'symbol': symbol,
                'interval': interval,
                'limit': limit
            }
            
            if startTime:
                params['startTime'] = startTime
            
            for attempt in range(max_retries):
                try:
                    response = session.get(self.binance_futures_url, params=params, timeout=15)
                    response.raise_for_status()
                    data = response.json()
                    
                    if isinstance(data, dict) and 'code' in data:
                        print(f"API返回错误: {data}")
                        time.sleep(2)
                        continue
                    
                    df = pd.DataFrame(data)
                    if df.empty:
                        print(f"未获取到数据")
                        return None
                    
                    df.columns = ['open_time', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_volume', 'trades', 'taker_base_volume', 'taker_quote_volume', 'ignore']
                    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
                    df.set_index('open_time', inplace=True)
                    
                    # 转换为浮点数
                    numeric_columns = ['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'taker_base_volume', 'taker_quote_volume']
                    df[numeric_columns] = df[numeric_columns].astype(float)
                    
                    return df
                except Exception as e:
                    print(f"获取数据时出错(尝试{attempt+1}/{max_retries}): {e}")
                    if attempt < max_retries - 1:
                        time.sleep(min(2 ** attempt, 10))
                    else:
                        return None
        except Exception as e:
            print(f"初始化出错: {e}")
            return None
    
    def calculate_macd(self, data, fast_period=12, slow_period=26, signal_period=9):
        """计算MACD指标"""
        # 计算EMA
        ema_fast = data['close'].ewm(span=fast_period, adjust=False).mean()
        ema_slow = data['close'].ewm(span=slow_period, adjust=False).mean()
        
        # 计算MACD线
        macd_line = ema_fast - ema_slow
        
        # 计算信号线
        signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
        
        # 计算柱状图
        macd_hist = macd_line - signal_line
        
        return macd_line, signal_line, macd_hist
    
    def detect_macd_cross(self, macd_line, signal_line):
        """检测MACD金叉死叉"""
        # 检查是否有足够的数据
        if len(macd_line) < 3:
            return None
        
        # 检查金叉（MACD线上穿信号线）
        if (macd_line.iloc[-3] < signal_line.iloc[-3] and 
            macd_line.iloc[-2] > signal_line.iloc[-2]):
            return 'golden_cross'
        
        # 检查死叉（MACD线下穿信号线）
        elif (macd_line.iloc[-3] > signal_line.iloc[-3] and 
              macd_line.iloc[-2] < signal_line.iloc[-2]):
            return 'death_cross'
        
        return None
    
    def check_buy_signal(self, macd_line, signal_line):
        """检查买入信号：1小时在0轴下出现金叉A，找到上一个金叉B，如果A的值小于B的3倍"""
        # 检查是否刚发生金叉
        current_cross = self.detect_macd_cross(macd_line, signal_line)
        if current_cross != 'golden_cross':
            return False
        
        # 检查金叉A是否在0轴以下
        if macd_line.iloc[-2] >= 0:
            return False
        
        # 金叉A的值
        value_a = abs(macd_line.iloc[-2])
        
        # 寻找上一个金叉B
        last_golden_cross_idx = None
        
        # 从当前位置向前查找
        for i in range(len(macd_line) - 4, 0, -1):
            # 检查是否在i位置发生金叉
            cross_at_i = (macd_line.iloc[i-1] < signal_line.iloc[i-1] and 
                         macd_line.iloc[i] > signal_line.iloc[i])
            
            if cross_at_i:
                last_golden_cross_idx = i
                break
        
        # 如果找不到上一个金叉B，不满足条件
        if last_golden_cross_idx is None:
            return False
        
        # 金叉B的值
        value_b = abs(macd_line.iloc[last_golden_cross_idx])
        
        # 检查A的值是否小于B的3倍
        return value_a < (value_b * 3)
    
    def check_sell_signal(self, macd_line, signal_line):
        """检查卖出信号：1小时在0轴上出现死叉A，找到上一个死叉B，如果A*3小于B"""
        # 检查是否刚发生死叉
        current_cross = self.detect_macd_cross(macd_line, signal_line)
        if current_cross != 'death_cross':
            return False
        
        # 检查死叉A是否在0轴以上
        if macd_line.iloc[-2] <= 0:
            return False
        
        # 死叉A的值
        value_a = abs(macd_line.iloc[-2])
        
        # 寻找上一个死叉B
        last_death_cross_idx = None
        
        # 从当前位置向前查找
        for i in range(len(macd_line) - 4, 0, -1):
            # 检查是否在i位置发生死叉
            cross_at_i = (macd_line.iloc[i-1] > signal_line.iloc[i-1] and 
                         macd_line.iloc[i] < signal_line.iloc[i])
            
            if cross_at_i:
                last_death_cross_idx = i
                break
        
        # 如果找不到上一个死叉B，不满足条件
        if last_death_cross_idx is None:
            return False
        
        # 死叉B的值
        value_b = abs(macd_line.iloc[last_death_cross_idx])
        
        # 检查A*3是否小于B
        return (value_a * 3) < value_b
    
    def analyze_historical_signals(self, lookback_days=30):
        """分析BTC过去一段时间的历史信号"""
        print(f"开始分析BTC过去{lookback_days}天的历史信号...")
        
        # 计算起始时间戳
        end_time = datetime.now()
        start_time = end_time - timedelta(days=lookback_days)
        start_timestamp = int(start_time.timestamp() * 1000)
        
        # 获取4小时K线数据
        print("获取4小时K线数据...")
        four_hour_data = self.get_futures_klines("BTCUSDT", "4h", limit=1000, startTime=start_timestamp)
        if four_hour_data is None:
            print("无法获取4小时K线数据")
            return
        
        # 获取1小时K线数据
        print("获取1小时K线数据...")
        hourly_data = self.get_futures_klines("BTCUSDT", "1h", limit=1000, startTime=start_timestamp)
        if hourly_data is None:
            print("无法获取1小时K线数据")
            return
        
        # 计算4小时MACD
        four_hour_macd_line, four_hour_macd_signal, _ = self.calculate_macd(four_hour_data)
        
        # 计算1小时MACD
        hourly_macd_line, hourly_macd_signal, _ = self.calculate_macd(hourly_data)
        
        # 存储发现的信号
        buy_signals = []
        sell_signals = []
        
        # 回测信号 - 模拟逐时间点分析
        print("开始回测信号...")
        
        # 确定回测的时间范围
        min_length = min(len(hourly_macd_line) - 3, len(four_hour_macd_line) - 3)
        
        # 记录每个4小时周期对应的小时索引
        four_hour_times = four_hour_macd_line.index
        
        for i in range(100, min_length):  # 从足够的数据开始
            # 获取当前时间点的子集数据
            current_hourly_macd = hourly_macd_line.iloc[:i+1]
            current_hourly_signal = hourly_macd_signal.iloc[:i+1]
            
            # 找到对应的4小时数据点
            current_time = current_hourly_macd.index[-1]
            four_hour_idx = None
            for j in range(len(four_hour_times) - 1, -1, -1):
                if four_hour_times[j] <= current_time:
                    four_hour_idx = j
                    break
            
            if four_hour_idx is None:
                continue
            
            # 获取4小时MACD方向
            four_hour_macd_bullish = four_hour_macd_line.iloc[four_hour_idx] > four_hour_macd_signal.iloc[four_hour_idx]
            
            # 检测1小时MACD交叉
            cross_result = self.detect_macd_cross(current_hourly_macd, current_hourly_signal)
            
            # 检查买入信号
            if four_hour_macd_bullish and cross_result == 'golden_cross' and self.check_buy_signal(current_hourly_macd, current_hourly_signal):
                signal_time = current_time.strftime("%Y-%m-%d %H:%M:%S")
                price = hourly_data['close'].iloc[i-1]  # 获取交叉发生时的价格
                buy_signals.append((signal_time, price))
                print(f"发现买入信号: {signal_time}, 价格: {price:.2f}")
            
            # 检查卖出信号
            elif not four_hour_macd_bullish and cross_result == 'death_cross' and self.check_sell_signal(current_hourly_macd, current_hourly_signal):
                signal_time = current_time.strftime("%Y-%m-%d %H:%M:%S")
                price = hourly_data['close'].iloc[i-1]  # 获取交叉发生时的价格
                sell_signals.append((signal_time, price))
                print(f"发现卖出信号: {signal_time}, 价格: {price:.2f}")
        
        # 打印总结
        print("\n=== 分析结果总结 ===")
        print(f"分析时间范围: {start_time.strftime('%Y-%m-%d')} 到 {end_time.strftime('%Y-%m-%d')}")
        print(f"发现买入信号数量: {len(buy_signals)}")
        print(f"发现卖出信号数量: {len(sell_signals)}")
        
        if buy_signals:
            print("\n买入信号详情:")
            for time_str, price in sorted(buy_signals):
                print(f"时间: {time_str}, 价格: {price:.2f}")
        
        if sell_signals:
            print("\n卖出信号详情:")
            for time_str, price in sorted(sell_signals):
                print(f"时间: {time_str}, 价格: {price:.2f}")
        
        return buy_signals, sell_signals

# 如果直接运行此脚本
if __name__ == "__main__":
    # 创建分析器实例
    analyzer = BTCHistoryAnalyzer()
    # 分析BTC过去30天的历史信号
    analyzer.analyze_historical_signals()