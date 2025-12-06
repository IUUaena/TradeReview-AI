import pandas as pd
import numpy as np

def process_trades_to_rounds(df):
    """
    核心算法：将零散的成交记录 (Fills) 合并为完整的交易回合 (Round Trips)。

    逻辑：从仓位为0开始，直到仓位再次回归0，视为一笔完整交易。
    """
    if df is None or df.empty:
        return pd.DataFrame()

    # 1. 预处理：按时间正序排列（从旧到新），这对计算持仓至关重要
    df = df.sort_values(by='timestamp', ascending=True)
    
    rounds = []
    
    # 2. 按币种分组处理 (BTC的交易不能和ETH混在一起)
    grouped = df.groupby('symbol')
    
    for symbol, group in grouped:
        # 初始化当前回合的变量
        current_qty = 0.0
        current_pnl = 0.0
        current_commission = 0.0
        start_time = None
        
        # 记录这一回合包含的原始订单ID（方便未来关联笔记）
        trade_ids = []
        
        # 标记是否在持仓中
        in_position = False
        
        # side_direction: 1 (多头), -1 (空头), 0 (无)
        side_direction = 0 
        
        for index, row in group.iterrows():
            qty = float(row['qty'])
            price = float(row['price'])
            pnl = float(row['realized_pnl'])
            commission = float(row['commission'])
            timestamp = row['timestamp']
            side = row['side'].lower() # buy / sell
            
            # 确定方向符号
            # 注意：币安合约里，Buy是正向，Sell是负向（通常逻辑）
            # 但我们需要根据 current_qty 来判断是开仓还是平仓
            
            # 如果当前是空仓，这一笔就是开仓
            if current_qty == 0:
                in_position = True
                start_time = timestamp
                side_direction = 1 if side == 'buy' else -1
                trade_ids = [row['id']]
                
                current_pnl = pnl
                current_commission = commission
                
                # 更新持仓
                if side == 'buy': current_qty += qty
                else: current_qty -= qty
                
            else:
                # 已经在持仓中，这是加仓或减仓
                trade_ids.append(row['id'])
                current_pnl += pnl
                current_commission += commission
                
                prev_qty = current_qty
                if side == 'buy': current_qty += qty
                else: current_qty -= qty
                
                # 判断是否平仓 (仓位归零，或极度接近0)
                # 浮点数比较需要用 abs < 0.00001
                if abs(current_qty) < 0.000001:
                    # === 交易结束，打包数据 ===
                    end_time = timestamp
                    duration_minutes = (end_time - start_time) / 1000 / 60
                    
                    rounds.append({
                        'symbol': symbol,
                        'direction': 'Long' if side_direction == 1 else 'Short',
                        'open_time': start_time,
                        'close_time': end_time,
                        'open_date': pd.to_datetime(start_time, unit='ms').strftime('%Y-%m-%d %H:%M'),
                        'duration_min': round(duration_minutes, 1),
                        'total_pnl': round(current_pnl, 2),
                        'total_fee': round(current_commission, 2),
                        'net_pnl': round(current_pnl - current_commission, 2), # 净利润
                        'trade_count': len(trade_ids), # 这一单操作了几次
                        'status': 'Closed'
                    })
                    
                    # 重置状态
                    in_position = False
                    current_qty = 0
                    side_direction = 0

        # 循环结束后，如果还在持仓 (in_position == True)，说明有一笔未完成的单子
        if in_position:
             rounds.append({
                'symbol': symbol,
                'direction': 'Long' if side_direction == 1 else 'Short',
                'open_time': start_time,
                'close_time': group.iloc[-1]['timestamp'], # 暂用最后一条记录时间
                'open_date': pd.to_datetime(start_time, unit='ms').strftime('%Y-%m-%d %H:%M'),
                'duration_min': 'Holding',
                'total_pnl': round(current_pnl, 2), # 这里通常只有资金费率或部分止盈的钱
                'total_fee': round(current_commission, 2),
                'net_pnl': round(current_pnl - current_commission, 2),
                'trade_count': len(trade_ids),
                'status': 'Open (持仓中)'
            })

    # 转成 DataFrame
    if not rounds:
        return pd.DataFrame()
        
    results_df = pd.DataFrame(rounds)
    # 按平仓时间倒序（最近的完成单在最上面）
    results_df = results_df.sort_values(by='close_time', ascending=False)
    
    return results_df

