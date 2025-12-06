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
    """
    核心工具：突破 7 天限制的抓取器。
    它会自动把时间切成 7 天一段，循环抓取。
    """
    all_trades = []
    current_start = start_ts
    
    # 7天的毫秒数 (稍微减去1分钟，防止临界点报错)
    SEVEN_DAYS_MS = 7 * 24 * 60 * 60 * 1000 - 60000
    
    while current_start < end_ts:
        current_end = current_start + SEVEN_DAYS_MS
        if current_end > end_ts:
            current_end = end_ts
            
        try:
            # 必须同时指定 startTime 和 endTime
            trades = exchange.fetch_my_trades(symbol=symbol, since=current_start, limit=1000, params={'endTime': current_end})
            if trades:
                all_trades.extend(trades)
        except Exception as e:
            pass
            
        # 往前跳
        current_start = current_end
        # 极速模式：不休息太久，因为我们有很多币种要扫
        # 但为了安全，保留极小延迟
        time.sleep(0.05) 
        
    return all_trades

def get_binance_data(api_key, api_secret, mode="recent", target_coins_str="", progress_callback=None):
    """
    Args:
        mode: 'recent' (扫描所有币种最近 30 天) 或 'deep' (扫描指定币种过去 1 年)
    """
    print(f"--- 启动数据同步: 模式={mode} ---")
    
    exchange = ccxt.binance({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True,
        'options': { 'defaultType': 'future' }
    })

    try:
        # 1. 准备币种清单
        if progress_callback: progress_callback("正在连接交易所并下载交易对...", 0)
        exchange.load_markets()
        
        target_symbols = []
        
        if mode == "recent":
            # 升级：模式A 变为扫描所有 USDT 合约
            for symbol, market in exchange.markets.items():
                if market.get('quote') == 'USDT' and market.get('contract') == True:
                    target_symbols.append(symbol)
            print(f"✅ [月度扫描] 准备扫描 {len(target_symbols)} 个合约的最近 30 天记录")
            
        else:
            # 模式B：深度挖掘 (1年)
            if not target_coins_str:
                return None, "深度模式下，必须输入具体的币种（例如 BTC, ETH）。"
            
            user_coins = [x.strip().upper() for x in target_coins_str.split(',') if x.strip()]
            for coin in user_coins:
                if not coin.endswith('/USDT'): coin = f"{coin}/USDT"
                if coin in exchange.markets:
                    target_symbols.append(coin)
            print(f"✅ [年度挖掘] 将挖掘以下币种的 1 年历史: {target_symbols}")

        if not target_symbols:
            return None, "没有有效的交易对可供扫描。"

        # 2. 设定时间窗口
        now_ts = int(datetime.now().timestamp() * 1000)
        
        if mode == "recent":
            # 最近 30 天
            start_ts = int((datetime.now() - timedelta(days=30)).timestamp() * 1000)
        else:
            # 过去 365 天
            start_ts = int((datetime.now() - timedelta(days=365)).timestamp() * 1000)

        # 3. 开始抓取
        all_results = []
        total_symbols = len(target_symbols)
        
        for index, symbol in enumerate(target_symbols):
            progress = (index + 1) / total_symbols
            status_text = f"正在扫描 ({index+1}/{total_symbols}): {symbol}"
            if progress_callback: progress_callback(status_text, progress)
            print(status_text)

            try:
                # 统一使用分片抓取，兼容 30 天或 365 天
                trades = fetch_history_chunked(exchange, symbol, start_ts, now_ts)

                if trades:
                    print(f"   🎉 {symbol}: 获取到 {len(trades)} 条数据")
                    all_results.extend(trades)

            except Exception as e:
                continue

        # 4. 清洗数据
        if not all_results:
            return None, "扫描完成，在此时间段内未发现任何记录。"

        if progress_callback: progress_callback("正在清洗整理数据...", 0.99)
        
        data_list = []
        for i, t in enumerate(all_results):
            try:
                # 提取 PnL 和 Fee
                pnl = 0.0
                info = t.get('info', {})
                if isinstance(info, dict):
                    pnl = safe_float(info.get('realizedPnl'))
                
                commission = 0.0
                fee = t.get('fee')
                if fee and isinstance(fee, dict):
                    commission = safe_float(fee.get('cost'))
                    
                ts = t.get('timestamp', int(time.time()*1000))
                
                row = {
                    'id': str(t.get('id', f'unknown_{i}')),
                    'exchange': 'Binance',
                    'symbol': str(t.get('symbol', 'Unknown')),
                    'side': str(t.get('side', 'unknown')),
                    'price': safe_float(t.get('price')),
                    'qty': safe_float(t.get('amount')),
                    'realized_pnl': pnl,
                    'commission': commission,
                    'timestamp': ts,
                    'date_str': datetime.fromtimestamp(ts / 1000).strftime('%Y-%m-%d %H:%M:%S'),
                    'notes': '',        
                    'ai_analysis': ''   
                }
                data_list.append(row)
            except:
                continue

        df = pd.DataFrame(data_list)
        df = df.sort_values(by='timestamp', ascending=False)
        # 极其重要：去重！因为分片抓取可能会在边界处抓到重复的
        df = df.drop_duplicates(subset=['id'])
        
        return df, "success"

    except Exception as e:
        import traceback
        traceback.print_exc()
        return None, f"运行错误: {str(e)}"
