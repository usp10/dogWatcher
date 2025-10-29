import sys
import crypto_multiperiod_analysis

if __name__ == "__main__":
    print("执行一次筛选分析以验证修复...")
    
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
    
    # 只执行一次筛选分析，不启动定时任务
    analyzer.execute_filter()
    
    print("筛选分析完成，修复验证结束。")