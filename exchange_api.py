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
            'defaultType': 'future', 
        }
    })

    try:
        # 2. 尝试获取账户余额（测试连接）
        exchange.fetch_balance()
        print("✅ 交易所连接成功！")

        # 3. 获取最近的成交记录
        trades = exchange.fetch_my_trades(symbol=None, limit=limit)
        
        if not trades:
            return None, "没有找到最近的交易记录。"

        # 4. 数据清洗：加固防弹版
        data_list = []
        for t in trades:
            try:
                # --- 安全获取字段 ---
                
                # 1. 处理原始信息 (info)
                raw_info = t.get('info', {}) 
                if raw_info is None: raw_info = {} # 双重保险
                
                # 2. 获取已实现盈亏 (Realized PnL)
                # 如果获取不到，默认为 0.0
                pnl = float(raw_info.get('realizedPnl', 0.0))
                
                # 3. 处理手续费 (Fee)
                # 有些特殊的单子可能没有 fee 字段，或者是 None
                fee_cost = 0.0
                fee_data = t.get('fee')
                if fee_data and isinstance(fee_data, dict):
                    fee_cost = float(fee_data.get('cost', 0.0))
                
                # 4. 构建数据行
                data_list.append({
                    'id': str(t.get('id', '')), # 转成字符串防止报错
                    'exchange': 'Binance',
                    'symbol': t.get('symbol', 'Unknown'),
                    'side': t.get('side', 'unknown'),
                    'price': float(t.get('price', 0.0)),
                    'qty': float(t.get('amount', 0.0)),
                    'realized_pnl': pnl,
                    'timestamp': t['timestamp'],
                    'date_str': datetime.fromtimestamp(t['timestamp'] / 1000).strftime('%Y-%m-%d %H:%M:%S'),
                    'commission': fee_cost,
                    'notes': '',        
                    'ai_analysis': ''   
                })
            except Exception as inner_e:
                # 如果某一条具体的数据有问题，打印出来但不要让整个程序崩溃
                print(f"⚠️ 跳过一条异常数据: {str(inner_e)}")
                continue

        if not data_list:
            return None, "获取到了数据，但在清洗过程中全部被过滤了（可能是格式不兼容）。"

        df = pd.DataFrame(data_list)
        df = df.sort_values(by='timestamp', ascending=False)
        
        return df, "success"

    except Exception as e:
        # 打印详细错误信息方便调试
        import traceback
        traceback.print_exc()
        return None, f"连接或处理失败: {str(e)}"
