import ccxt
import pandas as pd
from datetime import datetime

def safe_float(value, default=0.0):
    """
    一个极其强壮的数字转换器。
    不管给它什么（None, 字符串, 对象），它都尽力转成数字，
    转不了就返回 0.0，绝不报错。
    """
    try:
        if value is None:
            return default
        return float(value)
    except (ValueError, TypeError):
        return default

def get_binance_futures_history(api_key, api_secret, limit=100):
    """
    连接币安 U本位合约 (USDT-M) 获取历史成交记录
    """
    print("--- 开始尝试连接交易所 ---") # Debug 标记
    
    # 1. 初始化交易所
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
        # 2. 测试连接
        exchange.fetch_balance()
        print("✅ 交易所连接成功 (Balance Check OK)")

        # 3. 获取数据
        # params={'incomeType': 'REALIZED_PNL'} 有时可以帮助筛选，但这里先抓全部
        trades = exchange.fetch_my_trades(symbol=None, limit=limit)
        
        if not trades:
            return None, "连接成功，但没有找到最近的交易记录 (Trades list is empty)。"

        print(f"📦 抓取到了 {len(trades)} 条原始记录")

        # 4. 超级安全的清洗流程
        data_list = []
        
        for i, t in enumerate(trades):
            try:
                # 打印第一条数据看看长什么样（方便调试）
                if i == 0:
                    print(f"🔍 [DEBUG] 第一条原始数据样本: {t}")

                # 必须确保 t 是个字典
                if not isinstance(t, dict):
                    print(f"⚠️ 跳过第 {i} 条：数据格式不是字典")
                    continue

                # --- 逐个字段安全提取 ---
                
                # ID
                order_id = str(t.get('id', f'unknown_{i}'))
                
                # Symbol
                symbol = str(t.get('symbol', 'Unknown'))
                
                # Side (buy/sell)
                side = str(t.get('side', 'unknown'))
                
                # Price
                price = safe_float(t.get('price'))
                
                # Qty
                amount = safe_float(t.get('amount'))
                
                # Realized PnL (最容易报错的地方)
                pnl = 0.0
                info = t.get('info')
                if info and isinstance(info, dict):
                    pnl = safe_float(info.get('realizedPnl'))
                
                # Commission/Fee (也很容易报错)
                commission = 0.0
                fee = t.get('fee')
                # 这里的逻辑是：如果 fee 是 None，下面这行不会运行；
                # 如果 fee 是字典但没有 cost，safe_float 会处理。
                if fee and isinstance(fee, dict):
                    commission = safe_float(fee.get('cost'))

                # 时间戳
                timestamp = t.get('timestamp')
                if not timestamp:
                    timestamp = int(datetime.now().timestamp() * 1000)
                
                date_str = datetime.fromtimestamp(timestamp / 1000).strftime('%Y-%m-%d %H:%M:%S')

                # 构建最终行
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
                print(f"⚠️ 处理第 {i} 条数据时发生意外错误: {inner_e}")
                # 即使这条错了，也不要停，继续下一条
                continue

        if not data_list:
            return None, "数据清洗后为空。可能所有数据都不符合格式。"

        df = pd.DataFrame(data_list)
        df = df.sort_values(by='timestamp', ascending=False)
        
        return df, "success"

    except Exception as e:
        import traceback
        traceback.print_exc() # 这会把详细错误印在终端里
        return None, f"全局错误: {str(e)}"
