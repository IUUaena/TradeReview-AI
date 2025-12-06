import pandas as pd
import numpy as np

def process_trades_to_rounds(df):
    """
    核心算法：将零散的成交记录合并为完整的交易回合。
    🌟 升级版：增加了 open_id 字段，用于关联笔记。
    """
    if df is None or df.empty:
        return pd.DataFrame()
    
    # 1. 预处理
    df = df.sort_values(by='timestamp', ascending=True)
    rounds = []
    
    # 2. 分组处理
    grouped = df.groupby('symbol')
    
    for symbol, group in grouped:
        current_qty = 0.0
        current_pnl = 0.0
        current_commission = 0.0
        start_time = None
        
        trade_ids = [] # 记录涉及的所有订单ID
        
        in_position = False
        side_direction = 0 
        
        for index, row in group.iterrows():
            qty = float(row['qty'])
            pnl = float(row['realized_pnl'])
            commission = float(row['commission'])
            timestamp = row['timestamp']
            side = row['side'].lower()
            
            # 判断开仓
            if current_qty == 0:
                in_position = True
                start_time = timestamp
                side_direction = 1 if side == 'buy' else -1
                trade_ids = [row['id']] # 🌟 记录开仓ID
                current_pnl = pnl
                current_commission = commission
                
                if side == 'buy': current_qty += qty
                else: current_qty -= qty
                
            else:
                # 加仓或平仓
                trade_ids.append(row['id'])
                current_pnl += pnl
                current_commission += commission
                
                if side == 'buy': current_qty += qty
                else: current_qty -= qty
                
                # 判断是否平仓完毕
                if abs(current_qty) < 0.000001:
                    end_time = timestamp
                    duration_minutes = (end_time - start_time) / 1000 / 60
                    
                    rounds.append({
                        'open_id': trade_ids[0], # 🌟 关键：保存开仓单ID，作为这笔交易的唯一索引
                        'symbol': symbol,
                        'direction': 'Long' if side_direction == 1 else 'Short',
                        'open_time': start_time,
                        'close_time': end_time,
                        'open_date': pd.to_datetime(start_time, unit='ms').strftime('%Y-%m-%d %H:%M'),
                        'duration_min': round(duration_minutes, 1),
                        'total_pnl': round(current_pnl, 2),
                        'total_fee': round(current_commission, 2),
                        'net_pnl': round(current_pnl - current_commission, 2),
                        'trade_count': len(trade_ids),
                        'status': 'Closed'
                    })
                    
                    in_position = False
                    current_qty = 0
                    side_direction = 0

        # 处理未结持仓
        if in_position:
             rounds.append({
                'open_id': trade_ids[0], # 🌟 也要带上ID
                'symbol': symbol,
                'direction': 'Long' if side_direction == 1 else 'Short',
                'open_time': start_time,
                'close_time': group.iloc[-1]['timestamp'],
                'open_date': pd.to_datetime(start_time, unit='ms').strftime('%Y-%m-%d %H:%M'),
                'duration_min': 'Holding',
                'total_pnl': round(current_pnl, 2),
                'total_fee': round(current_commission, 2),
                'net_pnl': round(current_pnl - current_commission, 2),
                'trade_count': len(trade_ids),
                'status': 'Open (持仓中)'
            })

    if not rounds:
        return pd.DataFrame()
        
    results_df = pd.DataFrame(rounds)
    results_df = results_df.sort_values(by='close_time', ascending=False)
    
    return results_df
