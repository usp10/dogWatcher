import requests
import time
from datetime import datetime

# 币种信息映射表 - 仅包含USDT交易对
crypto_info = {
    'BTCUSDT': { 'name': '比特币', 'icon': '₿' },
    'ETHUSDT': { 'name': '以太坊', 'icon': 'Ξ' },
    'SOLUSDT': { 'name': '索拉纳', 'icon': '◎' },
    'ADAUSDT': { 'name': '卡尔达诺', 'icon': '₳' },
    'XRPUSDT': { 'name': '瑞波币', 'icon': '✕' },
    'DOGEUSDT': { 'name': '狗狗币', 'icon': 'Ð' },
    'MATICUSDT': { 'name': 'Polygon', 'icon': '⟠' },
    'DOTUSDT': { 'name': '波卡', 'icon': '⟡' },
    'LINKUSDT': { 'name': 'Chainlink', 'icon': '⚓' },
    'LTCUSDT': { 'name': '莱特币', 'icon': 'Ł' },
    'AVAXUSDT': { 'name': 'Avalanche', 'icon': '⧫' },
    'UNIUSDT': { 'name': 'Uniswap', 'icon': '⛏' },
    'BCHUSDT': { 'name': '比特币现金', 'icon': 'BCH' },
    'XMRUSDT': { 'name': '门罗币', 'icon': 'ɱ' },
    'ATOMUSDT': { 'name': 'Cosmos', 'icon': '⚛' },
    'ETCUSDT': { 'name': '以太经典', 'icon': '⟠' },
    'FILUSDT': { 'name': 'Filecoin', 'icon': '⨎' },
    'TRXUSDT': { 'name': '波场', 'icon': 'TRX' },
    'ICPUSDT': { 'name': 'Internet Computer', 'icon': '⚡' },
    'NEARUSDT': { 'name': 'NEAR Protocol', 'icon': '⟠' },
    'APTUSDT': { 'name': 'Aptos', 'icon': '⧫' },
    'SANDUSDT': { 'name': 'Sandbox', 'icon': 'SAND' },
    'MANAUSDT': { 'name': 'Decentraland', 'icon': 'MANA' },
    'ALGOUSDT': { 'name': 'Algorand', 'icon': '⚛' },
    'AXSUSDT': { 'name': 'Axie Infinity', 'icon': '⚔' },
    'AAVEUSDT': { 'name': 'Aave', 'icon': 'AAVE' },
    'MKRUSDT': { 'name': 'MakerDAO', 'icon': 'MKR' },
    'CRVUSDT': { 'name': 'Curve DAO', 'icon': 'CRV' },
    'ZECUSDT': { 'name': 'Zcash', 'icon': 'ⓩ' },
    'COMPUSDT': { 'name': 'Compound', 'icon': 'COMP' },
    'GRTUSDT': { 'name': 'The Graph', 'icon': 'GRT' },
    'ENSUSDT': { 'name': 'Ethereum Name Service', 'icon': 'ENS' },
    'SNXUSDT': { 'name': 'Synthetix', 'icon': 'SNX' },
    'YFIUSDT': { 'name': 'Yearn Finance', 'icon': 'YFI' },
    'CELRUSDT': { 'name': 'Celer Network', 'icon': 'CELR' },
    'CELOUSDT': { 'name': 'Celo', 'icon': 'CELO' },
    'CROUSDT': { 'name': 'Crypto.com Coin', 'icon': 'CRO' },
    'DASHUSDT': { 'name': '达世币', 'icon': 'DASH' },
    'KNCUSDT': { 'name': 'Kyber Network', 'icon': 'KNC' },
    'LRCUSDT': { 'name': 'Loopring', 'icon': 'LRC' },
    'QNTUSDT': { 'name': 'Quant', 'icon': 'QNT' },
    'RUNEUSDT': { 'name': 'THORChain', 'icon': 'RUNE' },
    'SUSHIUSDT': { 'name': 'SushiSwap', 'icon': 'SUSHI' },
    'THETAUSDT': { 'name': 'Theta Network', 'icon': 'THETA' },
    'UMAUSDT': { 'name': 'UMA', 'icon': 'UMA' },
    'VETUSDT': { 'name': 'VeChain', 'icon': 'VET' },
    'WAVESUSDT': { 'name': 'Waves', 'icon': 'WAVES' },
    'ZILUSDT': { 'name': 'Zilliqa', 'icon': 'ZIL' }
}

