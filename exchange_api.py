import ccxt
import pandas as pd
from datetime import datetime, timedelta
import time

def safe_float(value, default=0.0):
    try:
        if value is None: return default
        return float(value)
    except: return default

def get_binance_futures_history(api_key, api_secret, progress_callback=None, months_back=12):
    """
    全量扫描：

    1. 自动获取所有 USDT 合约。

    2. 强制从指定时间（months_back）开始抓取，打破 7 天限制。

    """
    print("--- 启动全量历史扫描模式 ---")
    
    # 1. 设定起始时间 (时光机)
    # 默认为过去 12 个月。如果你交易很久了，可以把 12 改成 24 或 36
    start_time = datetime.now() - timedelta(days=30 * months_back)
    since_timestamp = int(start_time.timestamp() * 1000)
    print(f"🗓️ 设定查询起始日期: {start_time.strftime('%Y-%m-%d')}")
    
    # 2. 初始化
    exchange = ccxt.binance({
        'apiKey': api_key,
        'secret': api_secret,
        'timeout': 30000,
        'enableRateLimit': True,
        'options': {
            'defaultType': 'future', 
        }
    })

    try:
        # 3. 获取所有交易对
        if progress_callback: progress_callback("正在下载币安合约交易对清单...", 0)
        exchange.load_markets()
        
        # 筛选 USDT 合约
        target_symbols = []
        for symbol, market in exchange.markets.items():
            if market.get('quote') == 'USDT' and market.get('contract') == True:
                target_symbols.append(symbol)
        
        total_symbols = len(target_symbols)
        print(f"✅ 需扫描 {total_symbols} 个交易对")
        if total_symbols == 0:
            return None, "未找到交易对。"

        # 4. 循环扫描
        all_trades = []
        
        for index, symbol in enumerate(target_symbols):
            # 进度显示
            progress = (index + 1) / total_symbols
            status_text = f"正在扫描 ({index+1}/{total_symbols}): {symbol}"
            if progress_callback: progress_callback(status_text, progress)
            print(status_text)
            try:
                # 🌟 核心修改：加入 since 参数 🌟
                # 告诉币安：给我从 since_timestamp 开始的所有数据
                # limit=1000 是单次最大值
                trades = exchange.fetch_my_trades(symbol=symbol, since=since_timestamp, limit=1000)
                
                if trades:
                    print(f"   🎉 {symbol}: 找到 {len(trades)} 条记录")
                    all_trades.extend(trades)
                    
                    # ⚠️ 高级逻辑：如果超过 1000 条怎么办？
                    # 通常小白用户单币种一年内很少超过1000笔成交。
                    # 如果你交易极其频繁，这里需要写更复杂的 while 循环分页。
                    # 目前版本我们先抓前1000条，跑通流程为主。
                
                time.sleep(0.05) # 防封号延迟
                
            except Exception as e:
                # print(f"错误 {symbol}: {e}")
                continue

        if not all_trades:
            return None, f"在过去 {months_back} 个月内未发现任何交易记录。"

        # 5. 清洗数据
        if progress_callback: progress_callback("正在整理历史数据...", 0.99)
        
        data_list = []
        for i, t in enumerate(all_trades):
            try:
                # 提取 PnL
                pnl = 0.0
                info = t.get('info', {})
                if isinstance(info, dict):
                    pnl = safe_float(info.get('realizedPnl'))
                
                # 提取 Fee
                commission = 0.0
                fee = t.get('fee')
                if fee and isinstance(fee, dict):
                    commission = safe_float(fee.get('cost'))
                    
                row = {
                    'id': str(t.get('id', f'unknown_{i}')),
                    'exchange': 'Binance',
                    'symbol': str(t.get('symbol', 'Unknown')),
                    'side': str(t.get('side', 'unknown')),
                    'price': safe_float(t.get('price')),
                    'qty': safe_float(t.get('amount')),
                    'realized_pnl': pnl,
                    'commission': commission,
                    'timestamp': t.get('timestamp', int(time.time()*1000)),
                    'date_str': datetime.fromtimestamp(t['timestamp'] / 1000).strftime('%Y-%m-%d %H:%M:%S'),
                    'notes': '',        
                    'ai_analysis': ''   
                }
                data_list.append(row)
            except:
                continue

        df = pd.DataFrame(data_list)
        df = df.sort_values(by='timestamp', ascending=False)
        
        return df, "success"

    except Exception as e:
        import traceback
        traceback.print_exc()
        return None, f"扫描中断: {str(e)}"
