import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import requests
import time

# 创建一个测试用的调试脚本，验证15分钟周期的MACD分析逻辑

class MACDDebugger:
    def __init__(self):
        # 直接在类中实现必要的方法，而不是导入外部类
        self.api_url = "https://api.binance.com"
        self.headers = {'Content-Type': 'application/json'}
    
    def get_kline_data(self, symbol, interval, limit=100):
        """获取K线数据"""
        try:
            endpoint = f"{self.api_url}/api/v3/klines"
            params = {
                'symbol': symbol,
                'interval': interval,
                'limit': limit
            }
            
            response = requests.get(endpoint, headers=self.headers, params=params)
            data = response.json()
            
            # 转换为DataFrame
            columns = ['open_time', 'open', 'high', 'low', 'close', 'volume', 
                      'close_time', 'quote_asset_volume', 'number_of_trades', 
                      'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore']
            df = pd.DataFrame(data, columns=columns)
            
            # 转换数据类型
            numeric_columns = ['open', 'high', 'low', 'close', 'volume']
            for col in numeric_columns:
                df[col] = df[col].astype(float)
            
            df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
            df['close_time'] = pd.to_datetime(df['close_time'], unit='ms')
            
            return df
        except Exception as e:
            print(f"获取K线数据失败: {e}")
            return None
    
    def calculate_macd(self, close_prices, fast_period=12, slow_period=26, signal_period=9):
        """计算MACD指标"""
        try:
            # 计算EMA
            ema_fast = close_prices.ewm(span=fast_period, adjust=False).mean()
            ema_slow = close_prices.ewm(span=slow_period, adjust=False).mean()
            
            # 计算MACD线
            macd_line = ema_fast - ema_slow
            
            # 计算信号线
            signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
            
            # 计算柱状图
            histogram = macd_line - signal_line
            
            return macd_line, signal_line, histogram
        except Exception as e:
            print(f"计算MACD失败: {e}")
            return None, None, None
    
    def detect_macd_cross(self, macd_line, signal_line):
        """检测MACD交叉"""
        try:
            # 确保有足够的数据点
            if len(macd_line) < 3 or len(signal_line) < 3:
                return 'no_cross'
            
            # 检查是否发生金叉或死叉
            # 使用iloc[-3]和iloc[-2]进行判断
            if (macd_line.iloc[-3] < signal_line.iloc[-3] and 
                macd_line.iloc[-2] > signal_line.iloc[-2]):
                return 'golden_cross'  # 金叉
            elif (macd_line.iloc[-3] > signal_line.iloc[-3] and 
                  macd_line.iloc[-2] < signal_line.iloc[-2]):
                return 'death_cross'  # 死叉
            else:
                return 'no_cross'  # 无交叉
        except Exception as e:
            print(f"检测MACD交叉失败: {e}")
            return 'no_cross'
    
    def debug_macd_15min(self, symbol='BTCUSDT'):
        print(f"\n===== 调试15分钟周期MACD分析：{symbol} =====\n")
        
        try:
            # 获取15分钟K线数据
            quarter_hour_interval = '15m'
            quarter_hour_kline = self.get_kline_data(symbol, quarter_hour_interval, limit=200)
            
            if quarter_hour_kline is None or len(quarter_hour_kline) < 100:
                print(f"警告：{symbol} 15分钟K线数据不足")
                return
            
            print(f"成功获取 {len(quarter_hour_kline)} 条15分钟K线数据")
            
            # 获取4小时K线数据
            four_hour_interval = '4h'
            four_hour_kline = self.get_kline_data(symbol, four_hour_interval, limit=100)
            
            if four_hour_kline is None or len(four_hour_kline) < 20:
                print(f"警告：{symbol} 4小时K线数据不足")
                return
            
            print(f"成功获取 {len(four_hour_kline)} 条4小时K线数据")
            
            # 计算15分钟MACD
            quarter_hour_macd_line, quarter_hour_signal_line, quarter_hour_histogram = \
                self.calculate_macd(quarter_hour_kline['close'])
            
            print(f"\n15分钟MACD数据：")
            print(f"最新MACD线值: {quarter_hour_macd_line.iloc[-1]:.6f}")
            print(f"最新信号线值: {quarter_hour_signal_line.iloc[-1]:.6f}")
            print(f"最新柱状图值: {quarter_hour_histogram.iloc[-1]:.6f}")
            print(f"前一根MACD线值: {quarter_hour_macd_line.iloc[-2]:.6f}")
            print(f"前一根信号线值: {quarter_hour_signal_line.iloc[-2]:.6f}")
            print(f"前一根柱状图值: {quarter_hour_histogram.iloc[-2]:.6f}")
            
            # 检测MACD交叉
            cross_status = self.detect_macd_cross(quarter_hour_macd_line, quarter_hour_signal_line)
            print(f"\nMACD交叉状态: {cross_status}")
            
            # 检查是否在0轴下发生金叉
            if cross_status == 'golden_cross':
                last_macd = quarter_hour_macd_line.iloc[-2]
                is_below_zero = last_macd < 0
                print(f"金叉发生时MACD值: {last_macd:.6f}, 是否在0轴下: {is_below_zero}")
            
            # 检查是否在0轴上发生死叉
            if cross_status == 'death_cross':
                last_macd = quarter_hour_macd_line.iloc[-2]
                is_above_zero = last_macd > 0
                print(f"死叉发生时MACD值: {last_macd:.6f}, 是否在0轴上: {is_above_zero}")
            
            # 打印最近的MACD交叉点
            print(f"\n最近30个K线的MACD交叉点:")
            for i in range(len(quarter_hour_macd_line)-30, len(quarter_hour_macd_line)):
                if i-1 >= 0 and i < len(quarter_hour_macd_line) and i-1 < len(quarter_hour_signal_line):
                    if quarter_hour_macd_line.iloc[i-1] < quarter_hour_signal_line.iloc[i-1] and \
                       quarter_hour_macd_line.iloc[i] > quarter_hour_signal_line.iloc[i]:
                        print(f"K线{i}: 金叉, MACD值: {quarter_hour_macd_line.iloc[i]:.6f}, 是否在0轴下: {quarter_hour_macd_line.iloc[i] < 0}")
                    elif quarter_hour_macd_line.iloc[i-1] > quarter_hour_signal_line.iloc[i-1] and \
                         quarter_hour_macd_line.iloc[i] < quarter_hour_signal_line.iloc[i]:
                        print(f"K线{i}: 死叉, MACD值: {quarter_hour_macd_line.iloc[i]:.6f}, 是否在0轴上: {quarter_hour_macd_line.iloc[i] > 0}")
            
        except Exception as e:
            print(f"调试过程中出错: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    debugger = MACDDebugger()
    
    # 测试几个主流币种
    symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT']
    
    for symbol in symbols:
        debugger.debug_macd_15min(symbol)
        print("\n" + "="*70 + "\n")
    
    print("调试完成！")