# 全局变量
is_filter_running = False
is_filter_cancelled = False

# 获取K线数据 - 仅支持USDT交易对
def fetch_klines_data(symbol, interval='1h', limit=None):
    max_retries = 2  # 最大重试次数
    retries = 0
    last_error = None
    
    while retries < max_retries:
        try:
            # 根据周期设置默认的limit值
            default_limit = 168  # 1周 * 24小时/天 = 168个1小时K线
            if interval == '15m':
                default_limit = 672  # 1周 * 24小时/天 * 4个15分钟K线
            if interval == '4h':
                default_limit = 42   # 1周 * 6个4小时K线/天
            
            actual_limit = limit or default_limit
            
            # 使用现货API
            api_endpoint = 'https://api.binance.com/api/v3/klines'
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            params = {
                'symbol': symbol,
                'interval': interval,
                'limit': actual_limit
            }
            
            response = requests.get(api_endpoint, params=params, headers=headers, timeout=10)
            response.raise_for_status()  # 检查请求是否成功
            
            # 处理数据
            klines = response.json()
            if not isinstance(klines, list) or len(klines) == 0:
                raise ValueError(f'获取{symbol}的K线数据为空')
            
            data = []
            for kline in klines:
                data.append({
                    'timestamp': datetime.fromtimestamp(kline[0] / 1000),
                    'open': float(kline[1]),
                    'high': float(kline[2]),
                    'low': float(kline[3]),
                    'close': float(kline[4]),
                    'volume': float(kline[5])
                })
            
            return data
        except Exception as error:
            retries += 1
            last_error = error
            if retries >= max_retries:
                raise last_error
            time.sleep(1)  # 重试前等待1秒

# 判断是否为高点
def is_high_point(data, index, min_distance=3):
    # 检查是否在数据范围内
    if index < min_distance or index >= len(data) - min_distance:
        return False
    
    current_high = data[index]['high']
    
    # 检查前后min_distance个K线的最高点是否都小于当前最高点
    for i in range(1, min_distance + 1):
        if data[index - i]['high'] > current_high or data[index + i]['high'] > current_high:
            return False
    
    return True

# 判断是否为低点
def is_low_point(data, index, min_distance=3):
    # 检查是否在数据范围内
    if index < min_distance or index >= len(data) - min_distance:
        return False
    
    current_low = data[index]['low']
    
    # 检查前后min_distance个K线的最低点是否都大于当前最低点
    for i in range(1, min_distance + 1):
        if data[index - i]['low'] < current_low or data[index + i]['low'] < current_low:
            return False
    
    return True

