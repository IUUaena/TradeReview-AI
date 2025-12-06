import ccxt
import pandas as pd
from datetime import datetime

def get_binance_futures_history(api_key, api_secret, limit=100):
    """
    连接币安 U本位合约 (USDT-M) 获取历史成交记录
    """
    # 1. 初始化交易所对象
    exchange = ccxt.binance({
        'apiKey': api_key,
        'secret': api_secret,
        'timeout': 30000,
        'enableRateLimit': True,
        'options': {
            'defaultType': 'future', # 关键：指定是合约交易，不是现货
        }
    })
    
    try:
        # 2. 尝试获取账户余额（测试连接是否成功）
        exchange.fetch_balance()
        print("✅ 交易所连接成功！")
        
        # 3. 获取最近的成交记录 (My Trades)
        # 注意：这是获取"成交历史"，不是"历史委托"
        trades = exchange.fetch_my_trades(symbol=None, limit=limit)
        
        if not trades:
            return None, "没有找到最近的交易记录。"
        
        # 4. 数据清洗：把原始数据变成好看的表格
        data_list = []
        for t in trades:
            # 过滤掉资金费率 (Funding Fee) 等非交易记录，只保留买卖
            # 这里的逻辑可能需要根据你的实际需求微调
            data_list.append({
                'id': t['id'],
                'exchange': 'Binance',
                'symbol': t['symbol'], # 例如 BTC/USDT
                'side': t['side'],     # buy (开多/平空) 或 sell (开空/平多)
                'price': float(t['price']),
                'qty': float(t['amount']),
                'realized_pnl': float(t['info'].get('realizedPnl', 0)), # 只有平仓才会有已实现盈亏
                'timestamp': t['timestamp'],
                'date_str': datetime.fromtimestamp(t['timestamp'] / 1000).strftime('%Y-%m-%d %H:%M:%S'),
                'commission': float(t['fee']['cost']) if t.get('fee') else 0,
                'notes': '',        # 预留给笔记
                'ai_analysis': ''   # 预留给 AI
            })
        
        df = pd.DataFrame(data_list)
        # 按时间倒序排列（最新的在最上面）
        df = df.sort_values(by='timestamp', ascending=False)
        
        return df, "success"
    
    except Exception as e:
        return None, f"连接失败: {str(e)}"

