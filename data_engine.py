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
        clean_key = api_key.strip() if api_key else ""
        clean_secret = secret.strip() if secret else ""
        try:
            exchange = ccxt.binance({
                'apiKey': clean_key,
                'secret': clean_secret,
                'timeout': 30000,
                'enableRateLimit': True,
                'options': {'defaultType': 'future'} 
            })
            return exchange
        except:
            return None

    def fetch_and_save(self, api_key, secret, mode, target_coins_str=None, progress_callback=None):
        exchange = self.get_exchange(api_key, secret)
        if not exchange: return "❌ 交易所对象创建失败", 0
        
        # --- 预处理：建立币种映射 ---
        try:
            if progress_callback: progress_callback("📡 连接交易所获取合约名录...", 1)
            markets = exchange.load_markets()
            
            # 建立映射表
            coin_map = {}
            all_usdt_symbols = []
            
            for s, m in markets.items():
                if '/USDT' in s and m.get('contract'):
                    all_usdt_symbols.append(s)
                    base = m.get('base')
                    if base:
                        coin_map[base.upper()] = s
            
            all_usdt_symbols = sorted(list(set(all_usdt_symbols)))
            total_count = len(all_usdt_symbols)

        except Exception as e:
            return f"❌ 连接失败: {str(e)}", 0

        key_tag = api_key.strip()[-4:]
        all_trades = []

        # =========================================================
        # 模式 A: 快速扫描 (最近7天)
        # =========================================================
        if mode == 'recent':
            if progress_callback: 
                progress_callback(f"🚀 准备扫描 {total_count} 个合约 (最近7天)...", 5)
            
            since_time = int((datetime.now() - timedelta(days=7)).timestamp() * 1000)
            
            for i, symbol in enumerate(all_usdt_symbols):
                try:
                    if i % 5 == 0 and progress_callback:
                        pct = 5 + int((i / total_count) * 90)
                        progress_callback(f"🔍 [{i}/{total_count}] 扫描: {symbol}", pct)
                        
                    trades = exchange.fetch_my_trades(symbol=symbol, since=since_time, limit=100)
                    if trades: 
                        all_trades.extend(trades)
                        time.sleep(0.05) 
                except:
                    continue

        # =========================================================
        # 模式 B: 深度挖掘 (最近1年，倒序切片)
        # =========================================================
        elif mode == 'deep':
            if not target_coins_str:
                return "⚠️ 请输入币种", 0
            
            user_inputs = [s.strip().upper() for s in target_coins_str.split(',') if s.strip()]
            target_symbols = []
            
            for u_coin in user_inputs:
                if u_coin in coin_map:
                    target_symbols.append(coin_map[u_coin])
                else:
                    target_symbols.append(f"{u_coin}/USDT")

            if not target_symbols:
                 return "❌ 未找到匹配的合约，请检查拼写。", 0

            # --- 🕒 时间设置调整：最近1年 ---
            now_ts = exchange.milliseconds()
            # 核心修改：只回溯到 365 天前
            stop_ts = int((datetime.now() - timedelta(days=365)).timestamp() * 1000)
            
            # 窗口大小：7天
            window_size = 7 * 24 * 60 * 60 * 1000

            total_targets = len(target_symbols)

            for i, symbol in enumerate(target_symbols):
                current_end = now_ts
                
                while current_end > stop_ts:
                    current_start = current_end - window_size
                    if current_start < stop_ts:
                        current_start = stop_ts 

                    end_date_str = datetime.fromtimestamp(current_end/1000).strftime('%Y-%m-%d')
                    start_date_str = datetime.fromtimestamp(current_start/1000).strftime('%Y-%m-%d')
                    
                    msg = f"⛏️ [{i+1}/{total_targets}] {symbol}: 正在查 {start_date_str} 至 {end_date_str}..."
                    if progress_callback: progress_callback(msg, 50)
                    print(f"DEBUG: Checking {symbol} from {start_date_str} to {end_date_str}")

                    try:
                        trades = exchange.fetch_my_trades(
                            symbol=symbol, 
                            since=current_start, 
                            limit=1000, 
                            params={'endTime': current_end}
                        )
                        
                        if trades:
                            all_trades.extend(trades)
                        
                        current_end = current_start
                        if current_end <= stop_ts:
                            break
                        time.sleep(0.3)

                    except Exception:
                        current_end = current_start 
                        time.sleep(1)

        # =========================================================
        # 入库
        # =========================================================
        if not all_trades:
            return f"✅ 扫描完成。最近1年内未发现数据。", 0

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
                pnl = float(t.get('info', {}).get('realizedPnl', 0))
                fee = float(t.get('fee', {}).get('cost', 0)) if t.get('fee') else 0.0
                
                c.execute('''
                    INSERT OR IGNORE INTO trades 
                    (id, timestamp, datetime, symbol, side, price, amount, cost, fee, fee_currency, pnl, api_key_tag)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    str(t['id']), t['timestamp'], t['datetime'], t['symbol'], t['side'], 
                    float(t['price'] or 0), float(t['amount'] or 0), float(t['cost'] or 0), 
                    fee, 'USDT', pnl, key_tag
                ))
                if c.rowcount > 0: count += 1
            except:
                continue
        conn.commit()
        conn.close()
        return count

    def load_trades(self, api_key):
        conn = sqlite3.connect(self.db_path)
        key_tag = api_key.strip()[-4:] if api_key else ""
        try:
            df = pd.read_sql_query("SELECT * FROM trades WHERE api_key_tag = ? ORDER BY timestamp DESC", conn, params=(key_tag,))
        except:
            df = pd.DataFrame()
        conn.close()
        return df

    def delete_account_data(self, api_key):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        key_tag = api_key.strip()[-4:] if api_key else ""
        c.execute("DELETE FROM trades WHERE api_key_tag = ?", (key_tag,))
        n = c.rowcount
        conn.commit()
        conn.close()
        return n