import time
import schedule
from crypto_multiperiod_analysis import *

# 运行15分钟周期的MACD分析系统

def run_analysis():
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 开始15分钟周期MACD分析...")
    
    try:
        # 初始化分析器
        analyzer = CryptoMultiperiodAnalyzer()
        
        # 获取交易对列表
        symbols = analyzer.get_top_usdt_futures(limit=100)
        
        if not symbols:
            print("警告：未获取到交易对列表")
            return
        
        print(f"获取到 {len(symbols)} 个交易对")
        
        # 对每个币种进行分析
        results = []
        for symbol in symbols:
            try:
                print(f"分析 {symbol}...")
                # 分析单个币种，现在使用15分钟周期
                result = analyzer.analyze_single_currency(symbol)
                if result:
                    results.append(result)
                # 避免请求过快
                time.sleep(0.1)
            except Exception as e:
                print(f"分析 {symbol} 出错: {e}")
        
        # 处理分析结果
        if results:
            analyzer.process_results(results)
        
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 15分钟周期分析完成！")
        
    except Exception as e:
        print(f"分析过程中出错: {e}")
        import traceback
        traceback.print_exc()

def main():
    print("========== 15分钟周期MACD分析系统启动 ==========")
    print(f"启动时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("系统设置:")
    print("- 小周期: 15分钟")
    print("- 大周期: 4小时")
    print("- 买入信号: 0轴下金叉")
    print("- 卖出信号: 0轴上死叉")
    print("=========================================")
    
    # 立即运行一次分析
    run_analysis()
    
    # 设置定时任务，每15分钟运行一次
    schedule.every(15).minutes.do(run_analysis)
    
    print("定时任务已设置，每15分钟运行一次分析")
    print("按 Ctrl+C 停止系统")
    
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n系统已停止")

if __name__ == "__main__":
    main()