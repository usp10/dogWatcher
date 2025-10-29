import pandas as pd
import numpy as np
import requests
import time
from datetime import datetime

class BTCSignalAnalyzer:
    def __init__(self):
        self.base_url = 'https://api.binance.com'
        self.headers = {'Accept': 'application/json'}
    
    def get_historical_klines(self, symbol, interval, limit=1000):
        """获取历史K线数据"""
        endpoint = f'/api/v3/klines'
        params = {
            'symbol': symbol,
            'interval': interval,
            'limit': limit
        }
        
        try:
            response = requests.get(self.base_url + endpoint, headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()
            
            columns = ['open_time', 'open', 'high', 'low', 'close', 'volume', 'close_time', 
                      'quote_volume', 'trades', 'taker_buy_base', 'taker_buy_quote', 'ignore']
            df = pd.DataFrame(data, columns=columns)
            
            # 转换时间戳为日期时间
            df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
            df['close_time'] = pd.to_datetime(df['close_time'], unit='ms')
            
            # 转换数值列为浮点数
            numeric_columns = ['open', 'high', 'low', 'close', 'volume', 'quote_volume', 
                              'taker_buy_base', 'taker_buy_quote']
            df[numeric_columns] = df[numeric_columns].astype(float)
            
            return df
        except Exception as e:
            print(f"获取{symbol} {interval}数据失败: {e}")
            return None
    
    def calculate_macd(self, data, fast_period=12, slow_period=26, signal_period=9):
        """计算MACD指标"""
        close_prices = data['close']
        
        # 计算EMA
        ema_fast = close_prices.ewm(span=fast_period, adjust=False).mean()
        ema_slow = close_prices.ewm(span=slow_period, adjust=False).mean()
        
        # 计算DIF（MACD线）
        macd_line = ema_fast - ema_slow
        
        # 计算DEA（信号线）
        signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
        
        # 计算柱状图
        hist = macd_line - signal_line
        
        return macd_line, signal_line, hist
    
    def detect_macd_cross(self, macd_line, signal_line):
        """检测MACD交叉信号"""
        # 检查是否有足够的数据点
        if len(macd_line) < 2:
            return None
        
        # 检查交叉
        if macd_line.iloc[-2] < signal_line.iloc[-2] and macd_line.iloc[-1] > signal_line.iloc[-1]:
            return 'golden_cross'  # 金叉
        elif macd_line.iloc[-2] > signal_line.iloc[-2] and macd_line.iloc[-1] < signal_line.iloc[-1]:
            return 'death_cross'  # 死叉
        else:
            return None
    
    def find_recent_signals(self, symbol="BTCUSDT", large_interval="4h", small_interval="15m", lookback_days=7):
        """查找BTC最近的信号"""
        print(f"开始分析{symbol}的历史信号...")
        
        # 获取大周期数据
        large_klines = self.get_historical_klines(symbol, large_interval)
        if large_klines is None or len(large_klines) < 3:
            print("无法获取足够的大周期数据")
            return
        
        # 获取小周期数据
        small_klines = self.get_historical_klines(symbol, small_interval)
        if small_klines is None or len(small_klines) < 3:
            print("无法获取足够的小周期数据")
            return
        
        # 计算MACD指标
        large_macd_line, large_macd_signal, _ = self.calculate_macd(large_klines)
        small_macd_line, small_macd_signal, _ = self.calculate_macd(small_klines)
        
        # 检测信号
        signals = []
        
        # 分析最近的历史数据，查找信号
        for i in range(min(100, len(small_klines) - 3), len(small_klines) - 1):
            # 获取当前点和前几个点的MACD值
            current_small_macd = small_macd_line.iloc[i]
            prev_small_macd = small_macd_line.iloc[i-1]
            prev_prev_small_macd = small_macd_line.iloc[i-2]
            
            # 获取对应的大周期MACD状态
            # 找到对应的大周期索引
            small_time = small_klines['open_time'].iloc[i]
            large_index = large_klines[large_klines['open_time'] <= small_time].last_valid_index()
            
            if large_index is not None and large_index >= 0:
                current_large_dif = large_macd_line.iloc[large_index]
                current_large_dea = large_macd_signal.iloc[large_index]
                
                # 判断大周期趋势
                if current_large_dif > current_large_dea:
                    large_trend = "多头"
                else:
                    large_trend = "空头"
                
                # 检测MACD转折信号
                # 空趋势下的信号
                if current_large_dif < 0 and current_small_macd < 0 and prev_small_macd < 0 and prev_prev_small_macd < 0:
                    if prev_small_macd > current_small_macd and prev_small_macd > prev_prev_small_macd:
                        signal_time = small_klines['open_time'].iloc[i]
                        signals.append({
                            'time': signal_time,
                            'type': '空趋势MACD转折信号',
                            'large_trend': large_trend,
                            'small_macd_values': {
                                'c': prev_prev_small_macd,
                                'b': prev_small_macd,
                                'a': current_small_macd
                            }
                        })
                
                # 多趋势下的信号
                elif current_large_dif > 0 and current_small_macd > 0 and prev_small_macd > 0 and prev_prev_small_macd > 0:
                    if prev_small_macd > current_small_macd and prev_small_macd > prev_prev_small_macd:
                        signal_time = small_klines['open_time'].iloc[i]
                        signals.append({
                            'time': signal_time,
                            'type': '多趋势MACD转折信号',
                            'large_trend': large_trend,
                            'small_macd_values': {
                                'c': prev_prev_small_macd,
                                'b': prev_small_macd,
                                'a': current_small_macd
                            }
                        })
                
                # 检测MACD交叉信号
                if i + 1 < len(small_macd_line):
                    macd_cross = None
                    if small_macd_line.iloc[i] < small_macd_signal.iloc[i] and small_macd_line.iloc[i+1] > small_macd_signal.iloc[i+1]:
                        macd_cross = 'golden_cross'
                    elif small_macd_line.iloc[i] > small_macd_signal.iloc[i] and small_macd_line.iloc[i+1] < small_macd_signal.iloc[i+1]:
                        macd_cross = 'death_cross'
                    
                    if macd_cross:
                        signal_time = small_klines['open_time'].iloc[i+1]
                        signals.append({
                            'time': signal_time,
                            'type': 'MACD金叉' if macd_cross == 'golden_cross' else 'MACD死叉',
                            'large_trend': large_trend,
                            'price': small_klines['close'].iloc[i+1]
                        })
        
        # 按时间排序
        signals.sort(key=lambda x: x['time'], reverse=True)
        
        # 输出最近的信号
        if signals:
            print(f"\n找到{len(signals)}个历史信号:")
            print("-" * 80)
            for i, signal in enumerate(signals[:10], 1):  # 只显示最近10个信号
                print(f"信号 #{i}:")
                print(f"  时间: {signal['time']}")
                print(f"  类型: {signal['type']}")
                print(f"  大周期趋势: {signal['large_trend']}")
                if 'small_macd_values' in signal:
                    values = signal['small_macd_values']
                    print(f"  MACD值: c={values['c']:.4f}, b={values['b']:.4f}(最大), a={values['a']:.4f}")
                if 'price' in signal:
                    print(f"  价格: {signal['price']:.2f}")
                print("-" * 80)
            
            # 显示上一次信号
            latest_signal = signals[0]
            print(f"\nBTC上一次信号:")
            print(f"  时间: {latest_signal['time']}")
            print(f"  类型: {latest_signal['type']}")
            print(f"  大周期趋势: {latest_signal['large_trend']}")
            if 'small_macd_values' in latest_signal:
                values = latest_signal['small_macd_values']
                print(f"  MACD值: c={values['c']:.4f}, b={values['b']:.4f}(最大), a={values['a']:.4f}")
            if 'price' in latest_signal:
                print(f"  价格: {latest_signal['price']:.2f}")
        else:
            print("\n未找到任何历史信号")
    
    def detect_top_divergence(self, price_data, macd_data, lookback_periods=60, debug=False):
        """检测顶背离（看跌背离）
        
        顶背离定义：价格创新高，但MACD未能创新高，表明上涨动能减弱
        
        Args:
            price_data: 价格数据（DataFrame的high列）
            macd_data: MACD数据（MACD线）
            lookback_periods: 回溯周期数
            debug: 是否输出调试信息
            
        Returns:
            dict: 包含背离信息的字典，如果没有背离则返回None
        """
        if len(price_data) < lookback_periods or len(macd_data) < lookback_periods:
            if debug:
                print(f"  调试: 数据不足，价格数据长度={len(price_data)}，MACD数据长度={len(macd_data)}")
            return None
        
        # 获取最近的价格数据
        recent_prices = price_data.iloc[-lookback_periods:].values
        recent_macd = macd_data.iloc[-lookback_periods:].values
        recent_times = price_data.index[-lookback_periods:]
        
        # 查找价格的两个高点
        price_highs = []
        for i in range(1, len(recent_prices) - 1):
            if recent_prices[i] > recent_prices[i-1] and recent_prices[i] > recent_prices[i+1]:
                price_highs.append((i, recent_prices[i], recent_times[i]))
        
        if len(price_highs) < 2:
            if debug:
                print(f"  调试: 未找到足够的价格高点，仅找到{len(price_highs)}个高点")
                # 输出最高价信息
                max_price_idx = recent_prices.argmax()
                print(f"  调试: 最近{lookback_periods}根K线最高价: {recent_prices[max_price_idx]:.2f} (位置: {max_price_idx})")
            return None
        
        # 按时间顺序取最近的两个高点
        recent_high_idx, recent_high_price, recent_high_time = price_highs[-1]
        prev_high_idx, prev_high_price, prev_high_time = price_highs[-2]
        
        if debug:
            print(f"  调试: 最近高点: {recent_high_price:.2f} (时间: {recent_high_time})")
            print(f"  调试: 前高点: {prev_high_price:.2f} (时间: {prev_high_time})")
        
        # 检查价格是否创新高
        if recent_high_price <= prev_high_price:
            if debug:
                print(f"  调试: 价格未创新高，最近高点 {recent_high_price:.2f} <= 前高点 {prev_high_price:.2f}")
            return None
        
        # 获取对应位置的MACD值
        recent_high_macd = recent_macd[recent_high_idx]
        prev_high_macd = recent_macd[prev_high_idx]
        
        if debug:
            print(f"  调试: 最近高点MACD: {recent_high_macd:.4f}")
            print(f"  调试: 前高点MACD: {prev_high_macd:.4f}")
        
        # 检查MACD是否没有创新高（形成背离）
        if recent_high_macd < prev_high_macd:
            # 计算背离强度（价格涨幅与MACD跌幅的比值）
            price_change = (recent_high_price - prev_high_price) / prev_high_price * 100
            macd_change = (recent_high_macd - prev_high_macd) / abs(prev_high_macd) * 100 if prev_high_macd != 0 else 0
            
            if debug:
                print(f"  调试: 发现顶背离！价格上涨{price_change:.2f}%，MACD下跌{macd_change:.2f}%")
            
            return {
                'type': 'top_divergence',
                'signal': '看跌背离',
                'recent_high_time': recent_high_time,
                'recent_high_price': recent_high_price,
                'prev_high_time': prev_high_time,
                'prev_high_price': prev_high_price,
                'recent_high_macd': recent_high_macd,
                'prev_high_macd': prev_high_macd,
                'price_change_percent': price_change,
                'macd_change_percent': macd_change,
                'divergence_strength': abs(price_change / macd_change) if macd_change != 0 else float('inf')
            }
        else:
            if debug:
                print(f"  调试: MACD同步创新高，无背离")
        
        return None
    
    def detect_bottom_divergence(self, price_data, macd_data, lookback_periods=60, debug=False):
        """检测底背离（看涨背离）
        
        底背离定义：价格创新低，但MACD未能创新低，表明下跌动能减弱
        
        Args:
            price_data: 价格数据（DataFrame的low列）
            macd_data: MACD数据（MACD线）
            lookback_periods: 回溯周期数
            debug: 是否输出调试信息
            
        Returns:
            dict: 包含背离信息的字典，如果没有背离则返回None
        """
        if len(price_data) < lookback_periods or len(macd_data) < lookback_periods:
            if debug:
                print(f"  调试: 数据不足，价格数据长度={len(price_data)}，MACD数据长度={len(macd_data)}")
            return None
        
        # 获取最近的价格数据
        recent_prices = price_data.iloc[-lookback_periods:].values
        recent_macd = macd_data.iloc[-lookback_periods:].values
        recent_times = price_data.index[-lookback_periods:]
        
        # 查找价格的两个低点
        price_lows = []
        for i in range(1, len(recent_prices) - 1):
            if recent_prices[i] < recent_prices[i-1] and recent_prices[i] < recent_prices[i+1]:
                price_lows.append((i, recent_prices[i], recent_times[i]))
        
        if len(price_lows) < 2:
            if debug:
                print(f"  调试: 未找到足够的价格低点，仅找到{len(price_lows)}个低点")
                # 输出最低价信息
                min_price_idx = recent_prices.argmin()
                print(f"  调试: 最近{lookback_periods}根K线最低价: {recent_prices[min_price_idx]:.2f} (位置: {min_price_idx})")
            return None
        
        # 按时间顺序取最近的两个低点
        recent_low_idx, recent_low_price, recent_low_time = price_lows[-1]
        prev_low_idx, prev_low_price, prev_low_time = price_lows[-2]
        
        if debug:
            print(f"  调试: 最近低点: {recent_low_price:.2f} (时间: {recent_low_time})")
            print(f"  调试: 前低点: {prev_low_price:.2f} (时间: {prev_low_time})")
        
        # 检查价格是否创新低
        if recent_low_price >= prev_low_price:
            if debug:
                print(f"  调试: 价格未创新低，最近低点 {recent_low_price:.2f} >= 前低点 {prev_low_price:.2f}")
            return None
        
        # 获取对应位置的MACD值
        recent_low_macd = recent_macd[recent_low_idx]
        prev_low_macd = recent_macd[prev_low_idx]
        
        if debug:
            print(f"  调试: 最近低点MACD: {recent_low_macd:.4f}")
            print(f"  调试: 前低点MACD: {prev_low_macd:.4f}")
        
        # 检查MACD是否没有创新低（形成背离）
        if recent_low_macd > prev_low_macd:
            # 计算背离强度（价格跌幅与MACD涨幅的比值）
            price_change = (recent_low_price - prev_low_price) / prev_low_price * 100
            macd_change = (recent_low_macd - prev_low_macd) / abs(prev_low_macd) * 100 if prev_low_macd != 0 else 0
            
            if debug:
                print(f"  调试: 发现底背离！价格下跌{price_change:.2f}%，MACD上涨{macd_change:.2f}%")
            
            return {
                'type': 'bottom_divergence',
                'signal': '看涨背离',
                'recent_low_time': recent_low_time,
                'recent_low_price': recent_low_price,
                'prev_low_time': prev_low_time,
                'prev_low_price': prev_low_price,
                'recent_low_macd': recent_low_macd,
                'prev_low_macd': prev_low_macd,
                'price_change_percent': price_change,
                'macd_change_percent': macd_change,
                'divergence_strength': abs(price_change / macd_change) if macd_change != 0 else float('inf')
            }
        else:
            if debug:
                print(f"  调试: MACD同步创新低，无背离")
        
        return None
    
    def calculate_ema(self, data, period):
        """计算指数移动平均线"""
        return data.ewm(span=period, adjust=False).mean()
    
    def find_macd_divergence(self, symbol="BTCUSDT", interval="1h", lookback_periods=200, divergence_type="top", debug=False):
        """查找MACD背离（顶背离或底背离），并考虑大周期趋势
        
        Args:
            symbol: 币种符号
            interval: 时间周期
            lookback_periods: 回溯周期数
            divergence_type: 背离类型，'top'（顶背离）或'bottom'（底背离）
            debug: 是否输出调试信息
            
        Returns:
            dict: 背离信息字典，如果没有找到则返回None
        """
        print(f"开始分析{symbol}的MACD{('顶' if divergence_type == 'top' else '底')}背离...")
        
        # 获取历史K线数据
        klines = self.get_historical_klines(symbol, interval, limit=lookback_periods)
        if klines is None or len(klines) < 100:
            print("无法获取足够的K线数据进行背离分析")
            return None
        
        # 计算MACD指标
        macd_line, signal_line, _ = self.calculate_macd(klines)
        
        # 获取大周期趋势（使用更长周期的EMA来判断）
        if len(klines) >= 200:
            ema50 = self.calculate_ema(klines['close'], 50)
            ema200 = self.calculate_ema(klines['close'], 200)
            long_term_trend = 'bull' if ema50.iloc[-1] > ema200.iloc[-1] else 'bear'
            
            if debug:
                print(f"  调试: 大周期趋势: {long_term_trend} (EMA50: {ema50.iloc[-1]:.2f}, EMA200: {ema200.iloc[-1]:.2f})")
        else:
            # 如果数据不足，使用MACD方向作为趋势判断
            long_term_trend = 'bull' if macd_line.iloc[-1] > signal_line.iloc[-1] else 'bear'
            if debug:
                print(f"  调试: 数据不足，使用MACD方向判断趋势: {long_term_trend}")
        
        # 检测背离
        if divergence_type == 'top':
            # 优先检查与趋势一致的背离
            if long_term_trend == 'bear':
                divergence = self.detect_top_divergence(klines['high'], macd_line, lookback_periods=min(lookback_periods, 100), debug=debug)
                if divergence:
                    divergence['trend_confirmed'] = True
                    return divergence
            # 再检查与趋势相反的背离
            divergence = self.detect_top_divergence(klines['high'], macd_line, lookback_periods=min(lookback_periods, 100), debug=debug)
            if divergence:
                divergence['trend_confirmed'] = False
        else:
            # 优先检查与趋势一致的背离
            if long_term_trend == 'bull':
                divergence = self.detect_bottom_divergence(klines['low'], macd_line, lookback_periods=min(lookback_periods, 100), debug=debug)
                if divergence:
                    divergence['trend_confirmed'] = True
                    return divergence
            # 再检查与趋势相反的背离
            divergence = self.detect_bottom_divergence(klines['low'], macd_line, lookback_periods=min(lookback_periods, 100), debug=debug)
            if divergence:
                divergence['trend_confirmed'] = False
        
        # 输出背离信息
        if divergence:
            trend_confirmation = "(大周期确认)" if divergence.get('trend_confirmed', False) else "(大周期相反)"
            print(f"\n找到MACD{('顶' if divergence_type == 'top' else '底')}背离信号:{trend_confirmation}")
            print("-" * 80)
            
            if divergence_type == 'top':
                print(f"最近高点时间: {divergence['recent_high_time']}")
                print(f"最近高点价格: {divergence['recent_high_price']:.2f}")
                print(f"前高点时间: {divergence['prev_high_time']}")
                print(f"前高点价格: {divergence['prev_high_price']:.2f}")
                print(f"最近高点MACD: {divergence['recent_high_macd']:.4f}")
                print(f"前高点MACD: {divergence['prev_high_macd']:.4f}")
            else:
                print(f"最近低点时间: {divergence['recent_low_time']}")
                print(f"最近低点价格: {divergence['recent_low_price']:.2f}")
                print(f"前低点时间: {divergence['prev_low_time']}")
                print(f"前低点价格: {divergence['prev_low_price']:.2f}")
                print(f"最近低点MACD: {divergence['recent_low_macd']:.4f}")
                print(f"前低点MACD: {divergence['prev_low_macd']:.4f}")
            
            print(f"价格变化: {divergence['price_change_percent']:.2f}%")
            print(f"MACD变化: {divergence['macd_change_percent']:.2f}%")
            print(f"背离强度: {divergence['divergence_strength']:.2f}")
            print("-" * 80)
            
            return divergence
        else:
            print(f"\n未找到任何MACD{('顶' if divergence_type == 'top' else '底')}背离信号")
            return None
    
    def find_macd_top_divergence(self, symbol="BTCUSDT", interval="1h", lookback_periods=200, debug=False):
        """查找BTC最近的MACD顶背离"""
        return self.find_macd_divergence(symbol, interval, lookback_periods, divergence_type="top", debug=debug)
    
    def find_macd_bottom_divergence(self, symbol="BTCUSDT", interval="1h", lookback_periods=200, debug=False):
        """查找BTC最近的MACD底背离"""
        return self.find_macd_divergence(symbol, interval, lookback_periods, divergence_type="bottom", debug=debug)
    
    def find_latest_btc_divergence(self, divergence_type="top", debug=False):
        """查找BTC最近的背离，在多个周期上进行检查
        
        Args:
            divergence_type: 背离类型，'top'（顶背离）或'bottom'（底背离）
            debug: 是否输出调试信息
            
        Returns:
            dict: 背离信息字典，如果没有找到则返回None
        """
        # 检查多个时间周期
        intervals = ['1h', '4h', '1d']
        
        for interval in intervals:
            print(f"\n在{interval}周期检查{divergence_type}背离...")
            if divergence_type == 'top':
                divergence = self.find_macd_top_divergence(symbol="BTCUSDT", interval=interval, lookback_periods=300, debug=debug)
            else:
                divergence = self.find_macd_bottom_divergence(symbol="BTCUSDT", interval=interval, lookback_periods=300, debug=debug)
                
            if divergence:
                trend_confirmation = "(大周期确认)" if divergence.get('trend_confirmed', False) else "(大周期相反)"
                print(f"✅ 在{interval}周期找到{divergence_type}背离! {trend_confirmation}")
                return divergence
        
        print(f"\n在所有检查的周期中都未找到{divergence_type}背离信号")
        return None
    
    def find_latest_btc_top_divergence(self, debug=False):
        """查找BTC最近的顶背离，在多个周期上进行检查"""
        print(f"=== 开始搜索BTC最近的顶背离 (调试模式: {debug}) ===")
        return self.find_latest_btc_divergence(divergence_type="top", debug=debug)
    
    def find_latest_btc_bottom_divergence(self, debug=False):
        """查找BTC最近的底背离，在多个周期上进行检查"""
        print(f"=== 开始搜索BTC最近的底背离 (调试模式: {debug}) ===")
        return self.find_latest_btc_divergence(divergence_type="bottom", debug=debug)

if __name__ == "__main__":
    analyzer = BTCSignalAnalyzer()
    
    # 设置是否启用调试模式
    debug_mode = True  # 设置为True启用详细调试信息
    
    # 查找BTC最近的信号（包括MACD交叉和转折信号）
    print("\n===== 查找BTC最近的信号 =====\n")
    analyzer.find_recent_signals(symbol="BTCUSDT", large_interval="4h", small_interval="15m", lookback_days=7)
    
    # 同时查找BTC最近的顶背离和底背离
    print("\n===== 检测BTC顶背离 =====\n")
    analyzer.find_latest_btc_top_divergence(debug=debug_mode)
    
    print("\n===== 检测BTC底背离 =====\n")
    analyzer.find_latest_btc_bottom_divergence(debug=debug_mode)