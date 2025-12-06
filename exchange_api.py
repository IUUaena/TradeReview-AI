import ccxt
import pandas as pd
from datetime import datetime
import time

def safe_float(value, default=0.0):
    try:
        if value is None: return default
        return float(value)
    except: return default

def get_binance_futures_history(api_key, api_secret, progress_callback=None):
    """
    全量扫描：自动获取所有上线的 USDT 合约，并抓取交易记录。

    Args:
        progress_callback: 一个函数，用来告诉前端由于进度条走到哪里了

    """
    print("--- 启动全量扫描模式 ---")
    
    # 1. 初始化
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
        # 2. 获取所有交易对 (下载菜单)
        if progress_callback: progress_callback("正在下载币安所有合约交易对信息...", 0)
        exchange.load_markets()
        
        # 3. 筛选出所有 USDT 结尾的合约 (过滤掉币本位和 USDC 本位)
        # 这里的逻辑是：必须是 USDT 结算，且是合约(swap)
        target_symbols = []
        for symbol, market in exchange.markets.items():
            if market.get('quote') == 'USDT' and market.get('contract') == True:
                target_symbols.append(symbol)
        
        total_symbols = len(target_symbols)
        print(f"✅ 发现 {total_symbols} 个 USDT 合约交易对")
        if total_symbols == 0:
            return None, "未找到任何 USDT 合约交易对，请检查网络或 API 权限。"

        # 4. 地毯式搜索
        all_trades = []
        
        # 为了不让用户等太久，我们打印进度
        for index, symbol in enumerate(target_symbols):
            # 更新前端进度条 (0.0 到 1.0)
            progress = (index + 1) / total_symbols
            status_text = f"正在扫描 ({index+1}/{total_symbols}): {symbol}"
            
            if progress_callback: progress_callback(status_text, progress)
            print(status_text) # 终端也打印一下
            try:
                # limit=1000 是币安单次请求的极限
                trades = exchange.fetch_my_trades(symbol=symbol, limit=1000)
                
                if trades:
                    print(f"   🎉 发现数据! {symbol}: {len(trades)} 条")
                    all_trades.extend(trades)
                
                # 关键：稍微停顿，防止被币安封 IP (Rate Limit)
                # 只有当找到数据时才不需要停太久，没数据时跑快点？
                # 币安权重计算很复杂，为了安全，我们保持匀速
                time.sleep(0.05) 
                
            except Exception as e:
                # 某些特殊已经下架的币种可能会报错，忽略它
                # print(f"   跳过 {symbol}: {e}") 
                continue

        if not all_trades:
            return None, "扫描了所有币种，但未发现任何交易记录。请确认：1.这是合约账号吗？2.近期有交易吗？"

        # 5. 统一清洗数据
        if progress_callback: progress_callback("正在整理清洗数据...", 0.99)
        
        data_list = []
        for i, t in enumerate(all_trades):
            try:
                # 提取逻辑
                row = {
                    'id': str(t.get('id', f'unknown_{i}')),
                    'exchange': 'Binance',
                    'symbol': str(t.get('symbol', 'Unknown')),
                    'side': str(t.get('side', 'unknown')),
                    'price': safe_float(t.get('price')),
                    'qty': safe_float(t.get('amount')),
                    'realized_pnl': 0.0,
                    'commission': 0.0,
                    'timestamp': t.get('timestamp', int(time.time()*1000)),
                    'date_str': '',
                    'notes': '',        
                    'ai_analysis': ''   
                }
                
                # 补充 PnL
                info = t.get('info', {})
                if isinstance(info, dict):
                    row['realized_pnl'] = safe_float(info.get('realizedPnl'))
                
                # 补充 Fee
                fee = t.get('fee')
                if fee and isinstance(fee, dict):
                    row['commission'] = safe_float(fee.get('cost'))
                    
                # 补充时间字符串
                row['date_str'] = datetime.fromtimestamp(row['timestamp'] / 1000).strftime('%Y-%m-%d %H:%M:%S')
                data_list.append(row)
            except:
                continue

        df = pd.DataFrame(data_list)
        df = df.sort_values(by='timestamp', ascending=False)
        
        return df, "success"

    except Exception as e:
        import traceback
        traceback.print_exc()
        return None, f"扫描过程中断: {str(e)}"
