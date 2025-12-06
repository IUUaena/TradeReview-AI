import ccxt
import pandas as pd
import sqlite3
import time
from datetime import datetime, timedelta

class TradeDataEngine:
    def __init__(self, db_path='trade_review.db'):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id TEXT,
                timestamp INTEGER,
                datetime TEXT,
                symbol TEXT,
                side TEXT,
                price REAL,
                amount REAL,
                cost REAL,
                fee REAL,
                fee_currency TEXT,
                pnl REAL,
                api_key_tag TEXT, 
                notes TEXT,
                ai_analysis TEXT,
                UNIQUE(id, api_key_tag)
            )
        ''')
        conn.commit()
        conn.close()

    def get_exchange(self, api_key, secret):
        """连接币安 U本位合约"""
        try:
            exchange = ccxt.binance({
                'apiKey': api_key,
                'secret': secret,
                'timeout': 30000,
                'enableRateLimit': True,
                'options': {'defaultType': 'future'} 
            })
            return exchange
        except:
            return None

    def fetch_and_save(self, api_key, secret, mode, target_coins_str=None, progress_callback=None):
        exchange = self.get_exchange(api_key, secret)
        if not exchange: return "❌ 交易所连接失败，请检查网络或 Key", 0

        key_tag = api_key[-4:]
        all_trades = []

        try:
            # 1. 获取所有交易对信息
            if progress_callback: progress_callback("📡 正在获取币安合约市场列表...", 5)
            markets = exchange.load_markets()
            
            # --- 🚀 核心优化：只保留 USDT 本位合约 ---
            # 逻辑：必须是合约(swap/future) 且 结算货币是 USDT
            valid_symbols = []
            for symbol, market in markets.items():
                is_contract = market.get('type') in ['future', 'swap'] # 永续或交割
                is_usdt = market.get('quote') == 'USDT'                # 必须是 USDT 结算
                # 排除 USDC 本位 或 币本位 (USD)
                if is_contract and is_usdt:
                    valid_symbols.append(symbol)
            
            print(f"DEBUG: 筛选出 {len(valid_symbols)} 个 USDT 本位合约")

        except Exception as e:
            return f"❌ 获取市场列表失败: {str(e)}", 0

        # --- 模式 A: 快速扫描 (严格筛选后的名单) ---
        if mode == 'recent':
            # 设定时间范围：7天前
            since_time = int((datetime.now() - timedelta(days=7)).timestamp() * 1000)
            
            total_symbols = len(valid_symbols)
            if progress_callback: progress_callback(f"🚀 准备扫描 {total_symbols} 个 USDT 合约...", 10)
            
            for i, symbol in enumerate(valid_symbols):
                try:
                    # 进度条优化
                    if i % 5 == 0 and progress_callback:
                        pct = 10 + int((i / total_symbols) * 80)
                        progress_callback(f"🔍 扫描: {symbol} ({i}/{total_symbols})", pct)

                    # 抓取
                    trades = exchange.fetch_my_trades(symbol=symbol, since=since_time, limit=100)
                    if trades:
                        all_trades.extend(trades)
                        time.sleep(0.05) # 稍微快一点点，因为有些币可能压根没开过单
                except Exception as e:
                    continue

        # --- 模式 B: 深度挖掘 (指定币种) ---
        elif mode == 'deep':
            if not target_coins_str:
                return "⚠️ 深度模式必须手动输入币种 (如 BTC, ETH)", 0
            
            # 智能匹配用户输入的币种
            target_symbols = []
            for s in target_coins_str.split(','):
                s = s.strip().upper()
                if not s: continue
                
                # 在我们筛选出的 USDT 列表中查找
                # 比如用户输 BTC，我们找 BTC/USDT:USDT
                matched = False
                for v_sym in valid_symbols:
                    # 匹配逻辑：如果 valid_symbol 包含用户输入的 (例如 BTC/USDT)
                    if v_sym.startswith(s + "/"):
                        target_symbols.append(v_sym)
                        matched = True
                        break
                
                if not matched:
                    # 如果没找到，尝试硬拼一个最常见的格式
                    target_symbols.append(f"{s}/USDT")

            one_year_ago = int((datetime.now() - timedelta(days=365)).timestamp() * 1000)
            
            for i, symbol in enumerate(target_symbols):
                msg = f"⛏️ 深度挖掘 {symbol}..."
                if progress_callback: progress_callback(msg, int((i / len(target_symbols)) * 90))
                
                since = one_year_ago
                while True:
                    try:
                        trades = exchange.fetch_my_trades(symbol=symbol, since=since, limit=1000)
                        if not trades: break
                        
                        all_trades.extend(trades)
                        since = trades[-1]['timestamp'] + 1
                        
                        if since > exchange.milliseconds(): break
                        time.sleep(0.2)
                    except Exception as e:
                        print(f"⚠️ {symbol} 抓取中断: {e}")
                        break

        # --- 入库逻辑 ---
        if not all_trades:
            return "✅ 扫描完成，但在指定范围内没有发现新交易。", 0

        if progress_callback: progress_callback(f"💾 正在保存 {len(all_trades)} 条记录...", 95)
        new_count = self._save_to_db(all_trades, key_tag)
        
        if progress_callback: progress_callback("✅ 完成！", 100)
        return "成功", new_count

    def _save_to_db(self, trades, key_tag):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        count = 0
        for t in trades:
            try:
                pnl = 0.0
                info = t.get('info', {})
                if info and 'realizedPnl' in info:
                    pnl = float(info['realizedPnl'])
                
                fee_cost = 0.0
                if t.get('fee') and 'cost' in t['fee']:
                    fee_cost = float(t['fee']['cost'])

                trade_id = str(t.get('id', ''))
                ts = t.get('timestamp', 0)
                dt = t.get('datetime', '')
                symbol = t.get('symbol', '')
                side = t.get('side', '')
                price = float(t.get('price', 0))
                amount = float(t.get('amount', 0))
                cost = float(t.get('cost', 0))

                c.execute('''
                    INSERT OR IGNORE INTO trades 
                    (id, timestamp, datetime, symbol, side, price, amount, cost, fee, fee_currency, pnl, api_key_tag)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (trade_id, ts, dt, symbol, side, price, amount, cost, fee_cost, 'USDT', pnl, key_tag))
                
                if c.rowcount > 0: count += 1
            except Exception:
                continue

        conn.commit()
        conn.close()
        return count

    def load_trades(self, api_key):
        conn = sqlite3.connect(self.db_path)
        key_tag = api_key[-4:] if api_key else ""
        try:
            df = pd.read_sql_query("SELECT * FROM trades WHERE api_key_tag = ? ORDER BY timestamp DESC", conn, params=(key_tag,))
        except:
            df = pd.DataFrame()
        conn.close()
        return df

    def delete_account_data(self, api_key):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        key_tag = api_key[-4:] if api_key else ""
        c.execute("DELETE FROM trades WHERE api_key_tag = ?", (key_tag,))
        row_count = c.rowcount
        conn.commit()
        conn.close()
        return row_count