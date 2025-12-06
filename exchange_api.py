import ccxt
import pandas as pd
from datetime import datetime, timedelta
import time

def safe_float(value, default=0.0):
    try:
        if value is None: return default
        return float(value)
    except: return default

def fetch_history_chunked(exchange, symbol, start_ts, end_ts):
    """分片抓取工具"""
    all_trades = []
    current_start = start_ts
    SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000 - 60000
    
    while current_start < end_ts:
        current_end = current_start + SEVEN_DAYS_MS
        if current_end > end_ts: current_end = end_ts
        try:
            trades = exchange.fetch_my_trades(symbol=symbol, since=current_start, limit=1000, params={'endTime': current_end})
            if trades: all_trades.extend(trades)
        except: pass
        current_start = current_end
        time.sleep(0.05) 
    return all_trades

def get_binance_data(api_key, api_secret, mode="fast", target_coins_str="", progress_callback=None):
    """
    mode: 'fast' (7天), 'month' (30天), 'deep' (1年指定币种)
    """
    print(f"--- 启动数据同步: 模式={mode} ---")
    
    exchange = ccxt.binance({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True,
        'options': { 'defaultType': 'future' }
    })

    try:
        if progress_callback: progress_callback("正在下载交易对信息...", 0)
        exchange.load_markets()
        
        target_symbols = []
        
        # 1. 确定要扫描的币种
        if mode in ["fast", "month"]:
            # 自动扫描所有 USDT 合约
            for symbol, market in exchange.markets.items():
                if market.get('quote') == 'USDT' and market.get('contract') == True:
                    target_symbols.append(symbol)
            print(f"✅ [{mode}] 扫描所有 {len(target_symbols)} 个合约")
        else:
            # 深度模式：指定币种
            if not target_coins_str: return None, "深度模式必须输入币种。"
            
            user_coins = [x.strip().upper() for x in target_coins_str.split(',') if x.strip()]
            for coin in user_coins:
                if not coin.endswith('/USDT'): coin = f"{coin}/USDT"
                if coin in exchange.markets: target_symbols.append(coin)
        if not target_symbols: return None, "没有有效的交易对。"

        # 2. 确定时间范围
        now_ts = int(datetime.now().timestamp() * 1000)
        
        if mode == "fast":
            # 7天
            start_ts = int((datetime.now() - timedelta(days=7)).timestamp() * 1000)
        elif mode == "month":
            # 30天
            start_ts = int((datetime.now() - timedelta(days=30)).timestamp() * 1000)
        else:
            # 365天
            start_ts = int((datetime.now() - timedelta(days=365)).timestamp() * 1000)

        # 3. 执行扫描
        all_results = []
        total = len(target_symbols)
        
        for index, symbol in enumerate(target_symbols):
            if progress_callback:
                progress_callback(f"扫描中 ({index+1}/{total}): {symbol}", (index+1)/total)
            
            try:
                # 统一用分片抓取，稳健
                trades = fetch_history_chunked(exchange, symbol, start_ts, now_ts)
                if trades: all_results.extend(trades)
            except: continue

        # 4. 数据清洗
        if not all_results: return None, "该时间段内未发现交易记录。"
        
        if progress_callback: progress_callback("正在清洗数据...", 0.99)
        
        data_list = []
        for i, t in enumerate(all_results):
            try:
                # 关键修复：确保 commission 存在
                commission = 0.0
                fee = t.get('fee')
                if fee and isinstance(fee, dict):
                    commission = safe_float(fee.get('cost'))
                
                info = t.get('info', {})
                pnl = safe_float(info.get('realizedPnl')) if isinstance(info, dict) else 0.0
                
                ts = t.get('timestamp', int(time.time()*1000))
                
                data_list.append({
                    'id': str(t.get('id', f'unknown_{i}')),
                    'exchange': 'Binance',
                    'symbol': str(t.get('symbol', 'Unknown')),
                    'side': str(t.get('side', 'unknown')),
                    'price': safe_float(t.get('price')),
                    'qty': safe_float(t.get('amount')),
                    'realized_pnl': pnl,
                    'commission': commission, # 🌟 确保这里有值
                    'timestamp': ts,
                    'date_str': datetime.fromtimestamp(ts/1000).strftime('%Y-%m-%d %H:%M:%S'),
                    'notes': '',        
                    'ai_analysis': ''   
                })
            except: continue

        df = pd.DataFrame(data_list)
        df = df.sort_values(by='timestamp', ascending=False)
        df = df.drop_duplicates(subset=['id'])
        return df, "success"

    except Exception as e:
        return None, str(e)
