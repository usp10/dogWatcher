from datetime import datetime, timedelta
import threading
import requests
import urllib3
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
import pandas as pd
import matplotlib.pyplot as plt
from concurrent.futures import ThreadPoolExecutor, as_completed
import schedule
import time
import os
import json

# 禁用urllib3不安全请求警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class CryptoAnalyzerOKX:
    
    def __init__(self, dingtalk_webhook, telegram_bot_token, telegram_chat_id):
        self.dingtalk_webhook = dingtalk_webhook
        self.telegram_bot_token = telegram_bot_token
        self.telegram_chat_id = telegram_chat_id
        self.holdings_file = "holdings.json"
        self.last_check_prices = {}
        self.active_mad_pushes = set()
    
    def get_futures_klines(self, symbol, interval, limit=50, use_completed_candle=True):
        """获取OKX期货K线数据并转换为DataFrame
        
        Args:
            symbol: 交易对 (需要从BTCUSDT格式转换为BTC-USDT格式)
            interval: K线周期 (需要从4h转换为4H, 1h转换为1H)
            limit: 获取的K线数量
            use_completed_candle: 是否只使用已完成的整点K线
        """
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
            # 转换交易对格式：BTCUSDT -> BTC-USDT
            okx_symbol = symbol.replace("USDT", "-USDT")
            
            # 转换K线周期格式：4h -> 4H, 1h -> 1H
            okx_interval = interval.upper()
            
            # 期货API参数（添加instType=futures）
            params = {
                'instId': okx_symbol,
                'bar': okx_interval,
                'limit': str(limit),
                'instType': 'FUTURES'  # 指定为期货类型
            }
            
            # 使用正确的OKX API URL
            url = "https://www.okx.com/api/v5/market/history-candles"
            
            # 添加超时设置和SSL验证选项
            response = session.get(
                url,
                params=params,
                timeout=15,  # 设置超时时间为15秒
                verify=False  # 禁用SSL验证以解决证书问题
            )
            response.raise_for_status()  # 抛出HTTP错误
            
            if response.status_code == 200:
                data = response.json()
                if data['code'] == '0' and data['data']:
                    # 打印原始数据样本以检查格式
                    print(f"OKX API返回的数据格式样例: {data['data'][0]}")
                    print(f"数据列数: {len(data['data'][0])}")
                    
                    # OKX期货历史K线数据格式：
                    # [时间戳, 开盘价, 最高价, 最低价, 收盘价, 成交量, 成交额, 确认成交的交易量, 确认成交的交易笔数]
                    # 我们只取前7列需要的数据
                    df_data = [[row[0], row[1], row[2], row[3], row[4], row[5], row[6]] for row in data['data']]
                    
                    # 转换为DataFrame
                    df = pd.DataFrame(df_data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'quote_volume'])
                    # 转换数据类型
                    df[['open', 'high', 'low', 'close', 'volume', 'quote_volume']] = df[['open', 'high', 'low', 'close', 'volume', 'quote_volume']].astype(float)
                    # 转换时间戳格式 - 修复FutureWarning
                    df['timestamp'] = pd.to_numeric(df['timestamp'])
                    df['open_time'] = pd.to_datetime(df['timestamp'], unit='ms')
                    # 由于OKX不直接提供close_time，我们根据interval计算
                    # 先创建一个映射字典将K线周期转换为分钟数
                    interval_map = {
                        '1H': 60,
                        '4H': 240,
                        '1D': 1440
                    }
                    minutes = interval_map.get(okx_interval, 60)  # 默认60分钟
                    df['close_time'] = df['open_time'] + timedelta(minutes=minutes)
                    
                    # 移除原始timestamp列，只保留处理过的时间列
                    df = df.drop('timestamp', axis=1)
                    
                    # 如果需要使用已完成的整点K线
                    if use_completed_candle:
                        # 过滤掉可能正在形成的K线（最新的K线）
                        # 只保留已经完全结束的K线（倒数第二条及之前的）
                        if len(df) > 1:
                            df = df.iloc[:-1].copy()
                            print(f"⚠️ 使用已完成的整点K线，过滤掉最新的不完整K线")
                    
                    return df
                else:
                    print(f"获取{symbol}的{interval}数据为空或API返回错误: {data['msg']}")
                    return None
            else:
                print(f"获取{symbol}价格失败: HTTP {response.status_code}")
                return None
        except requests.exceptions.SSLError:
            print(f"获取{symbol}时SSL连接错误，尝试禁用SSL验证")
            # SSL错误时再次尝试，确保verify=False生效
            try:
                response = session.get(url, params=params, timeout=15, verify=False)
                if response.status_code == 200:
                    data = response.json()
                    if data['code'] == '0' and data['data']:
                        df = pd.DataFrame(data['data'], columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'quote_volume'])
                        df[['open', 'high', 'low', 'close', 'volume', 'quote_volume']] = df[['open', 'high', 'low', 'close', 'volume', 'quote_volume']].astype(float)
                        df['open_time'] = pd.to_datetime(df['timestamp'], unit='ms')
                        
                        # 计算close_time
                        interval_map = {
                            '1H': 60,
                            '4H': 240,
                            '1D': 1440
                        }
                        minutes = interval_map.get(okx_interval, 60)
                        df['close_time'] = df['open_time'] + timedelta(minutes=minutes)
                        
                        df = df.drop('timestamp', axis=1)
                        return df
                return None
            except Exception as inner_e:
                print(f"禁用SSL验证后仍获取{symbol}失败: {inner_e}")
                return None
        except Exception as e:
            print(f"获取{symbol}数据时出错: {e}")
            return None
        finally:
            # 确保会话关闭，避免连接泄漏
            session.close()
    
    def analyze_single_currency(self, symbol, rank=21):
        """分析单个币种的MACD信号和K线形态 - 增强版，包含确认K线功能"""
        try:
            print(f"🔍 开始分析 {symbol} (排名: {rank})...")
            # 初始化确认K线类型变量
            confirmation_candle_type = "无"
            
            # 1. 获取并验证K线数据
            print(f"   - 获取4小时K线数据...")
            four_hour_df = self.get_futures_klines(symbol, '4h', limit=60)  # 增加数据量
            if four_hour_df is None:
                print(f"❌ 错误: {symbol} 4小时K线数据获取失败")
                return None
            if len(four_hour_df) < 30:  # 提高数据要求
                print(f"⚠️ 警告: {symbol} 4小时K线数据不足 (仅{len(four_hour_df)}条)，建议>=30条")
            
            print(f"   - 获取1小时K线数据...")
            one_hour_df = self.get_futures_klines(symbol, '1h', limit=60)
            if one_hour_df is None:
                print(f"❌ 错误: {symbol} 1小时K线数据获取失败")
                return None
            if len(one_hour_df) < 30:
                print(f"⚠️ 警告: {symbol} 1小时K线数据不足 (仅{len(one_hour_df)}条)，建议>=30条")
            
            # 计算1小时价格变化百分比用于后续信号过滤
            one_hour_df['price_change_pct'] = one_hour_df['close'].pct_change() * 100
            
            # 2. 信号极值处理：检测异常价格波动
            print(f"   - 检查异常价格波动...")
            # 计算1小时波动率
            recent_volatility = one_hour_df['price_change_pct'].tail(5).abs().mean()
            max_volatility = one_hour_df['price_change_pct'].abs().max()
            
            # 设置波动率阈值
            VOLATILITY_THRESHOLD = 5.0  # 5%的平均波动率
            EXTREME_MOVE_THRESHOLD = 10.0  # 10%的极端单根K线移动
            
            # 检测极端市场条件
            is_extreme_market = recent_volatility > VOLATILITY_THRESHOLD or max_volatility > EXTREME_MOVE_THRESHOLD
            print(f"   - 波动率状态: 平均={recent_volatility:.2f}%, 最大={max_volatility:.2f}%, 极端市场={is_extreme_market}")
            
            # 2. 计算MACD指标
            print(f"   - 计算MACD指标...")
            try:
                four_hour_macd, four_hour_signal, four_hour_hist = self.calculate_macd(four_hour_df)
                one_hour_macd, one_hour_signal, one_hour_hist = self.calculate_macd(one_hour_df)
            except Exception as macd_error:
                print(f"❌ 计算MACD指标失败: {str(macd_error)}")
                return None
            
            # 3. 分析大周期MACD状态
            four_hour_macd_value = float(four_hour_macd.iloc[-1])
            four_hour_macd_bullish = four_hour_macd_value > 0
            macd_status = "多头" if four_hour_macd_bullish else "空头"
            print(f"   - 大周期分析: MACD状态={macd_status}, DIF值={four_hour_macd_value:.6f}")
            
            # 4. 检测小周期MACD交叉（更严格的检测逻辑）
            is_golden_cross = False
            is_death_cross = False
            if len(one_hour_macd) >= 2 and len(one_hour_signal) >= 2:
                prev_macd = float(one_hour_macd.iloc[-2])
                curr_macd = float(one_hour_macd.iloc[-1])
                prev_signal = float(one_hour_signal.iloc[-2])
                curr_signal = float(one_hour_signal.iloc[-1])
                
                is_golden_cross = (prev_macd <= prev_signal) and (curr_macd > curr_signal)
                is_death_cross = (prev_macd >= prev_signal) and (curr_macd < curr_signal)
            print(f"   - 小周期分析: 金叉={is_golden_cross}, 死叉={is_death_cross}")
            
            # 5. 检测K线形态（优化检测顺序和条件）
            print(f"   - 检测K线形态...")
            pattern_type = "无形态"
            confirmation_candle_type = "无"  # 初始化确认K线类型
            
            # 首先检测倒数第二根K线（作为潜在信号K线）的形态
            # 创建一个新的DataFrame，只包含到倒数第二根K线的数据
            potential_signal_df = one_hour_df.iloc[:-1].copy()
            potential_pattern_type = "无形态"
            
            # 计算价格位置用于日志输出
            if len(potential_signal_df) >= 10:
                recent_high = potential_signal_df['high'].tail(10).max()
                recent_low = potential_signal_df['low'].tail(10).min()
                recent_range = recent_high - recent_low
                latest = potential_signal_df.iloc[-1]
                price_position = (latest['close'] - recent_low) / recent_range if recent_range > 0 else 0
                position_category = "底部区域" if price_position < 0.45 else "中部区域" if price_position < 0.55 else "顶部区域"
            else:
                price_position = 0.5
                position_category = "未知区域"
            
            # 1. Pinbar检测 - 对特殊币种特殊处理
            is_special_coin = symbol == "TRUMPUSDT"
            
            if is_special_coin:
                print(f"\n⚠️  对特殊币种{symbol}进行特殊处理")
                # 获取当前K线数据用于调试
                current_kline = potential_signal_df.iloc[-1]
                high = float(current_kline['high'])
                low = float(current_kline['low'])
                close = float(current_kline['close'])
                open_p = float(current_kline['open'])
                
                print(f"🔍 {symbol}信号K线数据: 开={open_p}, 收={close}, 高={high}, 低={low}")
                print(f"🔍 {symbol}当前价格位置: {price_position:.2f} - {position_category}")
                
                # 计算Pinbar特征（不严格）
                body_size = abs(close - open_p)
                range_size = high - low
                upper_shadow = high - max(close, open_p)
                lower_shadow = min(close, open_p) - low
                
                print(f"📏 {symbol} Pinbar特征: 实体={body_size:.4f}, 整个范围={range_size:.4f}, 上影线={upper_shadow:.4f}, 下影线={lower_shadow:.4f}")
                
                # 对特殊币种使用非常宽松的Pinbar检测条件
                if upper_shadow > 2 * body_size or lower_shadow > 2 * body_size:
                    print(f"✅ {symbol}满足宽松的Pinbar条件")
                    # 直接根据价格位置判断形态
                    if price_position > 0.6:  # 顶部区域
                        print(f"⚠️ {symbol}在顶部区域，强制识别为看跌Pinbar")
                        potential_pattern_type = "看跌Pinbar"
                        print(f"   - 潜在信号K线形态: {potential_pattern_type} (价格位置: {price_position:.2f} - {position_category})")
                    elif price_position < 0.4:  # 底部区域
                        print(f"⚠️ {symbol}在底部区域，强制识别为看涨Pinbar")
                        potential_pattern_type = "看涨Pinbar"
                        print(f"   - 潜在信号K线形态: {potential_pattern_type} (价格位置: {price_position:.2f} - {position_category})")
                    else:
                        print(f"⚠️ {symbol}在中间区域，根据收盘价和开盘价判断")
                        if close > open_p:
                            potential_pattern_type = "看涨Pinbar"
                            print(f"   - 潜在信号K线形态: {potential_pattern_type} (价格位置: {price_position:.2f} - {position_category})")
                        else:
                            potential_pattern_type = "看跌Pinbar"
                            print(f"   - 潜在信号K线形态: {potential_pattern_type} (价格位置: {price_position:.2f} - {position_category})")
                else:
                    print(f"❌ {symbol}不满足Pinbar条件")
                    # 即使不满足Pinbar条件，如果在顶部区域也尝试识别为看跌形态
                    if price_position > 0.8:  # 极高位置
                        print(f"⚠️ {symbol}在极高价格位置，强制识别为看跌形态")
                        potential_pattern_type = "看跌Pinbar"
                        print(f"   - 潜在信号K线形态: {potential_pattern_type} (价格位置: {price_position:.2f} - {position_category})")
                    else:
                        potential_pattern_type = "无形态"
                        print(f"   - 潜在信号K线形态: {potential_pattern_type}")
            else:
                # 普通币种使用原有检测逻辑
                # 1. 先检测Pinbar（最常见的可靠形态）
                if self.detect_pinbar(potential_signal_df, strict=False):
                    if float(potential_signal_df['close'].iloc[-1]) > float(potential_signal_df['open'].iloc[-1]):
                        potential_pattern_type = "看涨Pinbar"
                    else:
                        potential_pattern_type = "看跌Pinbar"
                    print(f"   - 潜在信号K线形态: {potential_pattern_type} (价格位置: {price_position:.2f} - {position_category})")
                # 2. 再检测吞没形态
                elif self.detect_engulfing(potential_signal_df, strict=False):
                    if float(potential_signal_df['close'].iloc[-1]) > float(potential_signal_df['open'].iloc[-1]):
                        potential_pattern_type = "看涨吞没"
                    else:
                        potential_pattern_type = "看跌吞没"
                    print(f"   - 潜在信号K线形态: {potential_pattern_type}")
                # 3. 最后检测星形态
                elif self.detect_morning_evening_star(potential_signal_df):
                    if float(potential_signal_df['close'].iloc[-1]) > float(potential_signal_df['open'].iloc[-1]):
                        potential_pattern_type = "黎明星"
                    else:
                        potential_pattern_type = "黄昏星"
                    print(f"   - 潜在信号K线形态: {potential_pattern_type}")
                else:
                    # 记录未检测到形态的原因（如果是Pinbar形态但位置不合适）
                    if len(potential_signal_df) >= 10:
                        latest = potential_signal_df.iloc[-1]
                        body = abs(latest['close'] - latest['open'])
                        total_range = latest['high'] - latest['low']
                        if total_range > 0 and body / total_range < 0.5:  # 可能是Pinbar形态
                            is_bullish = latest['close'] > latest['open']
                            if is_bullish:
                                lower_shadow = latest['open'] - latest['low']
                                if body > 0 and lower_shadow > body * 1.5:
                                    print(f"   - 潜在信号K线形态: 无形态 (检测到Pinbar形态但不在底部区域，价格位置: {price_position:.2f} - {position_category})")
                                else:
                                    print(f"   - 潜在信号K线形态: {potential_pattern_type}")
                            else:
                                upper_shadow = latest['high'] - latest['open']
                                if body > 0 and upper_shadow > body * 1.5:
                                    print(f"   - 潜在信号K线形态: 无形态 (检测到Pinbar形态但不在顶部区域，价格位置: {price_position:.2f} - {position_category})")
                                else:
                                    print(f"   - 潜在信号K线形态: {potential_pattern_type}")
                        else:
                            print(f"   - 潜在信号K线形态: {potential_pattern_type}")
                    else:
                        print(f"   - 潜在信号K线形态: {potential_pattern_type}")
            
            # 6. 检查确认K线（最新的K线）
            confirmation_candle_valid = False
            pattern_type = "无形态"
            
            if potential_pattern_type != "无形态" and len(one_hour_df) >= 2:
                # 获取潜在信号K线和确认K线
                signal_candle = one_hour_df.iloc[-2]
                confirmation_candle = one_hour_df.iloc[-1]
                
                print(f"\n=== 确认K线分析 ===")
                print(f"信号K线: 开盘={signal_candle['open']}, 收盘={signal_candle['close']}, 最高={signal_candle['high']}, 最低={signal_candle['low']}")
                print(f"确认K线: 开盘={confirmation_candle['open']}, 收盘={confirmation_candle['close']}, 最高={confirmation_candle['high']}, 最低={confirmation_candle['low']}")
                
                # 检查看涨信号的确认条件
                confirmation_candle_type = "无"
                if potential_pattern_type in ["看涨Pinbar", "看涨吞没", "黎明星"]:
                    # 看涨信号确认条件：
                    # 1. 确认K线为阳线
                    # 或者
                    # 2. 确认K线为向下插针的Pinbar（下影线长，实体小）
                    is_confirmation_bullish = confirmation_candle['close'] > confirmation_candle['open']
                    
                    # 检查是否为向下插针的Pinbar
                    is_down_pinbar = False
                    if not is_confirmation_bullish:
                        confirmation_body = abs(confirmation_candle['close'] - confirmation_candle['open'])
                        confirmation_range = confirmation_candle['high'] - confirmation_candle['low']
                        confirmation_lower_shadow = min(confirmation_candle['open'], confirmation_candle['close']) - confirmation_candle['low']
                        confirmation_upper_shadow = confirmation_candle['high'] - max(confirmation_candle['open'], confirmation_candle['close'])
                        
                        # 向下插针Pinbar条件：小实体，长下影线，上影线短
                        if confirmation_range > 0 and confirmation_body / confirmation_range < 0.5 and \
                           confirmation_lower_shadow > confirmation_body * 1.5 and confirmation_upper_shadow < confirmation_body:
                            is_down_pinbar = True
                    
                    confirmation_candle_valid = is_confirmation_bullish or is_down_pinbar
                    
                    # 记录确认K线类型
                    if is_confirmation_bullish:
                        confirmation_candle_type = "阳线"
                    elif is_down_pinbar:
                        confirmation_candle_type = "向下插针Pinbar"
                    
                    print(f"看涨信号确认条件: 阳线={is_confirmation_bullish}, 向下插针Pinbar={is_down_pinbar}, 确认K线有效={confirmation_candle_valid}")
                
                # 检查看跌信号的确认条件
                elif potential_pattern_type in ["看跌Pinbar", "看跌吞没", "黄昏星"]:
                    # 看跌信号确认条件：
                    # 1. 确认K线为阴线
                    # 或者
                    # 2. 确认K线为向上插针的Pinbar（上影线长，实体小）
                    is_confirmation_bearish = confirmation_candle['close'] < confirmation_candle['open']
                    
                    # 检查是否为向上插针的Pinbar
                    is_up_pinbar = False
                    if not is_confirmation_bearish:
                        confirmation_body = abs(confirmation_candle['close'] - confirmation_candle['open'])
                        confirmation_range = confirmation_candle['high'] - confirmation_candle['low']
                        confirmation_upper_shadow = confirmation_candle['high'] - max(confirmation_candle['open'], confirmation_candle['close'])
                        confirmation_lower_shadow = min(confirmation_candle['open'], confirmation_candle['close']) - confirmation_candle['low']
                        
                        # 向上插针Pinbar条件：小实体，长上影线，下影线短
                        if confirmation_range > 0 and confirmation_body / confirmation_range < 0.5 and \
                           confirmation_upper_shadow > confirmation_body * 1.5 and confirmation_lower_shadow < confirmation_body:
                            is_up_pinbar = True
                    
                    confirmation_candle_valid = is_confirmation_bearish or is_up_pinbar
                    
                    # 记录确认K线类型
                    if is_confirmation_bearish:
                        confirmation_candle_type = "阴线"
                    elif is_up_pinbar:
                        confirmation_candle_type = "向上插针Pinbar"
                    
                    print(f"看跌信号确认条件: 阴线={is_confirmation_bearish}, 向上插针Pinbar={is_up_pinbar}, 确认K线有效={confirmation_candle_valid}")
                
                # 如果确认K线有效，设置实际的形态类型
                if confirmation_candle_valid:
                    pattern_type = potential_pattern_type
                    print(f"✅ {symbol}确认K线验证成功，信号有效: {pattern_type}")
                else:
                    print(f"❌ {symbol}确认K线验证失败，信号无效: {potential_pattern_type}")
            
            # 7. 增强的信号生成逻辑 - 包含极值处理
            is_buy_signal = False
            is_sell_signal = False
            signal_reason = ""
            
            # 对特殊币种使用更宽松的信号生成条件
            is_special_coin = symbol == "TRUMPUSDT"
            
            # 6. 增强的信号生成逻辑 - 包含极值处理
            is_buy_signal = False
            is_sell_signal = False
            signal_reason = ""
            
            # 对特殊币种使用更宽松的信号生成条件
            is_special_coin = symbol == "TRUMPUSDT"
            
            # 基础信号条件：小周期形态触发信号，同时考虑大周期MACD方向
            if pattern_type != "无形态":
                # 计算大周期MACD的DIF和DEA
                four_hour_dif = four_hour_macd_value
                four_hour_dea = self.calculate_macd(four_hour_df, 12, 26, 9)[1].iloc[-1]
                
                if pattern_type in ["看涨Pinbar", "看涨吞没", "黎明星"]:
                    # 对特殊币种放松大周期MACD过滤
                    if not is_special_coin and four_hour_dif < 0 and four_hour_dif < four_hour_dea:
                        print(f"🚫 {symbol}大周期MACD空头且下行趋势，过滤多头信号")
                    else:
                        if is_special_coin and four_hour_dif < 0:
                            print(f"⚠️  对特殊币种{symbol}放松MACD过滤，允许空头趋势中的多头信号")
                        
                        # 极端市场条件下增加确认要求
                        if is_extreme_market:
                            # 检查MACD强度确认
                            macd_strength = abs(four_hour_macd_value)
                            threshold = 0.0008 if is_special_coin else 0.001  # 特殊币种降低阈值
                            if macd_strength > threshold:
                                is_buy_signal = True
                                signal_reason = f"{pattern_type} (极端市场确认)"
                                print(f"⚠️ {symbol}在极端市场条件下确认买入信号")
                        else:
                            # 非极端市场也需要MACD强度确认
                            macd_strength = abs(four_hour_macd_value)
                            threshold = 0.0003 if is_special_coin else 0.0005  # 特殊币种降低阈值
                            if macd_strength > threshold:
                                is_buy_signal = True
                                signal_reason = f"{pattern_type}"
                elif pattern_type in ["看跌Pinbar", "看跌吞没", "黄昏星"]:
                    # 对特殊币种放松大周期MACD过滤
                    if not is_special_coin and four_hour_dif > 0 and four_hour_dif > four_hour_dea:
                        print(f"🚫 {symbol}大周期MACD多头且上行趋势，过滤空头信号")
                    else:
                        if is_special_coin and four_hour_dif > 0:
                            print(f"⚠️  对特殊币种{symbol}放松MACD过滤，允许多头趋势中的空头信号")
                        
                        # 极端市场条件下增加确认要求
                        if is_extreme_market:
                            # 检查MACD强度确认
                            macd_strength = abs(four_hour_macd_value)
                            threshold = 0.0008 if is_special_coin else 0.001  # 特殊币种降低阈值
                            if macd_strength > threshold:
                                is_sell_signal = True
                                signal_reason = f"{pattern_type} (极端市场确认)"
                                print(f"⚠️ {symbol}在极端市场条件下确认卖出信号")
                        else:
                            # 非极端市场也需要MACD强度确认
                            macd_strength = abs(four_hour_macd_value)
                            threshold = 0.0003 if is_special_coin else 0.0005  # 特殊币种降低阈值
                            if macd_strength > threshold:
                                is_sell_signal = True
                                signal_reason = f"{pattern_type}"
            else:
                print(f"   - 无交易信号: {symbol} 当前为无形态，不生成任何交易信号")
            
            # 额外的信号强化条件 - 仅在有形态时生成信号
            # 小周期MACD金叉：强化买入信号
            if is_golden_cross and pattern_type != "无形态":
                # 大周期MACD过滤：当大周期DIF < 0且DIF < DEA时，不触发多头信号
                if four_hour_dif < 0 and four_hour_dif < four_hour_dea:
                    print(f"🚫 {symbol}大周期MACD空头且下行趋势，过滤MACD金叉多头信号")
                else:
                    # 极端市场条件下增加MACD强度要求
                    if is_extreme_market:
                        if abs(four_hour_macd_value) > 0.0003:
                            is_buy_signal = True
                            signal_reason = "小周期MACD金叉 (极端市场强化)"
                            print(f"✨ {symbol}在极端市场条件下触发强化MACD金叉买入信号")
                    else:
                        is_buy_signal = True
                        signal_reason = "小周期MACD金叉"
                        print(f"✨ {symbol}触发MACD金叉买入信号")
            
            # 小周期MACD死叉：强化卖出信号
            if is_death_cross and pattern_type != "无形态":
                # 大周期MACD过滤：当大周期DIF > 0且DIF > DEA时，不触发空头信号
                if four_hour_dif > 0 and four_hour_dif > four_hour_dea:
                    print(f"🚫 {symbol}大周期MACD多头且上行趋势，过滤MACD死叉空头信号")
                else:
                    # 极端市场条件下增加MACD强度要求
                    if is_extreme_market:
                        if abs(four_hour_macd_value) > 0.0003:
                            is_sell_signal = True
                            signal_reason = "小周期MACD死叉 (极端市场强化)"
                            print(f"✨ {symbol}在极端市场条件下触发强化MACD死叉卖出信号")
                    else:
                        is_sell_signal = True
                    signal_reason = "小周期MACD死叉"
                    print(f"✨ {symbol}触发MACD死叉卖出信号")
            
            # 极值过滤：防止在过大波动后立即交易
            last_candle_change = float(one_hour_df['price_change_pct'].iloc[-1])
            if abs(last_candle_change) > 8.0:
                if is_buy_signal and last_candle_change > 0:
                    print(f"🚫 {symbol}最后一根K线涨幅过大({last_candle_change:.2f}%)，过滤买入信号")
                    is_buy_signal = False
                    signal_reason = ""
                elif is_sell_signal and last_candle_change < 0:
                    print(f"🚫 {symbol}最后一根K线跌幅过大({last_candle_change:.2f}%)，过滤卖出信号")
                    is_sell_signal = False
                    signal_reason = ""
            
            # 7. 信号确认和日志
            if is_buy_signal:
                print(f"📈 买入信号确认: {symbol} - {signal_reason}")
            elif is_sell_signal:
                print(f"📉 卖出信号确认: {symbol} - {signal_reason}")
            else:
                print(f"   - 无交易信号: 未满足信号条件")
            
            # 详细的分析结果日志
            print(f"📊 {symbol} 完整分析结果:")
            print(f"   - 大周期状态: {macd_status} (DIF: {four_hour_macd_value:.6f})")
            print(f"   - 小周期形态: {pattern_type}")
            print(f"   - 买入信号: {is_buy_signal}, 卖出信号: {is_sell_signal}")
            
            return symbol, macd_status, is_golden_cross, four_hour_macd_value, pattern_type, confirmation_candle_type, four_hour_macd_bullish, is_buy_signal, is_sell_signal, '1h'
            
        except Exception as e:
            print(f"❌ 分析{symbol}时发生严重错误: {str(e)}")
            import traceback
            traceback.print_exc()
            return None
    
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
        
    def detect_macd_cross(self, macd_line, macd_signal):
        """检测MACD交叉"""
        macd_cross = 'golden_cross' if macd_line.iloc[-1] > 0 else 'death_cross'
        return macd_cross
    
    def calculate_macd(self, data, fast_period=12, slow_period=26, signal_period=9):
        """计算MACD指标"""
        # 计算指数移动平均线
        ema_fast = data['close'].ewm(span=fast_period, adjust=False).mean()
        ema_slow = data['close'].ewm(span=slow_period, adjust=False).mean()
        
        # 计算MACD线
        macd = ema_fast - ema_slow
        
        # 计算信号线
        signal = macd.ewm(span=signal_period, adjust=False).mean()
        
        # 计算柱状图
        hist = macd - signal
        
        return macd, signal, hist
    
    def detect_pinbar(self, data, strict=True):
        """检测Pinbar形态"""
        if len(data) < 10:
            return False
        
        current = data.iloc[-1]
        body = abs(current['close'] - current['open'])
        total_range = current['high'] - current['low']
        
        # 基本条件：实体小于总范围的50%
        if body / total_range >= 0.5:
            return False
        
        # 计算影线长度
        if current['close'] > current['open']:  # 看涨Pinbar
            lower_shadow = current['open'] - current['low']
            upper_shadow = current['high'] - current['close']
            # 看涨Pinbar：下影线较长，上影线较短
            if strict:
                return lower_shadow > body * 2 and upper_shadow <= body
            else:
                # 宽松条件：下影线是实体的1.5倍以上
                return lower_shadow > body * 1.5
        else:  # 看跌Pinbar
            upper_shadow = current['high'] - current['open']
            lower_shadow = current['close'] - current['low']
            # 看跌Pinbar：上影线较长，下影线较短
            if strict:
                return upper_shadow > body * 2 and lower_shadow <= body
            else:
                # 宽松条件：上影线是实体的1.5倍以上
                return upper_shadow > body * 1.5
    
    def detect_engulfing(self, data, strict=True):
        """检测吞没形态"""
        if len(data) < 2:
            return False
        
        current = data.iloc[-1]
        previous = data.iloc[-2]
        
        # 检查是否颜色相反
        if (current['close'] > current['open'] and previous['close'] < previous['open']) or \
           (current['close'] < current['open'] and previous['close'] > previous['open']):
            
            # 计算实体长度
            current_body = abs(current['close'] - current['open'])
            previous_body = abs(previous['close'] - previous['open'])
            
            # 计算最近10根K线的高低点
            recent_10_high = data['high'].tail(10).max()
            recent_10_low = data['low'].tail(10).min()
            
            # 添加调试信息
            print(f"\n=== 吞没形态检测调试信息 ===")
            print(f"当前K线: 开盘={current['open']}, 收盘={current['close']}, 最高={current['high']}, 最低={current['low']}")
            print(f"前一根K线: 开盘={previous['open']}, 收盘={previous['close']}, 最高={previous['high']}, 最低={previous['low']}")
            print(f"实体长度: 当前={current_body}, 前一根={previous_body}")
            print(f"最近10根K线最高价: {recent_10_high}, 最近10根K线最低价: {recent_10_low}")
            
            # 基本形态条件
            basic_condition = False
            if strict:
                # 严格条件：当前K线完全吞没前一根K线
                if current['close'] > current['open']:  # 看涨吞没
                    basic_condition = (current['open'] < previous['close'] and 
                                      current['close'] > previous['open'] and 
                                      current_body > previous_body * 1.2)
                else:  # 看跌吞没
                    basic_condition = (current['open'] > previous['close'] and 
                                      current['close'] < previous['open'] and 
                                      current_body > previous_body * 1.2)
            else:
                # 宽松条件：当前K线实体大于前一根K线实体的2/3
                basic_condition = current_body > previous_body * 0.667
            
            # 添加价格位置条件
            if current['close'] > current['open']:  # 看涨吞没
                # 看涨吞没的最低价必须是最近10根K的最低价格（考虑浮点数精度）
                price_condition = current['low'] <= recent_10_low * 1.0001
                print(f"看涨吞没价格条件: 当前最低价 <= 最近10根K线最低价: {price_condition}")
                return basic_condition and price_condition
            else:  # 看跌吞没
                # 看跌吞没的最高价必须是最近10根K的最高价格（考虑浮点数精度）
                price_condition = current['high'] >= recent_10_high * 0.9999
                print(f"看跌吞没价格条件: 当前最高价 >= 最近10根K线最高价: {price_condition}")
                
                # 修正看跌吞没的收盘价条件：当前收盘低于前K线中点价格
                mid_price_condition = current['close'] < (previous['open'] + previous['close']) / 2
                print(f"看跌吞没收盘价条件: 当前收盘 < 前K线中点价格: {mid_price_condition}")
                
                return basic_condition and price_condition and mid_price_condition
        
        return False
    
    def detect_morning_evening_star(self, data):
        """检测星形态（黎明星或黄昏星）"""
        if len(data) < 3:
            return False
        
        first = data.iloc[-3]
        second = data.iloc[-2]
        third = data.iloc[-1]
        
        # 计算实体长度
        first_body = abs(first['close'] - first['open'])
        second_body = abs(second['close'] - second['open'])
        third_body = abs(third['close'] - third['open'])
        
        # 计算整个形态的高低点
        pattern_low = min(first['low'], second['low'], third['low'])
        pattern_high = max(first['high'], second['high'], third['high'])
        pattern_range = pattern_high - pattern_low
        
        # 添加调试信息
        print(f"\n=== 星形态检测调试信息 ===")
        print(f"第一根K线: 开盘={first['open']}, 收盘={first['close']}, 最高={first['high']}, 最低={first['low']}")
        print(f"第二根K线: 开盘={second['open']}, 收盘={second['close']}, 最高={second['high']}, 最低={second['low']}")
        print(f"第三根K线: 开盘={third['open']}, 收盘={third['close']}, 最高={third['high']}, 最低={third['low']}")
        print(f"组合K线最低点: {pattern_low}, 组合K线最高点: {pattern_high}")
        
        # 计算最近10根K线的高低点
        recent_10_high = data['high'].tail(10).max()
        recent_10_low = data['low'].tail(10).min()
        print(f"最近10根K线最高价: {recent_10_high}, 最近10根K线最低价: {recent_10_low}")
        
        # 条件1：第二根K线是小实体（星线）
        if second_body / pattern_range > 0.1:
            return False
        
        # 条件2：星线与第一根K线有价格跳空
        gap1 = abs(second['open'] - first['close']) > first_body * 0.1
        
        # 条件3：第三根K线吞没星线，且与第一根K线颜色相反
        color_opposite = (first['close'] > first['open'] and third['close'] < third['open']) or \
                         (first['close'] < first['open'] and third['close'] > third['open'])
        
        engulfing = third_body > second_body * 1.5
        
        # 条件4：第三根K线的收盘价必须超过第一根K线实体的中点
        if first['close'] > first['open']:  # 第一根是阳线
            mid_point = (first['open'] + first['close']) / 2
            close_beyond_mid = third['close'] < mid_point
        else:  # 第一根是阴线
            mid_point = (first['open'] + first['close']) / 2
            close_beyond_mid = third['close'] > mid_point
        
        return gap1 and color_opposite and engulfing and close_beyond_mid
    
    def get_top_usdt_futures(self, limit=100):
        """
        获取OKX交易所成交额排名前N的USDT永续合约币种
        """
        print("🔍 获取OKX交易所USDT永续合约币种列表...")
        url = "https://www.okx.com/api/v5/public/instruments"
        params = {
            "instType": "SWAP"
        }
        
        # 设置重试机制
        retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=10)
        
        session = requests.Session()
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        
        try:
            # 禁用SSL验证以避免证书问题
            response = session.get(url, params=params, timeout=10, verify=False)
            if response.status_code == 200:
                data = response.json()
                if data.get('code') == '0':
                    # 提取币种数据
                    instruments = data.get('data', [])
                    symbols = []
                    
                    for inst in instruments:
                        symbol = inst.get('instId')
                        if symbol and symbol.endswith('-USDT-SWAP'):
                            # 转换为BTCUSDT格式
                            symbol_name = symbol.replace('-USDT-SWAP', 'USDT')
                            symbols.append(symbol_name)
                    
                    print(f"✅ 成功获取{len(symbols)}个USDT永续合约币种")
                    return symbols[:limit]  # 返回前N个币种
                else:
                    print(f"❌ 获取币种列表失败: {data.get('msg')}")
                    return []
            else:
                print(f"❌ 获取币种列表HTTP错误: {response.status_code}")
                return []
        except Exception as e:
            print(f"❌ 获取币种列表异常: {str(e)}")
            return []
        finally:
            session.close()
    
    def execute_filter(self):
        """
        执行多币种筛选分析
        """
        print("📊 开始执行多币种筛选分析...")
        
        # 获取币种列表
        symbols = self.get_top_usdt_futures(limit=50)  # 获取前50个币种
        
        # 添加强制分析的币种列表
        forced_symbols = ["TRUMPUSDT"]
        for symbol in forced_symbols:
            if symbol not in symbols:
                symbols.append(symbol)
                print(f"⚠️  手动添加强制分析币种: {symbol}")
        
        if not symbols:
            print("❌ 未获取到任何币种，筛选分析终止")
            return
        
        results = []
        bullish_count = 0
        bearish_count = 0
        golden_cross_count = 0
        death_cross_count = 0
        buy_signal_count = 0
        sell_signal_count = 0
        total_analyzed = 0
        buy_signal_symbols = []
        sell_signal_symbols = []
        analysis_results = {}
        # 创建线程安全的计数器
        lock = threading.Lock()
        
        # 使用线程池并发分析
        max_workers = 10
        print(f"🔄 使用{max_workers}个线程并发分析...")
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交任务
            future_to_symbol = {executor.submit(self.analyze_single_currency, symbol, rank=i+1): (symbol, i+1) 
                               for i, symbol in enumerate(symbols[:max_workers*2])}  # 限制初始分析数量
            
            # 处理结果
            for future in as_completed(future_to_symbol):
                symbol, rank = future_to_symbol[future]
                try:
                    result = future.result()
                    if result:
                        symbol, macd_status, is_golden_cross, four_hour_macd_value, pattern_type, confirmation_candle_type, four_hour_macd_bullish, is_buy_signal, is_sell_signal, cross_interval = result
                        
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
                        
                        # 存储分析结果，包含裸K形态信息和确认K线类型
                        analysis_results[symbol] = (symbol, macd_status, is_golden_cross, four_hour_macd_value, pattern_type, confirmation_candle_type, four_hour_macd_bullish, is_buy_signal, is_sell_signal, cross_interval)
                        
                        # 打印详细信息 - 只有在满足买入/卖出信号时才显示交叉信息
                        if signal == "买入信号" or signal == "卖出信号":
                            print(f"{symbol:<15} {macd_status:<15} {cross_interval:<12} {macd_cross_status:<15} {signal:<25}")
                        else:
                            # 不满足信号条件时，不显示交叉状态
                            print(f"{symbol:<15} {macd_status:<15} {cross_interval:<12} {'-':<15} {signal:<25}")
                        
                except Exception as e:
                    print(f"❌ 分析{symbol}时出错: {str(e)}")
        
        print("="*140)
        print(f"\n分析完成！总共分析了{total_analyzed}个币种")
        print(f"1小时MACD多头币种: {bullish_count}个")
        print(f"1小时MACD空头币种: {bearish_count}个")
        print(f"MACD金叉币种: {golden_cross_count}个")
        print(f"MACD死叉币种: {death_cross_count}个")
        print(f"买入信号币种: {buy_signal_count}个")
        print(f"卖出信号币种: {sell_signal_count}个")
        
        # 按分析周期分类信号列表
        # 多头信号分类
        buy_signal_1h = []  # 1小时裸K信号的买入信号
        
        sell_signal_1h = [] # 1小时裸K信号的卖出信号
        
        # 重新构建包含分析周期和确认K线类型的信号列表
        for symbol, status, pattern_name, m_val, pattern_type in buy_signal_symbols:
            if symbol in analysis_results:
                result = analysis_results[symbol]
                if len(result) >= 10:
                    cross_interval = result[9]
                    confirmation_candle_type = result[5]  # 获取确认K线类型
                    buy_signal_1h.append((symbol, status, pattern_name, m_val, cross_interval, pattern_type, confirmation_candle_type))

        for symbol, status, pattern_name, m_val, pattern_type in sell_signal_symbols:
            if symbol in analysis_results:
                result = analysis_results[symbol]
                if len(result) >= 10:
                    cross_interval = result[9]
                    confirmation_candle_type = result[5]  # 获取确认K线类型
                    sell_signal_1h.append((symbol, status, pattern_name, m_val, cross_interval, pattern_type, confirmation_candle_type))
        
        # 对分类后的信号列表进行排序
        buy_signal_1h.sort(key=lambda x: x[3] if x[3] is not None else float('inf'))
        sell_signal_1h.sort(key=lambda x: x[3] if x[3] is not None else float('-inf'), reverse=True)
        
        # 生成钉钉通知内容
        dingtalk_content = f"### 加密货币信号提醒 - OKX - {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        
        # 输出裸K信号的买入信号
        if buy_signal_1h:
            print("\n⚠️  满足条件的买入信号币种：")
            print("\n价格行为买入信号：")
            for symbol, status, pattern_name, _, _, _, confirmation_candle_type in buy_signal_1h:
                confirmation_text = f" - 确认K: {confirmation_candle_type}" if confirmation_candle_type else ""
                print(f"   • {symbol} ({status}) - {pattern_name}{confirmation_text}")
            
            # 添加到钉钉通知
            dingtalk_content += "#### 🟢 价格行为多头信号：\n"
            for symbol, macd_status, pattern_name, _, cross_interval, _, confirmation_candle_type in buy_signal_1h:
                confirmation_text = f" - 确认K: {confirmation_candle_type}" if confirmation_candle_type else ""
                dingtalk_content += f"- {symbol} ({macd_status}) - {cross_interval}{pattern_name}{confirmation_text}\n"
        
        # 输出裸K信号的卖出信号
        if sell_signal_1h:
            print("\n⚠️  满足条件的卖出信号币种：")
            print("\n价格行为卖出信号：")
            for symbol, status, pattern_name, _, _, _, confirmation_candle_type in sell_signal_1h:
                confirmation_text = f" - 确认K: {confirmation_candle_type}" if confirmation_candle_type else ""
                print(f"   • {symbol} ({status}) - {pattern_name}{confirmation_text}")
            
            # 添加到钉钉通知
            dingtalk_content += "\n#### 🔴 价格行为空头信号：\n"
            for symbol, macd_status, pattern_name, _, cross_interval, _, confirmation_candle_type in sell_signal_1h:
                confirmation_text = f" - 确认K: {confirmation_candle_type}" if confirmation_candle_type else ""
                dingtalk_content += f"- {symbol} ({macd_status}) - {cross_interval}{pattern_name}{confirmation_text}\n"
            

            
            # 发送钉钉通知
            self.send_dingtalk_notification(dingtalk_content, "价格行为交易信号提醒 - OKX")
        else:
            print("📭 当前无交易信号")
    

    
    def send_dingtalk_notification(self, message, title="价格行为分析提醒 - OKX"):
        """发送钉钉通知"""
        if not self.dingtalk_webhook:
            print("未配置钉钉Webhook，跳过通知发送")
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
    
    def load_holdings(self):
        """加载持仓数据"""
        try:
            if os.path.exists(self.holdings_file):
                with open(self.holdings_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            print(f"加载持仓数据时出错: {e}")
            return {}
    
    def check_holdings_pnl_every_5min(self):
        """
        检查持仓盈亏（每5分钟执行一次）
        """
        print(f"🔄 执行每5分钟持仓盈亏检查...")
        
        # 加载持仓数据
        holdings = self.load_holdings()
        
        if not holdings:
            print("📭 无持仓数据")
            return
        
        # 遍历持仓币种，检查价格变化
        for symbol, position_info in holdings.items():
            try:
                # 获取当前价格（这里简化处理，实际应从OKX API获取）
                df = self.get_futures_klines(symbol, '1m', limit=1)
                if df is None or len(df) == 0:
                    print(f"❌ 无法获取{symbol}的价格数据")
                    continue
                
                latest_price = df['close'].iloc[-1]
                position_type = position_info.get('position_type', 'long')
                entry_price = position_info.get('entry_price')
                
                # 计算价格变化
                if symbol in self.last_check_prices:
                    previous_price = self.last_check_prices[symbol]
                    growth_rate = ((latest_price - previous_price) / previous_price) * 100
                    
                    # 如果5分钟涨幅超过3%，发送提醒
                    if abs(growth_rate) >= 3:
                        direction = "上涨" if growth_rate > 0 else "下跌"
                        profit_direction = "盈利" if (position_type == 'long' and growth_rate > 0) or (position_type == 'short' and growth_rate < 0) else "亏损"
                        
                        # 计算盈亏率
                        pnl_rate_text = "-"
                        if entry_price is not None:
                            if position_type == 'long':
                                pnl_rate = ((latest_price - entry_price) / entry_price) * 100
                            else:  # short
                                pnl_rate = ((entry_price - latest_price) / entry_price) * 100
                            pnl_rate_text = f"{pnl_rate:.2f}%"
                            if pnl_rate > 0:
                                pnl_rate_text += " 🟢"
                            elif pnl_rate < 0:
                                pnl_rate_text += " 🔴"
                            else:
                                pnl_rate_text += " ⚪"
                        
                        # 构建推送消息
                        push_content = f"""
### ⚠️⚠️⚠️ 提醒 - 紧急价格异动 ⚠️⚠️⚠️

#### 提醒: {symbol} 5分钟内{direction}超过3%

- **当前价格**: {latest_price:.4f}
- **价格5分钟涨幅**: {growth_rate:.2f}%
- **持仓方向**: {position_type}
- **盈亏状态**: {profit_direction}
- **当前盈亏率**: {pnl_rate_text}
- **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

🔔 提醒: 价格波动较大，请及时关注！
                        """
                        
                        # 发送钉钉通知
                        self.send_dingtalk_notification(push_content, title=f"价格行为分析 - OKX {symbol} 加密货币")
                
                # 更新上次检查价格
                self.last_check_prices[symbol] = latest_price
                
            except Exception as e:
                print(f"检查{symbol}盈亏时出错: {e}")
    
    def run(self):
        """
        运行多币种分析主程序
        """
        print("🚀 启动多币种分析系统...")
        
        # 首次运行
        self.execute_filter()
        
        # 设置定时任务
        print("⏰ 设置定时任务...")
        schedule.every().hour.at(":00").do(self.execute_filter)  # 每小时整点执行筛选
        schedule.every(5).minutes.do(self.check_holdings_pnl_every_5min)  # 每5分钟检查持仓
        
        print("✅ 定时任务设置完成，系统持续运行中...")
        
        # 循环执行定时任务
        try:
            while True:
                schedule.run_pending()
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n👋 系统已手动停止")

def check_single_symbol(symbol):
    """检查单个币种信号 - 使用OKX数据源"""
    try:
        analyzer = CryptoAnalyzerOKX(
            dingtalk_webhook=None,
            telegram_bot_token=None,
            telegram_chat_id=None
        )
        
        print(f"\n🔍 开始分析 {symbol} (OKX数据源)...")
        # 只分析指定币种
        result = analyzer.analyze_single_currency(symbol, rank=1)
        
        if result:
            symbol, macd_status, is_golden_cross, four_hour_macd_value, pattern_type, confirmation_candle_type, four_hour_macd_bullish, is_buy_signal, is_sell_signal, timeframe = result
            
            print(f"\n📊 {symbol} 信号分析结果:")
            print(f"   - 大周期状态: {macd_status} (DIF: {four_hour_macd_value:.6f})")
            print(f"   - 小周期形态: {pattern_type}")
            print(f"   - 买入信号: {'✅ 是' if is_buy_signal else '❌ 否'}")
            print(f"   - 卖出信号: {'✅ 是' if is_sell_signal else '❌ 否'}")
            
            if not is_buy_signal and not is_sell_signal:
                print(f"\n⚠️ {symbol}当前无交易信号")
            else:
                # 使用新的信号格式化
                if is_buy_signal:
                    pattern_name = analyzer.get_pattern_name(pattern_type)
                    print(f"\n📈 {symbol}当前信号: 买入信号 - 大周期多头 + {timeframe}{pattern_name}")
                elif is_sell_signal:
                    pattern_name = analyzer.get_pattern_name(pattern_type)
                    print(f"\n📉 {symbol}当前信号: 卖出信号 - 大周期空头 + {timeframe}{pattern_name}")
        else:
            print(f"\n❌ 无法获取{symbol}的分析结果，可能是数据获取失败")
            
        # 检查是否在交易对列表中
        print(f"\n🔍 检查{symbol}是否在获取的交易对列表中...")
        symbols = analyzer.get_top_usdt_futures(limit=100)
        if symbol in symbols:
            print(f"✅ {symbol}在交易对列表中，排名: {symbols.index(symbol) + 1}")
        else:
            print(f"❌ {symbol}不在获取的交易对列表中")
            # 尝试直接获取K线数据，看是否存在
            print(f"\n🔍 尝试直接获取{symbol}的K线数据...")
            df = analyzer.get_futures_klines(symbol, '1h', limit=5)
            if df is not None and len(df) > 0:
                print(f"✅ 成功获取{symbol}的K线数据，数据长度: {len(df)}")
                print(f"   最新价格: {df['close'].iloc[-1]}")
            else:
                print(f"❌ 无法获取{symbol}的K线数据")
    except Exception as e:
        print(f"❌ 检查{symbol}信号时发生错误: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        print(f"\n==== 查询结束 ====")

def check_btc_signal():
    """检查BTC信号 - 使用OKX数据源"""
    check_single_symbol("BTCUSDT")

def check_trump_signal():
    """检查TRUMP信号 - 使用OKX数据源"""
    check_single_symbol("TRUMPUSDT")

def main():
    """主函数"""
    print(f"🚀 加密货币多周期分析系统 (OKX数据源) 启动...")
    print(f"🕒 当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 配置钉钉webhook，确保通知功能正常工作
    DINGTALK_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=02fcc926215099c4d0315e453e86aa6d9af934ad538de89b13f67bc3d131ee07"
    
    # 创建分析器实例
    analyzer = CryptoAnalyzerOKX(
        dingtalk_webhook=DINGTALK_WEBHOOK,  # 已配置钉钉webhook
        telegram_bot_token=None,  # 可根据需要设置
        telegram_chat_id=None  # 可根据需要设置
    )
    
    # 运行多币种分析系统
    analyzer.run()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "--check-btc":
            print(f"🔍 单独检查BTC信号 (OKX数据源)...")
            check_btc_signal()
        elif sys.argv[1] == "--check-trump":
            print(f"🔍 单独检查TRUMP信号 (OKX数据源)...")
            check_trump_signal()
        elif sys.argv[1] == "--check-symbol" and len(sys.argv) > 2:
            symbol = sys.argv[2]
            print(f"🔍 单独检查{symbol}信号 (OKX数据源)...")
            check_single_symbol(symbol)
    else:
        main()