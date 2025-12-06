import ccxt
import pandas as pd
from datetime import datetime

def safe_float(value, default=0.0):
    """
    数字转换安全气囊
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
    print("--- 步骤 1: 初始化交易所配置 ---")
    
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
        # 🌟 关键修复点：加载市场信息（下载菜单） 🌟
        print("--- 步骤 2: 正在加载市场信息 (Load Markets) ---")
        exchange.load_markets()
        print("✅ 市场信息加载完毕！")
        
        # 测试余额连接
        print("--- 步骤 3: 检查账户余额权限 ---")
        exchange.fetch_balance()
        print("✅ 账户连接成功")
        
        # 获取数据
        print("--- 步骤 4: 开始抓取交易记录 ---")
        # 这里的 symbol=None 在 load_markets 后通常就能正常工作了
        trades = exchange.fetch_my_trades(symbol=None, limit=limit)
        
        if not trades:
            return None, "连接成功，但没有找到最近的交易记录。"
        
        print(f"📦 成功抓取到 {len(trades)} 条记录，开始清洗...")
        
        data_list = []
        for i, t in enumerate(trades):
            try:
                # 必须确保 t 是个字典
                if not isinstance(t, dict):
                    continue

                # --- 逐个字段安全提取 ---
                order_id = str(t.get('id', f'unknown_{i}'))
                symbol = str(t.get('symbol', 'Unknown'))
                side = str(t.get('side', 'unknown'))
                price = safe_float(t.get('price'))
                amount = safe_float(t.get('amount'))
                
                # PnL
                pnl = 0.0
                info = t.get('info')
                if info and isinstance(info, dict):
                    pnl = safe_float(info.get('realizedPnl'))
                
                # Commission
                commission = 0.0
                fee = t.get('fee')
                if fee and isinstance(fee, dict):
                    commission = safe_float(fee.get('cost'))

                # 时间
                timestamp = t.get('timestamp')
                if not timestamp:
                    timestamp = int(datetime.now().timestamp() * 1000)
                
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
                print(f"⚠️ 清洗第 {i} 条数据出错: {inner_e}")
                continue

        if not data_list:
            return None, "数据清洗后为空。"

        df = pd.DataFrame(data_list)
        df = df.sort_values(by='timestamp', ascending=False)
        
        return df, "success"

    except Exception as e:
        import traceback
        print("❌ 发生严重错误，堆栈信息如下：")
        traceback.print_exc() 
        return None, f"执行出错: {str(e)}"
