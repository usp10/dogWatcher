import sys
import crypto_multiperiod_analysis
import pandas as pd

if __name__ == "__main__":
    print("开始调试NEARUSDT的MACD数据...")
    
    # 从crypto_multiperiod_analysis.py中获取必要的配置
    DINGTALK_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=02fcc926215099c4d0315e453e86aa6d9af934ad538de89b13f67bc3d131ee07"
    TELEGRAM_BOT_TOKEN = "7708753284:AAEYV4WRHfJQR4tCb5uQ8ye-T29IEf6X9qE"
    TELEGRAM_CHAT_ID = "-4611171283"
    
    # 创建分析器实例
    analyzer = crypto_multiperiod_analysis.CryptoAnalyzer(
        dingtalk_webhook=DINGTALK_WEBHOOK,
        telegram_bot_token=TELEGRAM_BOT_TOKEN,
        telegram_chat_id=TELEGRAM_CHAT_ID
    )
    
    # 分析NEARUSDT
    symbol = "NEARUSDT"
    print(f"分析币种: {symbol}")
    
    # 获取1小时和4小时数据
    hourly_data = analyzer.get_futures_klines(symbol, '1h', limit=100)
    four_hour_data = analyzer.get_futures_klines(symbol, '4h', limit=50)
    
    if hourly_data is None or four_hour_data is None:
        print("无法获取数据")
        sys.exit(1)
    
    # 计算MACD
    hourly_macd_line, hourly_macd_signal, _ = analyzer.calculate_macd(hourly_data)
    four_hour_macd_line, four_hour_macd_signal, _ = analyzer.calculate_macd(four_hour_data)
    
    # 打印大周期MACD状态
    four_hour_macd_bullish = four_hour_macd_line.iloc[-1] > four_hour_macd_signal.iloc[-1]
    print(f"大周期(4h)MACD方向: {'多头' if four_hour_macd_bullish else '空头'}")
    print(f"大周期最新MACD值: {four_hour_macd_line.iloc[-1]}")
    print(f"大周期最新信号线值: {four_hour_macd_signal.iloc[-1]}")
    
    # 检测小周期MACD交叉
    macd_cross = analyzer.detect_macd_cross(hourly_macd_line, hourly_macd_signal)
    is_golden_cross = macd_cross == 'golden_cross'
    print(f"小周期(1h)MACD交叉状态: {macd_cross}")
    print(f"是否金叉: {is_golden_cross}")
    
    # 打印最近的MACD值和信号线值
    print("\n最近的MACD数据:")
    for i in range(5):
        idx = -5 + i
        if abs(idx) <= len(hourly_macd_line):
            print(f"索引{idx}: MACD={hourly_macd_line.iloc[idx]:.6f}, Signal={hourly_macd_signal.iloc[idx]:.6f}")
    
    # 检查买入信号并打印详细信息
    print("\n检查买入信号:")
    is_buy_signal = False
    if four_hour_macd_bullish and is_golden_cross:
        # 手动执行check_buy_signal的逻辑并打印中间结果
        close_price_a = hourly_data['close'].iloc[-2]  # 金叉A的收盘价
        macd_value_a = hourly_macd_line.iloc[-2]  # 金叉A的DIF值
        
        print(f"金叉A信息: 收盘价={close_price_a}, MACD值={macd_value_a}")
        print(f"金叉A的MACD值是否在0轴上: {macd_value_a > 0}")
        
        # 寻找上一个金叉B
        last_golden_cross_idx = None
        for i in range(len(hourly_macd_line) - 6, 0, -1):
            if i-1 < 0:
                continue
            
            cross_at_i = (hourly_macd_line.iloc[i-1] < hourly_macd_signal.iloc[i-1] and 
                         hourly_macd_line.iloc[i] > hourly_macd_signal.iloc[i])
            
            if cross_at_i:
                print(f"找到金叉候选，索引={i}, MACD值={hourly_macd_line.iloc[i]:.6f}")
                print(f"该金叉MACD值是否小于0: {hourly_macd_line.iloc[i] < 0}")
                print(f"该金叉MACD值是否小于-0.001: {hourly_macd_line.iloc[i] < -0.001}")
                
                if cross_at_i and hourly_macd_line.iloc[i] < -0.001:
                    last_golden_cross_idx = i
                    print(f"找到符合条件的金叉B，索引={i}")
                    break
        
        if last_golden_cross_idx is not None:
            close_price_b = hourly_data['close'].iloc[last_golden_cross_idx]
            price_diff_pct = abs(close_price_a - close_price_b) / close_price_b * 100
            
            print(f"金叉B信息: 索引={last_golden_cross_idx}, 收盘价={close_price_b}, MACD值={hourly_macd_line.iloc[last_golden_cross_idx]:.6f}")
            print(f"价格差异百分比: {price_diff_pct:.2f}%")
            
            # 检查价格条件
            if macd_value_a > 0:
                price_condition = close_price_a > close_price_b and price_diff_pct >= 0.2
                print(f"价格条件(0轴上): close_price_a > close_price_b 且 差异>=0.2%: {price_condition}")
            else:
                price_condition = close_price_a < close_price_b and price_diff_pct >= 0.2
                print(f"价格条件(0轴下): close_price_a < close_price_b 且 差异>=0.2%: {price_condition}")
            
            is_buy_signal = price_condition
    
    print(f"\n最终买入信号: {is_buy_signal}")
    print("调试完成。")