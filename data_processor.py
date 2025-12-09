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
    v8.1 深度价格行为分析 (含 Volume + Pattern)
    """
    if candles_df is None or candles_df.empty:
        return None
    
    # 1. 计算技术指标 (ATR, RVOL, Patterns)
    detected_patterns = []
    
    try:
        # ATR (14)
        candles_df['atr'] = candles_df.ta.atr(length=14)
        
        # RVOL
        vol_ma = candles_df['volume'].rolling(20).mean().replace(0, 1)
        candles_df['rvol'] = candles_df['volume'] / vol_ma
        
        # === 🕯️ K线形态识别 (Pattern Recognition) ===
        # 只计算特定的几种强形态
        # 结果：100(看涨), -100(看跌), 0(无)
        
        # 吞没形态
        candles_df['CDL_ENGULFING'] = candles_df.ta.cdl_pattern(name="engulfing")['CDL_ENGULFING']
        # 锤子线
        candles_df['CDL_HAMMER'] = candles_df.ta.cdl_pattern(name="hammer")['CDL_HAMMER']
        # 十字星
        candles_df['CDL_DOJI'] = candles_df.ta.cdl_pattern(name="doji")['CDL_DOJI10_0.1']
        # 启明/黄昏之星
        morning_star = candles_df.ta.cdl_pattern(name="morningstar")['CDL_MORNINGSTAR']
        evening_star = candles_df.ta.cdl_pattern(name="eveningstar")['CDL_EVENINGSTAR']
        candles_df['CDL_STAR'] = morning_star + evening_star
        # 流星线
        candles_df['CDL_SHOOTINGSTAR'] = candles_df.ta.cdl_pattern(name="shootingstar")['CDL_SHOOTINGSTAR']
    except Exception as e:
        print(f"指标计算失败: {e}")
        candles_df['atr'] = np.nan
        candles_df['rvol'] = 1.0
        # 初始化形态列为 0
        candles_df['CDL_ENGULFING'] = 0
        candles_df['CDL_HAMMER'] = 0
        candles_df['CDL_DOJI'] = 0
        candles_df['CDL_STAR'] = 0
        candles_df['CDL_SHOOTINGSTAR'] = 0
    
    # 2. 截取持仓期间 (用于绘图)
    # buffer: 往前多取 5 根，往后多取 5 根，方便看形态
    buffer_ms = 5 * 60 * 1000
    trade_mask = (candles_df['timestamp'] >= open_ts - buffer_ms) & (candles_df['timestamp'] <= close_ts + buffer_ms)
    period_df = candles_df.loc[trade_mask].copy()
    
    if period_df.empty:
        return None
    
    # === 🕵️‍♂️ 侦探模式：寻找入场前的信号 ===
    # 我们只关心开仓那一刻 (open_ts) 及其前 3 根 K 线有没有出现形态
    # 找到开仓时间对应的索引
    pattern_signal_str = "无显著形态"
    try:
        # 找到最接近 open_ts 的行的索引
        entry_rows = period_df[period_df['timestamp'] >= open_ts]
        if not entry_rows.empty:
            entry_idx = entry_rows.index[0]
            entry_idx_loc = period_df.index.get_loc(entry_idx)
            
            # 扫描 entry 前后 3 根 K 线
            scan_start = max(0, entry_idx_loc - 3)
            scan_end = min(len(period_df), entry_idx_loc + 1)
            scan_range = period_df.iloc[scan_start:scan_end]
            
            patterns_found = set()
            for idx, row in scan_range.iterrows():
                if row.get('CDL_ENGULFING', 0) != 0: 
                    patterns_found.add("吞没")
                if row.get('CDL_HAMMER', 0) != 0: 
                    patterns_found.add("锤子")
                if row.get('CDL_DOJI', 0) != 0: 
                    patterns_found.add("十字星")
                if row.get('CDL_STAR', 0) != 0: 
                    patterns_found.add("启明/黄昏星")
                if row.get('CDL_SHOOTINGSTAR', 0) != 0: 
                    patterns_found.add("流星线")
            
            pattern_signal_str = ",".join(list(patterns_found)) if patterns_found else "无显著形态"
    except Exception as e:
        print(f"形态检测失败: {e}")
        pattern_signal_str = "检测失败"
    
    # 获取开仓时的 ATR
    first_atr = period_df.iloc[0]['atr']
    entry_atr = first_atr if pd.notna(first_atr) else entry_price * 0.01
    
    # 平均 RVOL (只统计持仓部分，排除 buffer)
    real_hold_df = period_df[(period_df['timestamp'] >= open_ts) & (period_df['timestamp'] <= close_ts)]
    avg_rvol = real_hold_df['rvol'].mean() if not real_hold_df.empty else 1.0
    max_rvol = real_hold_df['rvol'].max() if not real_hold_df.empty else 1.0
    
    # 3. 计算极值
    period_high = period_df['high'].max()
    period_low = period_df['low'].min()
    
    max_profit_amt = 0.0
    max_loss_amt = 0.0
    final_pnl_amt = 0.0
    
    # 4. 计算 MAD & Efficiency
    # 注意：计算指标时要严格限制在 open_ts 和 close_ts 之间
    calc_df = period_df[(period_df['timestamp'] >= open_ts) & (period_df['timestamp'] <= close_ts)]
    
    if "Long" in trade_direction:
        max_profit_amt = (period_high - entry_price) * amount
        max_loss_amt = (period_low - entry_price) * amount
        final_pnl_amt = (exit_price - entry_price) * amount
        mad_minutes = len(calc_df[calc_df['close'] < entry_price])
        mfe_atr = (period_high - entry_price) / entry_atr
        mae_atr = (period_low - entry_price) / entry_atr
    else:
        max_profit_amt = (entry_price - period_low) * amount
        max_loss_amt = (entry_price - period_high) * amount
        final_pnl_amt = (entry_price - exit_price) * amount
        mad_minutes = len(calc_df[calc_df['close'] > entry_price])
        mfe_atr = (entry_price - period_low) / entry_atr
        mae_atr = (entry_price - period_high) / entry_atr
    
    efficiency = 0.0
    if max_profit_amt > 0:
        efficiency = final_pnl_amt / max_profit_amt
    
    # 6. R 倍数
    safe_risk = risk_amount if risk_amount > 0 else 1.0
    mfe_r = max_profit_amt / safe_risk
    mae_r = max_loss_amt / safe_risk
    etd_r = (max_profit_amt - final_pnl_amt) / safe_risk
    
    return {
        "MAE": mae_r,
        "MFE": mfe_r,
        "ETD": etd_r,
        "MAE_ATR": mae_atr,
        "MFE_ATR": mfe_atr,
        "MAD": mad_minutes,
        "Efficiency": efficiency,
        "RVOL": avg_rvol,
        "Max_RVOL": max_rvol,
        "Pattern": pattern_signal_str, # 👈 新增：检测到的形态
        "High": period_high,
        "Low": period_low,
        "Charts": period_df, 
    }
