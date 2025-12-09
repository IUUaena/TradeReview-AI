import pandas as pd
import numpy as np
import pandas_ta as ta

def process_trades_to_rounds(df):
    """
    v7.0 核心算法：高性能交易回合生成引擎
    """
    if df is None or df.empty:
        return pd.DataFrame()
    
    # 1. 向量化预处理
    df = df.sort_values(by='timestamp', ascending=True).reset_index(drop=True)
    
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
    v8.4 深度价格行为分析 (修复 KeyError 问题)
    """
    if candles_df is None or candles_df.empty:
        return None
    
    # === 🛡️ 保险箱 1: 基础指标 (ATR & RVOL) ===
    try:
        candles_df['atr'] = candles_df.ta.atr(length=14)
        vol_ma = candles_df['volume'].rolling(20).mean().replace(0, 1)
        candles_df['rvol'] = candles_df['volume'] / vol_ma
    except Exception as e:
        print(f"⚠️ 基础指标计算失败: {e}")
        candles_df['atr'] = np.nan
        candles_df['rvol'] = 1.0
    
    # === 🛡️ 保险箱 2: K线形态 (Pattern - 修复版) ===
    # 修复逻辑：不依赖固定列名，直接取返回结果的第一列
    pattern_cols = ['CDL_ENGULFING', 'CDL_HAMMER', 'CDL_DOJI', 'CDL_STAR', 'CDL_SHOOTINGSTAR']
    for col in pattern_cols:
        candles_df[col] = 0 # 先初始化为0，防止后面报错
    try:
        # 1. 吞没 (Engulfing)
        res = candles_df.ta.cdl_pattern(name="engulfing")
        if res is not None and not res.empty: candles_df['CDL_ENGULFING'] = res.iloc[:, 0]
        
        # 2. 锤子 (Hammer)
        res = candles_df.ta.cdl_pattern(name="hammer")
        if res is not None and not res.empty: candles_df['CDL_HAMMER'] = res.iloc[:, 0]
        
        # 3. 十字星 (Doji)
        # 这里的名字经常变，所以用 iloc[:, 0] 最安全
        res = candles_df.ta.cdl_pattern(name="doji")
        if res is not None and not res.empty: candles_df['CDL_DOJI'] = res.iloc[:, 0]
        
        # 4. 启明/黄昏星 (Star)
        # 需要把 Morning 和 Evening 合并
        res_m = candles_df.ta.cdl_pattern(name="morningstar")
        res_e = candles_df.ta.cdl_pattern(name="eveningstar")
        
        star_val = 0
        if res_m is not None and not res_m.empty: star_val += res_m.iloc[:, 0]
        if res_e is not None and not res_e.empty: star_val += res_e.iloc[:, 0]
        candles_df['CDL_STAR'] = star_val
        
        # 5. 流星线 (Shooting Star)
        res = candles_df.ta.cdl_pattern(name="shootingstar")
        if res is not None and not res.empty: candles_df['CDL_SHOOTINGSTAR'] = res.iloc[:, 0]
    except Exception as e:
        print(f"⚠️ 形态识别部分失败 (非致命): {e}")
    
    # 3. 截取持仓期间
    lookback_bars = 60
    lookback_ms = lookback_bars * 60 * 1000 
    trade_mask = (candles_df['timestamp'] >= open_ts - lookback_ms) & (candles_df['timestamp'] <= close_ts + (5*60*1000))
    period_df = candles_df.loc[trade_mask].copy()
    
    if period_df.empty:
        return None
    
    # === 🛡️ 保险箱 3: 结构位 (Structure) ===
    structure_info = "无明显结构"
    nearest_res = None
    nearest_sup = None
    
    try:
        window = 5 
        period_df['is_high'] = period_df['high'].rolling(window*2+1, center=True).max() == period_df['high']
        period_df['is_low'] = period_df['low'].rolling(window*2+1, center=True).min() == period_df['low']
        
        pre_entry_df = period_df[period_df['timestamp'] < open_ts]
        
        if not pre_entry_df.empty:
            resistances = pre_entry_df[pre_entry_df['is_high']]['high'].tail(3).tolist()
            supports = pre_entry_df[pre_entry_df['is_low']]['low'].tail(3).tolist()
            
            nearest_res = min([r for r in resistances if r > entry_price], default=None)
            nearest_sup = max([s for s in supports if s < entry_price], default=None)
            
            dist_to_res = (nearest_res - entry_price) / entry_price * 100 if nearest_res else 999
            dist_to_sup = (entry_price - nearest_sup) / entry_price * 100 if nearest_sup else 999
            
            if nearest_res and dist_to_res < 0.5:
                structure_info = f"⚠️ 逼近阻力位 ({nearest_res:.2f})"
            elif nearest_sup and dist_to_sup < 0.5:
                structure_info = f"✅ 踩在支撑位 ({nearest_sup:.2f})"
            elif nearest_res and nearest_sup:
                structure_info = "⇕ 区间震荡中"
    except Exception as e:
        print(f"⚠️ 结构分析失败: {e}")
    
    # === 4. 汇总数据 ===
    pattern_signal_str = "无显著形态"
    try:
        target_indices = period_df[period_df['timestamp'] >= open_ts].index
        if len(target_indices) > 0:
            entry_idx_loc = period_df.index.get_indexer([target_indices[0]])[0]
            scan_range = period_df.iloc[max(0, entry_idx_loc-3) : entry_idx_loc+1]
            patterns_found = set()
            for idx, row in scan_range.iterrows():
                if row.get('CDL_ENGULFING', 0) != 0: patterns_found.add("吞没")
                if row.get('CDL_HAMMER', 0) != 0: patterns_found.add("锤子")
                if row.get('CDL_DOJI', 0) != 0: patterns_found.add("十字星")
                if row.get('CDL_STAR', 0) != 0: patterns_found.add("星")
                if row.get('CDL_SHOOTINGSTAR', 0) != 0: patterns_found.add("流星")
            if patterns_found:
                pattern_signal_str = ",".join(list(patterns_found))
    except:
        pass
    
    # 基础指标
    first_atr = period_df.iloc[0]['atr']
    entry_atr = first_atr if pd.notna(first_atr) else entry_price * 0.01
    
    real_hold_df = period_df[(period_df['timestamp'] >= open_ts) & (period_df['timestamp'] <= close_ts)]
    
    avg_rvol = 1.0
    max_rvol = 1.0
    if not real_hold_df.empty:
        avg_rvol = float(real_hold_df['rvol'].mean())
        max_rvol = float(real_hold_df['rvol'].max())
    
    # 极值
    period_high = period_df['high'].max()
    period_low = period_df['low'].min()
    
    max_profit_amt = 0.0
    max_loss_amt = 0.0
    final_pnl_amt = 0.0
    mad_minutes = 0
    mfe_atr = 0
    mae_atr = 0
    
    calc_df = period_df[(period_df['timestamp'] >= open_ts) & (period_df['timestamp'] <= close_ts)]
    
    if not calc_df.empty:
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
    
    safe_risk = risk_amount if risk_amount > 0 else 1.0
    mfe_r = max_profit_amt / safe_risk
    mae_r = max_loss_amt / safe_risk
    etd_r = (max_profit_amt - final_pnl_amt) / safe_risk
    
    return {
        "MAE": mae_r, "MFE": mfe_r, "ETD": etd_r,
        "MAE_ATR": mae_atr, "MFE_ATR": mfe_atr,
        "MAD": mad_minutes, "Efficiency": efficiency,
        "RVOL": avg_rvol, "Max_RVOL": max_rvol, "Pattern": pattern_signal_str,
        "Structure": structure_info,
        "Resistance": nearest_res,
        "Support": nearest_sup,
        "High": period_high, "Low": period_low, "Charts": period_df
    }
