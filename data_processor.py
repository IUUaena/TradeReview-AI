import pandas as pd
import numpy as np
import pandas_ta as ta  # 👈 必须要有这个库

def process_trades_to_rounds(df):
    """
    v7.0 核心算法：高性能交易回合生成引擎
    """
    if df is None or df.empty:
        return pd.DataFrame()
    
    # 1. 向量化预处理
    df = df.sort_values(by='timestamp', ascending=True).reset_index(drop=True)
    
    # 填充缺失值
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
            # 兼容处理 side
            side = str(row.side).lower() if hasattr(row, 'side') else ''
            # 兼容处理 id
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
                
                # 缓存元数据
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
    v7.0 深度价格行为分析
    计算: ATR标准化指标, MAD(痛苦时长), Efficiency(交易效率)
    """
    if candles_df is None or candles_df.empty:
        return None
    
    # 1. 计算 ATR (需 pandas_ta)
    try:
        # 确保数据量足够，否则 ATR 会全是 NaN
        candles_df['atr'] = candles_df.ta.atr(length=14)
    except Exception as e:
        print(f"ATR 计算失败: {e}")
        candles_df['atr'] = np.nan
    
    # 2. 截取【持仓期间】的数据
    # buffer 60s
    trade_mask = (candles_df['timestamp'] >= open_ts) & (candles_df['timestamp'] <= close_ts)
    period_df = candles_df.loc[trade_mask].copy()
    
    if period_df.empty:
        return None
    
    # 获取开仓时刻的 ATR
    # 如果历史数据不够导致 ATR 为空，则用价格的 1% 代替，避免报错
    first_atr = period_df.iloc[0]['atr']
    if pd.isna(first_atr):
        entry_atr = entry_price * 0.01 
    else:
        entry_atr = first_atr
    
    # 3. 计算极值
    period_high = period_df['high'].max()
    period_low = period_df['low'].min()
    
    max_profit_amt = 0.0
    max_loss_amt = 0.0
    final_pnl_amt = 0.0
    
    # 4. 计算 MAD (痛苦时长)
    mad_minutes = 0
    if "Long" in trade_direction:
        max_profit_amt = (period_high - entry_price) * amount
        max_loss_amt = (period_low - entry_price) * amount
        final_pnl_amt = (exit_price - entry_price) * amount
        # 痛苦时长：收盘价 < 开仓价 的分钟数
        mad_minutes = len(period_df[period_df['close'] < entry_price])
    else:
        max_profit_amt = (entry_price - period_low) * amount
        max_loss_amt = (entry_price - period_high) * amount
        final_pnl_amt = (entry_price - exit_price) * amount
        # 痛苦时长：收盘价 > 开仓价 的分钟数
        mad_minutes = len(period_df[period_df['close'] > entry_price])
    
    # 5. 计算 Efficiency (卖飞程度)
    efficiency = 0.0
    if max_profit_amt > 0:
        efficiency = final_pnl_amt / max_profit_amt
    
    # 6. 转换为 R 倍数
    safe_risk = risk_amount if risk_amount > 0 else 1.0
    mfe_r = max_profit_amt / safe_risk
    mae_r = max_loss_amt / safe_risk
    etd_r = (max_profit_amt - final_pnl_amt) / safe_risk
    
    # 7. 转换为 ATR 倍数 (v7.0 核心)
    # 计算公式：(极值 - 开仓价) / ATR
    if "Long" in trade_direction:
        mfe_atr = (period_high - entry_price) / entry_atr
        mae_atr = (period_low - entry_price) / entry_atr
    else:
        mfe_atr = (entry_price - period_low) / entry_atr
        mae_atr = (entry_price - period_high) / entry_atr
    
    return {
        "MAE": mae_r,
        "MFE": mfe_r,
        "ETD": etd_r,
        "MAE_ATR": mae_atr,
        "MFE_ATR": mfe_atr,
        "MAD": mad_minutes,
        "Efficiency": efficiency,
        "High": period_high,
        "Low": period_low,
        "Charts": period_df, # 包含 ATR 列的数据
    }
