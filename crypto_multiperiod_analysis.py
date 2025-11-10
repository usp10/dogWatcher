from datetime import datetime
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


class CryptoAnalyzer:
    
    def __init__(self, dingtalk_webhook, telegram_bot_token, telegram_chat_id):
        self.dingtalk_webhook = dingtalk_webhook
        self.telegram_bot_token = telegram_bot_token
        self.telegram_chat_id = telegram_chat_id
        self.holdings_file = "holdings.json"
        self.last_check_prices = {}
        self.active_mad_pushes = set()
        # 定义BN平台alpha板块合约币列表
        self.alpha_coins = {
            "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "ARBUSDT", 
            "AAVEUSDT", "AVAXUSDT", "BCHUSDT", "COMPUSDT", "CRVUSDT",
            "DOTUSDT", "FILUSDT", "LINKUSDT", "LTCUSDT", "MATICUSDT",
            "MKRUSDT", "NEARUSDT", "UNIUSDT", "XMRUSDT", "XTZUSDT"
        }
    
    def get_futures_klines(self, symbol, interval, limit=50, use_completed_candle=True):
        """获取期货K线数据并转换为DataFrame
        
        Args:
            symbol: 交易对
            interval: K线周期
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
            url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
            # 添加超时设置和SSL验证选项
            response = session.get(
                url,
                timeout=15,  # 设置超时时间为15秒
                verify=False  # 禁用SSL验证以解决证书问题
            )
            response.raise_for_status()  # 抛出HTTP错误
            
            if response.status_code == 200:
                data = response.json()
                if data:
                    # 转换为DataFrame
                    df = pd.DataFrame(data, columns=['open_time', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_volume', 'trades', 'taker_buy_base', 'taker_buy_quote', 'ignore'])
                    # 转换数据类型
                    df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
                    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
                    df['close_time'] = pd.to_datetime(df['close_time'], unit='ms')
                    
                    # 如果需要使用已完成的整点K线
                    if use_completed_candle:
                        # 过滤掉可能正在形成的K线（最新的K线）
                        # 只保留已经完全结束的K线（倒数第二条及之前的）
                        if len(df) > 1:
                            df = df.iloc[:-1].copy()
                            print(f"⚠️ 使用已完成的整点K线，过滤掉最新的不完整K线")
                    
                    return df
                else:
                    print(f"获取{symbol}的{interval}数据为空")
                    return None
            else:
                print(f"获取{symbol}价格失败: HTTP {response.status_code}")
                return None
        except requests.exceptions.SSLError:
            print(f"获取{symbol}时SSL连接错误，尝试禁用SSL验证")
            # SSL错误时再次尝试，确保verify=False生效
            try:
                response = session.get(url, timeout=15, verify=False)
                if response.status_code == 200:
                    data = response.json()
                    if data:
                        df = pd.DataFrame(data, columns=['open_time', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_volume', 'trades', 'taker_buy_base', 'taker_buy_quote', 'ignore'])
                        df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
                        df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
                        df['close_time'] = pd.to_datetime(df['close_time'], unit='ms')
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
            
            # 基础信号条件：小周期形态触发信号，同时考虑大周期MACD方向
            if pattern_type != "无形态":
                # 计算大周期MACD的DIF和DEA
                four_hour_dif = four_hour_macd_value
                four_hour_dea = self.calculate_macd(four_hour_df, 12, 26, 9)[1].iloc[-1]
                
                if pattern_type in ["看涨Pinbar", "看涨吞没", "黎明星"]:
                    # 大周期MACD过滤：当大周期DIF < 0且DIF < DEA时，不触发多头信号
                    if four_hour_dif < 0 and four_hour_dif < four_hour_dea:
                        print(f"🚫 {symbol}大周期MACD空头且下行趋势，过滤多头信号")
                    else:
                        # 基础买入信号
                        is_buy_signal = True
                        signal_reason = f"{pattern_type}"
                elif pattern_type in ["看跌Pinbar", "看跌吞没", "黄昏星"]:
                    # 大周期MACD过滤：当大周期DIF > 0且DIF > DEA时，不触发空头信号
                    if four_hour_dif > 0 and four_hour_dif > four_hour_dea:
                        print(f"🚫 {symbol}大周期MACD多头且上行趋势，过滤空头信号")
                    else:
                        # 基础卖出信号
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
                    # MACD金叉买入信号
                    is_buy_signal = True
                    signal_reason = "小周期MACD金叉"
                    print(f"✨ {symbol}触发MACD金叉买入信号")
            
            # 小周期MACD死叉：强化卖出信号
            if is_death_cross and pattern_type != "无形态":
                # 大周期MACD过滤：当大周期DIF > 0且DIF > DEA时，不触发空头信号
                if four_hour_dif > 0 and four_hour_dif > four_hour_dea:
                    print(f"🚫 {symbol}大周期MACD多头且上行趋势，过滤MACD死叉空头信号")
                else:
                    # MACD死叉卖出信号
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
            
            # 8. 信号确认和日志
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
            print(f"   - 确认K线类型: {confirmation_candle_type}")
            print(f"   - 买入信号: {is_buy_signal}, 卖出信号: {is_sell_signal}")
            
            return symbol, macd_status, is_golden_cross, four_hour_macd_value, pattern_type, four_hour_macd_bullish, is_buy_signal, is_sell_signal, '1h', confirmation_candle_type
            
        except Exception as e:
            print(f"❌ 分析{symbol}时发生严重错误: {str(e)}")
            import traceback
            traceback.print_exc()
            return None
    
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
        """
        检测Pinbar形态，strict=False时放宽条件
        
        新增位置判断逻辑：
        - 看涨Pinbar必须出现在价格底部区域
        - 看跌Pinbar必须出现在价格顶部区域
        
        新增形态要求：
        - 看涨Pinbar：上影线不能超过实体长度，且最低价为最近10根K线最低
        - 看跌Pinbar：下影线不能超过实体长度，且最高价为最近10根K线最高
        """
        # 至少需要10根K线来判断价格位置和检查极值
        if len(data) < 10:
            print(f"Pinbar检测失败: 数据不足，需要至少10根K线")
            return False
            
        latest = data.iloc[-1]
        
        # 计算实体和影线长度
        body = abs(latest['close'] - latest['open'])
        total_range = latest['high'] - latest['low']
        
        # 避免除零错误
        if total_range == 0:
            print(f"Pinbar检测失败: K线无波动")
            return False
        
        # 计算价格位置 - 使用最近10根K线的高低点范围
        recent_high = data['high'].tail(10).max()
        recent_low = data['low'].tail(10).min()
        recent_range = recent_high - recent_low
        
        # 避免除零错误
        if recent_range == 0:
            print(f"Pinbar检测失败: 最近10根K线无波动")
            return False
        
        # 计算当前K线收盘价在最近10根K线中的相对位置（0-1）
        # 0表示最低，1表示最高
        price_position = (latest['close'] - recent_low) / recent_range
        
        # 计算最近20根K线的高低点
        recent_20_high = data['high'].tail(20).max()
        recent_20_low = data['low'].tail(20).min()
        
        # 添加调试信息
        print(f"\n=== Pinbar检测调试信息 ===")
        print(f"K线数据: 开盘={latest['open']}, 收盘={latest['close']}, 最高={latest['high']}, 最低={latest['low']}")
        print(f"实体长度: {body}, 总范围: {total_range}")
        print(f"价格位置: {price_position:.2f}")
        print(f"最近20根K线最高价: {recent_20_high}, 最近20根K线最低价: {recent_20_low}")
        
        # 根据严格/宽松模式设置参数
        if strict:
            body_ratio_threshold = 0.33
            shadow_ratio_threshold = 2.0
            bottom_threshold = 0.4
            top_threshold = 0.6
            print(f"严格模式: 实体比例阈值={body_ratio_threshold}, 影线比例阈值={shadow_ratio_threshold}")
        else:
            body_ratio_threshold = 0.5
            shadow_ratio_threshold = 1.5
            bottom_threshold = 0.45
            top_threshold = 0.55
            print(f"宽松模式: 实体比例阈值={body_ratio_threshold}, 影线比例阈值={shadow_ratio_threshold}")
        
        # 计算实体比例
        body_ratio = body / total_range
        print(f"实体比例={body_ratio:.2f}, 需要 < {body_ratio_threshold}")
        
        # 判断是否为看涨Pinbar
        is_bullish = latest['close'] > latest['open']
        
        if is_bullish:
            # 看涨Pinbar计算
            upper_shadow = latest['high'] - latest['close']
            lower_shadow = latest['open'] - latest['low']
            
            print(f"看涨Pinbar检查:")
            print(f"上影线: {upper_shadow}, 下影线: {lower_shadow}")
            
            # 价格位置条件
            is_bottom = price_position < bottom_threshold
            print(f"是否在底部区域: {is_bottom}, 价格位置需 < {bottom_threshold}")
            
            # 新条件1：上影线不能超过实体长度
            upper_shadow_condition = upper_shadow <= body
            print(f"上影线 <= 实体长度: {upper_shadow_condition}, 上影线={upper_shadow}, 实体={body}")
            
            # 新条件2：最低价格需要是最近10根K线的最低价（考虑浮点数精度问题）
            is_recent_lowest = latest['low'] <= recent_10_low * 1.0001  # 允许微小误差
            print(f"最低价是否为最近10根最低: {is_recent_lowest}, 当前最低={latest['low']}, 参考最低={recent_10_low}")
            
            # 看涨Pinbar的形态条件：小实体，长下影线
            pinbar_pattern = body_ratio < body_ratio_threshold and lower_shadow > body * shadow_ratio_threshold
            print(f"形态条件满足: {pinbar_pattern}")
            
            # 综合判断
            result = pinbar_pattern and is_bottom and upper_shadow_condition and is_recent_lowest
            print(f"最终看涨Pinbar检测结果: {result}")
        else:
            # 看跌Pinbar计算
            upper_shadow = latest['high'] - latest['open']
            lower_shadow = latest['close'] - latest['low']
            
            print(f"看跌Pinbar检查:")
            print(f"上影线: {upper_shadow}, 下影线: {lower_shadow}")
            
            # 价格位置条件
            is_top = price_position > top_threshold
            print(f"是否在顶部区域: {is_top}, 价格位置需 > {top_threshold}")
            
            # 新条件1：下影线不能超过实体长度
            lower_shadow_condition = lower_shadow <= body
            print(f"下影线 <= 实体长度: {lower_shadow_condition}, 下影线={lower_shadow}, 实体={body}")
            
            # 新条件2：最高价格需要是最近10根K线的最高价（考虑浮点数精度问题）
            is_recent_highest = latest['high'] >= recent_10_high * 0.9999  # 允许微小误差
            print(f"最高价是否为最近10根最高: {is_recent_highest}, 当前最高={latest['high']}, 参考最高={recent_10_high}")
            
            # 看跌Pinbar的形态条件：小实体，长上影线
            pinbar_pattern = body_ratio < body_ratio_threshold and upper_shadow > body * shadow_ratio_threshold
            print(f"形态条件满足: {pinbar_pattern}")
            
            # 综合判断
            result = pinbar_pattern and is_top and lower_shadow_condition and is_recent_highest
            print(f"最终看跌Pinbar检测结果: {result}")
        
        return result
    
    def detect_engulfing(self, data, strict=True):
        """检测吞没形态，strict=False时放宽条件"""
        # 至少需要20根K线来检查极值
        if len(data) < 20:
            print(f"吞没形态检测失败: 数据不足，需要至少20根K线")
            return False
            
        current = data.iloc[-1]
        previous = data.iloc[-2]
        
        # 检查是否颜色相反
        if (current['close'] > current['open'] and previous['close'] < previous['open']) or \
           (current['close'] < current['open'] and previous['close'] > previous['open']):
            
            # 计算实体长度
            current_body = abs(current['close'] - current['open'])
            previous_body = abs(previous['close'] - previous['open'])
            
            # 计算最近20根K线的高低点
            recent_20_high = data['high'].tail(20).max()
            recent_20_low = data['low'].tail(20).min()
            
            # 添加调试信息
            print(f"\n=== 吞没形态检测调试信息 ===")
            print(f"当前K线: 开盘={current['open']}, 收盘={current['close']}, 最高={current['high']}, 最低={current['low']}")
            print(f"前一根K线: 开盘={previous['open']}, 收盘={previous['close']}, 最高={previous['high']}, 最低={previous['low']}")
            print(f"实体长度: 当前={current_body}, 前一根={previous_body}")
            print(f"最近20根K线最高价: {recent_20_high}, 最近20根K线最低价: {recent_20_low}")
            
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
                # 看涨吞没的最低价必须是最近20根K的最低价格（考虑浮点数精度）
                price_condition = current['low'] <= recent_20_low * 1.0001
                print(f"看涨吞没价格条件: 当前最低价 <= 最近20根K线最低价: {price_condition}")
                return basic_condition and price_condition
            else:  # 看跌吞没
                # 看跌吞没的最高价必须是最近20根K的最高价格（考虑浮点数精度）
                price_condition = current['high'] >= recent_20_high * 0.9999
                print(f"看跌吞没价格条件: 当前最高价 >= 最近20根K线最高价: {price_condition}")
                
                # 修正看跌吞没的收盘价条件：当前收盘低于前K线中点价格
                mid_price_condition = current['close'] < (previous['open'] + previous['close']) / 2
                print(f"看跌吞没收盘价条件: 当前收盘 < 前K线中点价格: {mid_price_condition}")
                
                return basic_condition and price_condition and mid_price_condition
        
        return False
    
    def detect_morning_evening_star(self, data):
        """检测晨星/昏星形态"""
        # 至少需要20根K线来检查极值
        if len(data) < 20:
            print(f"星形态检测失败: 数据不足，需要至少20根K线")
            return False
            
        first = data.iloc[-3]
        second = data.iloc[-2]
        third = data.iloc[-1]
        
        # 计算最近10根K线的高低点
        recent_10_high = data['high'].tail(10).max()
        recent_10_low = data['low'].tail(10).min()
        
        # 计算组合K线的高低点
        pattern_low = min(first['low'], second['low'], third['low'])
        pattern_high = max(first['high'], second['high'], third['high'])
        
        # 添加调试信息
        print(f"\n=== 星形态检测调试信息 ===")
        print(f"第一根K线: 开盘={first['open']}, 收盘={first['close']}, 最高={first['high']}, 最低={first['low']}")
        print(f"第二根K线: 开盘={second['open']}, 收盘={second['close']}, 最高={second['high']}, 最低={second['low']}")
        print(f"第三根K线: 开盘={third['open']}, 收盘={third['close']}, 最高={third['high']}, 最低={third['low']}")
        print(f"组合K线最低点: {pattern_low}, 组合K线最高点: {pattern_high}")
        print(f"最近10根K线最高价: {recent_10_high}, 最近10根K线最低价: {recent_10_low}")
        
        # 晨星条件
        if (first['close'] < first['open'] and  # 第一根是阴线
            abs(second['close'] - second['open']) < abs(first['close'] - first['open']) * 0.5 and  # 第二根是小实体
            third['close'] > third['open'] and  # 第三根是阳线
            third['close'] > (first['open'] + first['close']) / 2):  # 第三根收盘价超过第一根中点
            
            # 黎明星组合K里的最低价格必须是最近20根k的最低价（考虑浮点数精度）
            price_condition = pattern_low <= recent_20_low * 1.0001
            print(f"黎明星价格条件: 组合K线最低点 <= 最近20根K线最低价: {price_condition}")
            return price_condition
        
        # 昏星条件
        elif (first['close'] > first['open'] and  # 第一根是阳线
              abs(second['close'] - second['open']) < abs(first['close'] - first['open']) * 0.5 and  # 第二根是小实体
              third['close'] < third['open'] and  # 第三根是阴线
              third['close'] < (first['open'] + first['close']) / 2):  # 第三根收盘价低于第一根中点
            
            # 黄昏星组合K里的最高价格必须是最近20根k的最高价（考虑浮点数精度）
            price_condition = pattern_high >= recent_20_high * 0.9999  # 允许微小误差
            print(f"黄昏星价格条件: 组合K线最高点 >= 最近20根K线最高价: {price_condition}")
            return price_condition
        
        return False
    
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
    
    def send_dingtalk_notification(self, message, title="价格行为分析提醒"):
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
        print("功能：筛选USDT合约成交额前50名币种，按成交额排序，检测4小时MACD(DIF)状态（多头>0/空头<0）和1小时裸K信号（Pinbar、吞没、黄昏星/黎明星）")
        print("每小时整点自动运行一次，并将结果推送到电报")
        print("每5分钟检查一次持仓盈亏率")
        
        # 首次运行一次
        self.execute_filter()
        
        # 设置定时任务，只在每小时的0分运行
        print("\n定时任务已设置，将在每小时的整点自动运行...")
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
        
        # 如果有警报，只保留日志记录
        if has_alerts:
            print("检测到持仓盈亏警报")
            print(f"警报内容: {alert_content}")
        else:
            print("本次检查未发现需要提醒的情况")
        
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 5分钟持仓盈亏检测完成")
    
    def get_top_usdt_futures(self, top_n=100):
        """获取成交额前N名的USDT合约币种及其成交额"""
        try:
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
            
            # 使用币安永续合约ticker API获取所有合约的成交额数据
            url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
            response = session.get(
                url,
                timeout=15,
                verify=False  # 禁用SSL验证以解决证书问题
            )
            
            if response.status_code == 200:
                tickers = response.json()
                
                # 筛选USDT合约并提取币种和成交额
                usdt_pairs = []
                for ticker in tickers:
                    symbol = ticker.get('symbol')
                    if symbol and symbol.endswith('USDT'):
                        # 获取24小时成交额
                        volume = float(ticker.get('quoteVolume', 0))
                        usdt_pairs.append((symbol, volume))
                
                # 按成交额降序排序
                usdt_pairs.sort(key=lambda x: x[1], reverse=True)
                
                # 返回前N个币种
                return usdt_pairs[:top_n]
            else:
                print(f"获取合约数据失败: HTTP {response.status_code}")
                return []
        except Exception as e:
            print(f"获取合约数据时出错: {e}")
            import traceback
            traceback.print_exc()
            return []
        finally:
            # 确保会话关闭
            if 'session' in locals():
                session.close()
                
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
                self.send_dingtalk_notification(push_content, title=f"价格行为分析 - 币安 {symbol} 加密货币")
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
        
        # 获取成交额前50名的USDT合约币种及其成交额
        top_currencies = self.get_top_usdt_futures(top_n=50)
        
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
                    # 接收分析结果，包含是否满足买入/卖出信号、裸K形态和确认K类型
                    symbol, macd_status, is_golden_cross, four_hour_macd_value, pattern_type, four_hour_macd_bullish, is_buy_signal, is_sell_signal, cross_interval, confirmation_candle_type = future.result()
                    
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
                        
                        # 存储分析结果，包含裸K形态信息和确认K类型
                        analysis_results[symbol] = (symbol, macd_status, is_golden_cross, four_hour_macd_value, pattern_type, four_hour_macd_bullish, is_buy_signal, is_sell_signal, cross_interval, confirmation_candle_type)
                        
                        # 打印详细信息 - 只有在满足买入/卖出信号时才显示交叉信息
                        if signal == "买入信号" or signal == "卖出信号":
                            print(f"{symbol:<15} {macd_status:<15} {cross_interval:<12} {macd_cross_status:<15} {signal:<25}")
                        else:
                            # 不满足信号条件时，不显示交叉状态
                            print(f"{symbol:<15} {macd_status:<15} {cross_interval:<12} {'-':<15} {signal:<25}")
                    
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
        
        # 重新构建包含分析周期和确认K类型的信号列表
        for symbol, status, pattern_name, m_val, pattern_type in buy_signal_symbols:
            if symbol in analysis_results:
                result = analysis_results[symbol]
                if len(result) >= 10:
                    cross_interval = result[8]
                    confirmation_type = result[9]
                    buy_signal_1h.append((symbol, status, pattern_name, m_val, cross_interval, pattern_type, confirmation_type))

        for symbol, status, pattern_name, m_val, pattern_type in sell_signal_symbols:
            if symbol in analysis_results:
                result = analysis_results[symbol]
                if len(result) >= 10:
                    cross_interval = result[8]
                    confirmation_type = result[9]
                    sell_signal_1h.append((symbol, status, pattern_name, m_val, cross_interval, pattern_type, confirmation_type))
        
        # 对分类后的信号列表进行排序
        buy_signal_1h.sort(key=lambda x: x[3] if x[3] is not None else float('inf'))
        sell_signal_1h.sort(key=lambda x: x[3] if x[3] is not None else float('-inf'), reverse=True)
        
        # 生成钉钉通知内容
        dingtalk_content = f"### 加密货币信号提醒 - 币安 - {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        
        # 输出裸K信号的买入信号（根据市值排名使用不同周期）
        if buy_signal_1h:
            print("\n⚠️  满足条件的买入信号币种：")
            print("\n价格行为买入信号：")
            for symbol, status, pattern_name, _, _, _, _ in buy_signal_1h:
                print(f"   • {symbol} ({status}) - {pattern_name}")
            
            # 添加到钉钉通知
            dingtalk_content += "#### 🟢 价格行为多头信号：\n"
            for symbol, macd_status, pattern_name, _, cross_interval, _, confirmation_type in buy_signal_1h:
                # 检查是否为alpha板块币种
                alpha_tag = " [ALPHA]" if symbol in self.alpha_coins else ""
                dingtalk_content += f"- {symbol}{alpha_tag} ({macd_status}) - {cross_interval}{pattern_name} - 确认K: {confirmation_type}\n"
        
        # 输出裸K信号的卖出信号（根据市值排名使用不同周期）
        if sell_signal_1h:
            print("\n⚠️  满足条件的卖出信号币种：")
            print("\n价格行为卖出信号：")
            for symbol, status, pattern_name, _, _, _, _ in sell_signal_1h:
                print(f"   • {symbol} ({status}) - {pattern_name}")
            
            # 添加到钉钉通知
            dingtalk_content += "\n#### 🔴 价格行为空头信号：\n"
            for symbol, macd_status, pattern_name, _, cross_interval, _, confirmation_type in sell_signal_1h:
                # 检查是否为alpha板块币种
                alpha_tag = " [ALPHA]" if symbol in self.alpha_coins else ""
                dingtalk_content += f"- {symbol}{alpha_tag} ({macd_status}) - {cross_interval}{pattern_name} - 确认K: {confirmation_type}\n"
        
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
                # 检查是否为alpha板块币种
                alpha_tag = " [ALPHA]" if signal['symbol'] in self.alpha_coins else ""
                dingtalk_content += f"- **{signal['symbol']}{alpha_tag}** ({position_text}) - {signal['signal_type']} - {signal['trigger_condition']}\n"
                print(f"   • {signal['symbol']}{alpha_tag} ({position_text}) - {signal['signal_type']} - {signal['trigger_condition']}")
        
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
            # 发送Telegram通知 - 已屏蔽
            # try:
            #     # 同时发送到电报群
            #     self.send_telegram_notification(dingtalk_content, "加密货币交易信号提醒")
            # except Exception as e:
            #     print(f"电报通知发送失败: {e}")
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
            success = analyzer.send_dingtalk_notification(push_content, title=f"价格行为分析 - 币安 {symbol} 加密货币")
            
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



def check_btc_signal():
    """专门检查BTC的最新信号"""
    print("==== 正在查询BTCUSDT的最新信号 ====")
    
    # 配置参数
    DINGTALK_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=02fcc926215099c4d0315e453e86aa6d9af934ad538de89b13f67bc3d131ee07"  # 请在此处填入您的钉钉webhook地址
    
    # 创建分析器实例
    analyzer = CryptoAnalyzer(
        dingtalk_webhook=DINGTALK_WEBHOOK,
        telegram_bot_token=None,
        telegram_chat_id=None
    )
    
    # 直接分析BTCUSDT
    symbol = "BTCUSDT"
    print(f"🔍 开始分析 {symbol}...")
    
    try:
        # 调用分析单个币种的方法
        result = analyzer.analyze_single_currency(symbol, 1)
        
        if result:
            symbol, macd_status, is_golden_cross, four_hour_macd_value, pattern_type, four_hour_macd_bullish, is_buy_signal, is_sell_signal, cross_interval = result
            
            print(f"\n📊 {symbol} 信号分析结果:")
            print(f"   - 大周期状态: {macd_status} (DIF: {four_hour_macd_value:.6f})")
            print(f"   - 小周期形态: {pattern_type}")
            print(f"   - 买入信号: {'✅ 是' if is_buy_signal else '❌ 否'}")
            print(f"   - 卖出信号: {'✅ 是' if is_sell_signal else '❌ 否'}")
            
            if is_buy_signal:
                pattern_name = analyzer.get_pattern_name(pattern_type) if hasattr(analyzer, 'get_pattern_name') else pattern_type
                print(f"\n📈 BTCUSDT当前信号: 买入信号 - 大周期多头 + {cross_interval}{pattern_name}")
            elif is_sell_signal:
                pattern_name = analyzer.get_pattern_name(pattern_type) if hasattr(analyzer, 'get_pattern_name') else pattern_type
                print(f"\n📉 BTCUSDT当前信号: 卖出信号 - 大周期空头 + {cross_interval}{pattern_name}")
            else:
                print("\n⚠️ BTCUSDT当前无交易信号")
        else:
            print("❌ 无法获取BTCUSDT的分析结果")
    
    except Exception as e:
        print(f"❌ 分析BTCUSDT时出错: {str(e)}")
    
    print("==== 查询结束 ====")

if __name__ == "__main__":
    import sys
    
    # 检查是否有特殊参数
    if len(sys.argv) > 1 and sys.argv[1] == "--check-btc":
        # 仅检查BTC信号
        check_btc_signal()
    else:
        # 正常运行
        DINGTALK_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=02fcc926215099c4d0315e453e86aa6d9af934ad538de89b13f67bc3d131ee07"  # 请在此处填入您的钉钉webhook地址
        
        analyzer = CryptoAnalyzer(
            dingtalk_webhook=DINGTALK_WEBHOOK,
            telegram_bot_token=None,
            telegram_chat_id=None
        )
        analyzer.run()