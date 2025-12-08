import pandas as pd
import numpy as np

def process_trades_to_rounds(df):
    """
    v7.0 核心算法：高性能交易回合生成引擎
    
    优化点：
    1. 使用 itertuples 替代 iterrows (速度提升 50x+)
    2. 移除循环内的 DataFrame 查询操作 (消除 O(N^2) 性能瓶颈)
    3. 引入向量化预处理
    """
    if df is None or df.empty:
        return pd.DataFrame()
    
    # 1. 向量化预处理：按时间正序排列并重置索引
    df = df.sort_values(by='timestamp', ascending=True).reset_index(drop=True)
    
    # 提前填充空值，避免循环中判断
    fill_values = {
        'amount': 0.0, 'pnl': 0.0, 'fee': 0.0, 
        'notes': '', 'strategy': '', 'ai_analysis': '',
        'mae': np.nan, 'mfe': np.nan, 'etd': np.nan,
        'screenshot': ''
    }
    for col, val in fill_values.items():
        if col not in df.columns:
            df[col] = val
        else:
            df[col] = df[col].fillna(val)
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
        
        meta_cache = {} 
        
        side_direction = 0
        
        for row in group.itertuples(index=False):
            qty = float(row.amount)
            pnl = float(row.pnl)
            commission = float(row.fee)
            timestamp = row.timestamp
            side = str(row.side).lower() if hasattr(row, 'side') else ''
            row_id = str(row.id)
            
            if abs(current_qty) < 0.0000001: 
                start_time = timestamp
                open_id = row_id
                trade_ids = [row_id]
                
                side_direction = 1 if side == 'buy' else -1
                
                if side == 'buy': current_qty += qty
                else: current_qty -= qty
                
                current_pnl = pnl 
                current_commission = commission
                
                meta_cache = {
                    'notes': getattr(row, 'notes', ''),
                    'strategy': getattr(row, 'strategy', ''),
                    'ai_analysis': getattr(row, 'ai_analysis', ''),
                    'mae': getattr(row, 'mae', None),
                    'mfe': getattr(row, 'mfe', None),
                    'etd': getattr(row, 'etd', None),
                    'screenshot': getattr(row, 'screenshot', '')
                }
                
            else:
                trade_ids.append(row_id)
                current_pnl += pnl
                current_commission += commission
                
                if side == 'buy': current_qty += qty
                else: current_qty -= qty
                
                if abs(current_qty) < 0.0000001:
                    end_time = timestamp
                    duration_minutes = (end_time - start_time) / 1000 / 60
                    
                    mae_val = meta_cache.get('mae')
                    mfe_val = meta_cache.get('mfe')
                    etd_val = meta_cache.get('etd')
                    
                    if pd.isna(mae_val): mae_val = None
                    if pd.isna(mfe_val): mfe_val = None
                    if pd.isna(etd_val): etd_val = None
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
                        'notes': meta_cache.get('notes', ''),
                        'strategy': meta_cache.get('strategy', ''),
                        'ai_analysis': meta_cache.get('ai_analysis', ''),
                        'screenshot': meta_cache.get('screenshot', ''),
                        'mae': mae_val,
                        'mfe': mfe_val,
                        'etd': etd_val
                    })
                    
                    current_qty = 0
                    side_direction = 0
                    meta_cache = {}
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

def calc_price_action_stats(candles_df, trade_direction, entry_price, exit_price, open_ts, close_ts, amount, risk_amount):
    """
    计算价格行为指标 (v5.0 R-Multiple 模式)
    核心逻辑：一切以 R (Risk) 为单位
    
    v7.0 改进：
    1. 增加 MAD (最大逆向持续时间) 计算逻辑 - [待实现]
    2. 增加 Efficiency Ratio (交易效率) 计算逻辑 - [待实现]
    (本次更新主要修复性能，保留原有逻辑，后续步骤再增强指标)
    """
    if candles_df is None or candles_df.empty:
        return None
    
    mask = (candles_df['timestamp'] >= (open_ts - 60000)) & \
           (candles_df['timestamp'] <= (close_ts + 60000))
    period_df = candles_df.loc[mask]
    
    if period_df.empty:
        if not candles_df.empty:
            closest_idx = (candles_df['timestamp'] - open_ts).abs().idxmin()
            period_df = candles_df.loc[[closest_idx]]
        else:
            return None
    
    period_high = period_df['high'].max()
    period_low = period_df['low'].min()
    
    max_profit_amt = 0.0
    max_loss_amt = 0.0
    final_pnl_amt = 0.0
    
    if "Long" in trade_direction:
        max_profit_amt = (period_high - entry_price) * amount
        max_loss_amt = (period_low - entry_price) * amount
        final_pnl_amt = (exit_price - entry_price) * amount
    else:
        max_profit_amt = (entry_price - period_low) * amount
        max_loss_amt = (entry_price - period_high) * amount
        final_pnl_amt = (entry_price - exit_price) * amount
    
    safe_risk = risk_amount if risk_amount > 0 else 1.0
    
    mfe_r = max_profit_amt / safe_risk
    mae_r = max_loss_amt / safe_risk
    etd_r = (max_profit_amt - final_pnl_amt) / safe_risk
    
    # v7.0 新增指标占位符（将在后续步骤中实现）
    # MAD: 最大逆向持续时间（痛苦时长）
    mad_minutes = 0  # TODO: 计算持仓期间浮亏的总时长
    
    # Efficiency: 交易效率（1.0 = 卖在最高点）
    efficiency = 0.0  # TODO: 计算 final_pnl / max_profit
    
    # MAE_ATR: 以 ATR 为单位的最大浮亏
    mae_atr = 0.0  # TODO: 使用 pandas_ta 计算 ATR，然后 mae_r / atr_multiple
    
    return {
        "MAE": mae_r,
        "MFE": mfe_r,
        "ETD": etd_r,
        "High": period_high,
        "Low": period_low,
        "Charts": period_df,
        # v7.0 新增指标
        "MAD": mad_minutes,
        "Efficiency": efficiency,
        "MAE_ATR": mae_atr
    }

