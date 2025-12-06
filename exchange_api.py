import ccxt
import pandas as pd
from datetime import datetime
import time

def safe_float(value, default=0.0):
    try:
        if value is None: return default
        return float(value)
    except: return default

def get_binance_futures_history(api_key, api_secret, limit=100):
    """
    连接币安 U本位合约，循环查询主流币种的成交记录
    """
    print("--- 开始连接交易所 ---")
    
    # 1. 定义我们要巡逻的币种清单
    # ⚠️ 警告：币安合约不支持一次性查所有，必须指定币种。
    # 这里我们先列出最常见的几个。以后可以在界面上让用户自己选。
    TARGET_SYMBOLS = [
        'BTC/USDT', 
        'ETH/USDT', 
        'SOL/USDT', 
        'BNB/USDT', 
        'DOGE/USDT',
        'XRP/USDT',
        'PEPE/USDT'
    ]

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
        # 2. 加载市场信息
        print("--- 正在下载交易对信息... ---")
        exchange.load_markets()
        
        # 3. 循环抓取
        all_trades = []
        
        print(f"--- 准备扫描以下币种: {TARGET_SYMBOLS} ---")
        
        for symbol in TARGET_SYMBOLS:
            print(f"🔍 正在查询 {symbol} ...")
            try:
                # 这里的 limit 是针对每个币种的
                trades = exchange.fetch_my_trades(symbol=symbol, limit=limit)
                
                if trades:
                    print(f"   ✅ 发现 {len(trades)} 条 {symbol} 的记录")
                    all_trades.extend(trades) # 把找到的记录倒进大桶里
                else:
                    print(f"   💨 {symbol} 无近期记录")
                
                # 稍微休息一下，防止被交易所限流
                time.sleep(0.1) 
                
            except Exception as e:
                print(f"   ⚠️ 查询 {symbol} 失败: {str(e)}")
                continue

        if not all_trades:
            return None, "扫描了主流币种，但没有发现任何成交记录。"

        print(f"📦 总共收集到 {len(all_trades)} 条记录，开始清洗...")

        # 4. 统一清洗数据
        data_list = []
        for i, t in enumerate(all_trades):
            try:
                # 安全提取字段
                order_id = str(t.get('id', f'unknown_{i}'))
                symbol = str(t.get('symbol', 'Unknown'))
                side = str(t.get('side', 'unknown'))
                price = safe_float(t.get('price'))
                amount = safe_float(t.get('amount'))
                
                # PnL & Fee
                pnl = 0.0
                info = t.get('info', {})
                if isinstance(info, dict):
                    pnl = safe_float(info.get('realizedPnl'))
                
                commission = 0.0
                fee = t.get('fee')
                if fee and isinstance(fee, dict):
                    commission = safe_float(fee.get('cost'))

                # 时间
                timestamp = t.get('timestamp')
                if not timestamp: timestamp = int(datetime.now().timestamp() * 1000)
                date_str = datetime.fromtimestamp(timestamp / 1000).strftime('%Y-%m-%d %H:%M:%S')

                row = {
                    'id': order_id,
                    'exchange': 'Binance',
                    'symbol': symbol,
                    'side': side,
                    'price': price,
                    'qty': amount,
                    'realized_pnl': pnl,
                    'timestamp': timestamp,
                    'date_str': date_str,
                    'commission': commission,
                    'notes': '',        
                    'ai_analysis': ''   
                }
                data_list.append(row)

            except Exception as inner_e:
                print(f"清洗错误: {inner_e}")
                continue

        df = pd.DataFrame(data_list)
        # 按时间倒序，最新的在最上面
        df = df.sort_values(by='timestamp', ascending=False)
        
        return df, "success"

    except Exception as e:
        import traceback
        traceback.print_exc()
        return None, f"全局执行出错: {str(e)}"
