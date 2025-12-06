import pandas as pd
import numpy as np

def process_trades_to_rounds(df):
    """
    核心算法：将零散的成交记录合并为完整的交易回合 (Round Trip)。
    """
    if df is None or df.empty:
        return pd.DataFrame()
    
    # 1. 预处理：按时间正序排列
    df = df.sort_values(by='timestamp', ascending=True)
    rounds = []
    
    # 2. 分组处理
    grouped = df.groupby('symbol')
    
    for symbol, group in grouped:
        current_qty = 0.0
        current_pnl = 0.0
        current_commission = 0.0
        start_time = None
        
        trade_ids = [] 
        open_id = None
        
        in_position = False
        side_direction = 0 
        
        for index, row in group.iterrows():
            # 🌟 修复点：字段名称与 data_engine.py 数据库保持一致
            # qty -> amount
            # realized_pnl -> pnl
            # commission -> fee
            qty = float(row['amount']) if row.get('amount') else 0.0
            pnl = float(row['pnl']) if row.get('pnl') else 0.0
            commission = float(row['fee']) if row.get('fee') else 0.0
            
            timestamp = row['timestamp']
            side = str(row['side']).lower()
            
            # --- 场景 A: 开仓 ---
            if abs(current_qty) < 0.0000001: 
                in_position = True
                start_time = timestamp
                open_id = row['id']
                trade_ids = [row['id']]
                
                side_direction = 1 if side == 'buy' else -1
                
                if side == 'buy': current_qty += qty
                else: current_qty -= qty
                
                current_pnl = pnl 
                current_commission = commission
                
            # --- 场景 B: 加仓或平仓 ---
            else:
                trade_ids.append(row['id'])
                current_pnl += pnl
                current_commission += commission
                
                if side == 'buy': current_qty += qty
                else: current_qty -= qty
                
                # 检查是否平仓完毕
                if abs(current_qty) < 0.0000001:
                    end_time = timestamp
                    duration_minutes = (end_time - start_time) / 1000 / 60
                    
                    # 提取笔记
                    note_content = ""
                    ai_content = ""
                    match_row = df[df['id'] == open_id]
                    if not match_row.empty:
                        # 数据库读出来如果是 None 要转为空字符串
                        note_val = match_row.iloc[0].get('notes')
                        ai_val = match_row.iloc[0].get('ai_analysis')
                        note_content = note_val if note_val else ""
                        ai_content = ai_val if ai_val else ""

                    rounds.append({
                        'round_id': open_id,
                        'symbol': symbol,
                        'direction': '做多 (Long)' if side_direction == 1 else '做空 (Short)',
                        'open_time': start_time,
                        'close_time': end_time,
                        'open_date_str': pd.to_datetime(start_time, unit='ms').strftime('%Y-%m-%d %H:%M'),
                        'close_date_str': pd.to_datetime(end_time, unit='ms').strftime('%Y-%m-%d %H:%M'),
                        'duration_min': round(duration_minutes, 1),
                        'duration_str': format_duration(duration_minutes),
                        'total_pnl': round(current_pnl, 2),
                        'total_fee': round(current_commission, 2),
                        'net_pnl': round(current_pnl - current_commission, 2),
                        'trade_count': len(trade_ids),
                        'status': 'Closed',
                        'notes': note_content,
                        'ai_analysis': ai_content
                    })
                    
                    in_position = False
                    current_qty = 0
                    side_direction = 0

    if not rounds:
        return pd.DataFrame()
        
    results_df = pd.DataFrame(rounds)
    results_df = results_df.sort_values(by='close_time', ascending=False)
    
    return results_df

def format_duration(minutes):
    if minutes < 60:
        return f"{int(minutes)}分"
    elif minutes < 1440:
        return f"{int(minutes/60)}小时{int(minutes%60)}分"
    else:
        return f"{int(minutes/1440)}天{int((minutes%1440)/60)}小时"