# 识别波浪点 - 高低点识别
def identify_wave_points(data, min_distance=3):
    points = []
    
    # 第一阶段：初步识别所有高低点
    for i in range(min_distance, len(data) - min_distance):
        if is_high_point(data, i, min_distance):
            points.append({
                'index': i,
                'price': data[i]['high'],
                'type': 'high',
                'timestamp': data[i]['timestamp']
            })
        elif is_low_point(data, i, min_distance):
            points.append({
                'index': i,
                'price': data[i]['low'],
                'type': 'low',
                'timestamp': data[i]['timestamp']
            })
    
    # 第二阶段：过滤过于接近的点
    if len(points) < 2:
        return points
    
    filtered_points = [points[0]]
    for i in range(1, len(points)):
        prev_point = filtered_points[-1]
        curr_point = points[i]
        
        # 如果当前点和前一个点类型相同，保留价格更高/更低的那个
        if prev_point['type'] == curr_point['type']:
            if prev_point['type'] == 'high':
                # 高点保留价格更高的
                if curr_point['price'] > prev_point['price']:
                    filtered_points.pop()
                    filtered_points.append(curr_point)
            else:
                # 低点保留价格更低的
                if curr_point['price'] < prev_point['price']:
                    filtered_points.pop()
                    filtered_points.append(curr_point)
        else:
            filtered_points.append(curr_point)
    
    # 第三阶段：再次检查相邻点之间的距离是否足够
    final_points = []
    min_points_distance = max(2, min_distance // 2)
    
    for point in filtered_points:
        if not final_points:
            final_points.append(point)
        else:
            last_point = final_points[-1]
            if abs(point['index'] - last_point['index']) >= min_points_distance:
                final_points.append(point)
    
    return final_points

# 检查是否有低位五浪模式
def has_five_wave_low_pattern(points):
    if len(points) < 6:
        return False
    
    # 按照索引排序
    sorted_points = sorted(points, key=lambda p: p['index'])
    
    # 检查是否有6个点且类型序列为低-高-低-高-低-高
    if len(sorted_points) < 6:
        return False
    
    # 寻找符合低位五浪模式的连续6个点
    for i in range(len(sorted_points) - 5):
        pattern_points = sorted_points[i:i+6]
        
        # 检查点类型序列：低-高-低-高-低-高
        if (pattern_points[0]['type'] == 'low' and 
            pattern_points[1]['type'] == 'high' and 
            pattern_points[2]['type'] == 'low' and 
            pattern_points[3]['type'] == 'high' and 
            pattern_points[4]['type'] == 'low' and 
            pattern_points[5]['type'] == 'high'):
            
            # 检查低点是否逐步抬高
            if (pattern_points[2]['price'] > pattern_points[0]['price'] and 
                pattern_points[4]['price'] > pattern_points[2]['price']):
                
                # 检查高点是否逐步抬高
                if (pattern_points[1]['price'] < pattern_points[3]['price'] and 
                    pattern_points[3]['price'] < pattern_points[5]['price']):
                    
                    # 验证第五浪的最低点
                    if pattern_points[4]['price'] > pattern_points[0]['price']:
                        return True
    
    return False

# 检查准备突破五浪结构模式
def check_low_pattern(klines_data, symbol):
    # 识别波浪点
    points = identify_wave_points(klines_data)
    
    # 检查是否有低位五浪模式
    if not has_five_wave_low_pattern(points):
        return None
    
    # 寻找符合低位五浪模式的连续6个点
    sorted_points = sorted(points, key=lambda p: p['index'])
    five_wave_pattern = None
    
    for i in range(len(sorted_points) - 5):
        pattern_points = sorted_points[i:i+6]
        
        # 检查点类型序列：低-高-低-高-低-高
        if (pattern_points[0]['type'] == 'low' and 
            pattern_points[1]['type'] == 'high' and 
            pattern_points[2]['type'] == 'low' and 
            pattern_points[3]['type'] == 'high' and 
            pattern_points[4]['type'] == 'low' and 
            pattern_points[5]['type'] == 'high'):
            
            # 检查低点是否逐步抬高
            if (pattern_points[2]['price'] > pattern_points[0]['price'] and 
                pattern_points[4]['price'] > pattern_points[2]['price']):
                
                # 检查高点是否逐步抬高
                if (pattern_points[1]['price'] < pattern_points[3]['price'] and 
                    pattern_points[3]['price'] < pattern_points[5]['price']):
                    
                    # 验证第五浪的最低点
                    if pattern_points[4]['price'] > pattern_points[0]['price']:
                        five_wave_pattern = pattern_points
                        break
    
    if not five_wave_pattern:
        return None
    
    # 获取五浪结构的最高价（最后一个高点）
    structure_high = five_wave_pattern[5]['price']
    
    # 获取五浪结构形成后的K线数据
    structure_end_index = five_wave_pattern[5]['index']
    后续_klines = klines_data[structure_end_index:]
    
    # 检查是否所有后续K线的收盘价都低于结构最高价
    all_below = all(kline['close'] < structure_high for kline in 后续_klines)
    
    # 检查是否有收盘价高于结构最高价（已突破）
    any_above = any(kline['close'] > structure_high for kline in 后续_klines)
    
    # 计算模式强度
    price_diff_percent = ((structure_high - five_wave_pattern[0]['price']) / five_wave_pattern[0]['price']) * 100
    strength = min(100, max(0, price_diff_percent))
    
    # 获取当前价格（最新K线的收盘价）
    current_price = klines_data[-1]['close'] if klines_data else 0
    
    # 判断模式类型
    pattern_type = '已突破五浪结构' if any_above else '准备突破五浪结构'
    
    if all_below:
        return {
            'symbol': symbol,
            'name': crypto_info[symbol]['name'],
            'icon': crypto_info[symbol]['icon'],
            'pattern_type': '准备突破五浪结构',
            'strength': strength,
            'current_price': current_price,
            'structure_high': structure_high,
            'breakout_distance': ((structure_high - current_price) / current_price) * 100 if current_price > 0 else 0
        }
    
    return None

# 筛选准备突破五浪结构的币种
def filter_five_wave_patterns(interval='1h'):
    global is_filter_running, is_filter_cancelled
    
    is_filter_running = True
    is_filter_cancelled = False
    
    results = []
    processed_count = 0
    total_count = len(crypto_info)
    
    try:
        # 遍历所有支持的币种
        for symbol in crypto_info.keys():
            if is_filter_cancelled:
                break
            
            try:
                # 获取K线数据
                klines_data = fetch_klines_data(symbol, interval)
                
                # 检查是否有足够的数据
                if len(klines_data) < 20:
                    print(f"{symbol} 数据不足，跳过分析")
                    processed_count += 1
                    continue
                
                # 检查准备突破五浪结构模式
                pattern_result = check_low_pattern(klines_data, symbol)
                
                if pattern_result:
                    results.append(pattern_result)
                    print(f"找到匹配: {pattern_result['name']}({symbol}) - {pattern_result['pattern_type']} (强度: {pattern_result['strength']:.2f}%)")
                
                processed_count += 1
                
                # 打印进度
                progress = (processed_count / total_count) * 100
                print(f"进度: {processed_count}/{total_count} ({progress:.1f}%)")
                
                # 避免请求过于频繁
                time.sleep(0.2)
                
            except Exception as e:
                print(f"分析 {symbol} 时出错: {str(e)}")
                processed_count += 1
                time.sleep(0.2)
        
    finally:
        is_filter_running = False
    
    # 按模式强度排序
    results.sort(key=lambda x: x['strength'], reverse=True)
    
    return results

# 主函数
def run_filter():
    """执行一次筛选任务"""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始筛选准备突破五浪结构的币种...")
    
    # 开始筛选，默认使用1h周期
    interval = '1h'
    results = filter_five_wave_patterns(interval)
    
    # 显示结果
    print("\n===== 筛选结果 =====")
    
    if not results:
        print("未找到符合条件的币种")
    else:
        print(f"共找到 {len(results)} 个符合条件的币种:\n")
        
        # 打印表头（去掉模式类型、名称、当前价格）
        print(f"{'币种':<12} {'强度(%)':<10} {'突破距离(%)':<10}")
        print("="*40)
        
        # 打印每个结果（去掉模式类型、名称、当前价格）
        for result in results:
            print(f"{result['symbol']:<12} {result['strength']:.2f}%      {result['breakout_distance']:.2f}%")
    
    print("\n筛选完成！")
    
    # 发送结果到钉钉群
    send_results_to_dingtalk(results, interval)
    
    print("\n等待下次整点执行...\n")

def main():
    """主函数，实现整点自动运行功能"""
    print("===== 五浪结构自动筛选器 =====")
    print("程序将在每小时整点自动执行筛选任务")
    print("按 Ctrl+C 可以退出程序\n")
    
    try:
        # 首次运行一次筛选
        run_filter()
        
        while True:
            # 获取当前时间
            now = datetime.now()
            
            # 计算距离下一个整点的秒数
            seconds_until_next_hour = 3600 - (now.minute * 60 + now.second)
            
            # 等待到下一个整点
            print(f"距离下次执行还有: {seconds_until_next_hour//3600}小时{(seconds_until_next_hour%3600)//60}分钟{seconds_until_next_hour%60}秒")
            time.sleep(seconds_until_next_hour)
            
            # 整点执行筛选
            run_filter()
            
    except KeyboardInterrupt:
        print("\n程序已被用户中断")
    except Exception as e:
        print(f"程序发生错误: {str(e)}")

# 发送结果到钉钉群
def send_results_to_dingtalk(results, interval):
    # 请替换为实际的钉钉机器人Webhook地址
    dingtalk_webhook = "https://oapi.dingtalk.com/robot/send?access_token=02fcc926215099c4d0315e453e86aa6d9af934ad538de89b13f67bc3d131ee07"
    
    # 如果未设置Webhook地址，跳过发送
    if dingtalk_webhook == "https://oapi.dingtalk.com/robot/send?access_token=YOUR_ACCESS_TOKEN_HERE":
        print("\n未设置钉钉机器人Webhook地址，跳过发送结果到钉钉群。")
        print("请在代码中配置您的钉钉机器人Webhook地址以启用此功能。")
        return
    
    # 构建消息内容
    if not results:
        message = {
            "msgtype": "text",
            "text": {
                "content": f"【五浪结构筛选结果】usp10\n周期: {interval}\n未找到符合条件的币种。"
            }
        }
    else:
        # 构建Markdown格式的消息 - 标题中也包含关键词
        markdown_content = "## 五浪结构筛选结果usp10\n"
        markdown_content += f"**周期**: {interval}\n"
        markdown_content += f"**找到符合条件的币种数量**: {len(results)}\n\n"
        # 简化表格，去掉模式类型、名称、当前价格
        markdown_content += "| 币种 | 强度(%) | 突破距离(%) |\n"
        markdown_content += "|------|---------|------------|\n"
        
        # 添加每个结果（去掉模式类型、名称、当前价格）
        for result in results:
            markdown_content += f"| {result['symbol']} | {result['strength']:.2f}% | {result['breakout_distance']:.2f}% |\n"
        
        message = {
            "msgtype": "markdown",
            "markdown": {
                "title": "五浪结构筛选结果usp10",  # 标题中也添加关键词
                "text": markdown_content
            }
        }
    
    # 设置重试次数和超时
    max_retries = 3
    retry_delay = 2  # 秒
    
    for attempt in range(max_retries):
        try:
            # 发送请求 - 增加重试配置和SSL设置
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)  # 禁用警告
            
            # 配置requests会话
            session = requests.Session()
            adapter = requests.adapters.HTTPAdapter(max_retries=3)
            session.mount('https://', adapter)
            
            # 禁用SSL验证以解决连接问题
            response = session.post(
                dingtalk_webhook,
                json=message,
                headers={'Content-Type': 'application/json'},
                timeout=15,
                verify=False  # 禁用SSL验证
            )
            
            response.raise_for_status()
            
            print("\n结果已成功发送到钉钉群！")
            return
            
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"\n发送失败 (尝试 {attempt + 1}/{max_retries})，{str(e)}，{retry_delay}秒后重试...")
                time.sleep(retry_delay)
            else:
                print(f"\n发送结果到钉钉群时多次尝试失败: {str(e)}")
                print("请检查以下几点:")
                print("1. 钉钉机器人Webhook地址是否正确")
                print("2. 网络连接是否正常")
                print("3. 钉钉机器人的安全设置是否正确配置了关键词'usp10'")
                print("4. 可能是SSL证书验证问题")

if __name__ == "__main__":
    main()