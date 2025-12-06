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
        
        # 1. 交易数据表 (保持不变)
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
                strategy TEXT,
                ai_analysis TEXT,
                UNIQUE(id, api_key_tag)
            )
        ''')
        
        # 2. 新增：API 账号管理表
        c.execute('''
            CREATE TABLE IF NOT EXISTS api_configs (
                api_key TEXT PRIMARY KEY,
                secret TEXT,
                alias TEXT
            )
        ''')
        
        conn.commit()
        conn.close()

    # ===========================
    #  🔑 账户管理功能 (新增)
    # ===========================
    
    def save_api_key(self, api_key, secret, alias):
        """保存或更新 API Key"""
        clean_key = api_key.strip()
        clean_secret = secret.strip()
        clean_alias = alias.strip()
        
        if not clean_key or not clean_secret or not clean_alias:
            return False, "❌ 所有字段都不能为空"
            
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            # 如果 Key 存在则更新，不存在则插入
            c.execute('INSERT OR REPLACE INTO api_configs (api_key, secret, alias) VALUES (?, ?, ?)', 
                      (clean_key, clean_secret, clean_alias))
            conn.commit()
            return True, f"✅ 账户【{clean_alias}】保存成功！"
        except Exception as e:
            return False, str(e)
        finally:
            conn.close()

    def get_all_accounts(self):
        """获取所有已保存的账户 (用于下拉菜单)"""
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query("SELECT alias, api_key FROM api_configs", conn)
        conn.close()
        return df

    def get_credentials(self, api_key):
        """根据 Key 获取 Secret"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT secret FROM api_configs WHERE api_key = ?", (api_key,))
        result = c.fetchone()
        conn.close()
        return result[0] if result else None

    def delete_account_full(self, api_key):
        """🧨 核弹按钮：删除账号配置 + 所有相关历史交易"""
        key_tag = api_key.strip()[-4:]
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # 1. 删交易数据
        c.execute("DELETE FROM trades WHERE api_key_tag = ?", (key_tag,))
        trades_count = c.rowcount
        
        # 2. 删账号配置
        c.execute("DELETE FROM api_configs WHERE api_key = ?", (api_key,))
        
        conn.commit()
        conn.close()
        return trades_count

    # ===========================
    #  📉 交易所连接与抓取 (保持之前的优秀逻辑)
    # ===========================

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
        
        try:
            if progress_callback: progress_callback("📡 连接交易所获取合约名录...", 1)
            markets = exchange.load_markets()
            coin_map = {}
            all_usdt_symbols = []
            for s, m in markets.items():
                if '/USDT' in s and m.get('contract'):
                    all_usdt_symbols.append(s)
                    base = m.get('base')
                    if base: coin_map[base.upper()] = s
            all_usdt_symbols = sorted(list(set(all_usdt_symbols)))
            total_count = len(all_usdt_symbols)
        except Exception as e:
            return f"❌ 连接失败: {str(e)}", 0

        key_tag = api_key.strip()[-4:]
        all_trades = []

        # --- 模式 A: 快速 ---
        if mode == 'recent':
            if progress_callback: progress_callback(f"🚀 准备扫描 {total_count} 个合约 (最近7天)...", 5)
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
                except: continue

        # --- 模式 B: 深度 (最近1年倒序) ---
        elif mode == 'deep':
            if not target_coins_str: return "⚠️ 请输入币种", 0
            user_inputs = [s.strip().upper() for s in target_coins_str.split(',') if s.strip()]
            target_symbols = []
            for u_coin in user_inputs:
                if u_coin in coin_map: target_symbols.append(coin_map[u_coin])
                else: target_symbols.append(f"{u_coin}/USDT")
            
            if not target_symbols: return "❌ 无匹配合约", 0

            now_ts = exchange.milliseconds()
            stop_ts = int((datetime.now() - timedelta(days=365)).timestamp() * 1000)
            window_size = 7 * 24 * 60 * 60 * 1000
            total_targets = len(target_symbols)

            for i, symbol in enumerate(target_symbols):
                current_end = now_ts
                while current_end > stop_ts:
                    current_start = current_end - window_size
                    if current_start < stop_ts: current_start = stop_ts 
                    
                    msg = f"⛏️ [{i+1}/{total_targets}] {symbol}: 查区间 {datetime.fromtimestamp(current_start/1000).strftime('%Y-%m-%d')}..."
                    if progress_callback: progress_callback(msg, 50)
                    
                    try:
                        trades = exchange.fetch_my_trades(symbol=symbol, since=current_start, limit=1000, params={'endTime': current_end})
                        if trades: all_trades.extend(trades)
                        current_end = current_start
                        if current_end <= stop_ts: break
                        time.sleep(0.3)
                    except:
                        current_end = current_start 
                        time.sleep(1)

        if not all_trades: return f"✅ 扫描完成。未发现新数据。", 0
        if progress_callback: progress_callback(f"💾 保存 {len(all_trades)} 条记录...", 95)
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
                ''', (str(t['id']), t['timestamp'], t['datetime'], t['symbol'], t['side'], float(t['price'] or 0), float(t['amount'] or 0), float(t['cost'] or 0), fee, 'USDT', pnl, key_tag))
                if c.rowcount > 0: count += 1
            except: continue
        conn.commit()
        conn.close()
        return count

    def load_trades(self, api_key):
        conn = sqlite3.connect(self.db_path)
        key_tag = api_key.strip()[-4:] if api_key else ""
        try:
            df = pd.read_sql_query("SELECT * FROM trades WHERE api_key_tag = ? ORDER BY timestamp DESC", conn, params=(key_tag,))
        except: df = pd.DataFrame()
        conn.close()
        return df

    # ===========================
    #  📝 笔记与 AI 数据更新
    # ===========================
    def update_trade_note(self, trade_id, note_text, strategy_text=None, api_key=None):
        """更新交易笔记和策略"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            # 如果表中有strategy列则更新，否则只更新notes（向后兼容）
            if api_key:
                key_tag = api_key.strip()[-4:]
                if strategy_text is not None:
                    # 尝试更新strategy字段（如果存在）
                    try:
                        c.execute("UPDATE trades SET notes = ?, strategy = ? WHERE id = ? AND api_key_tag = ?", 
                                (note_text, strategy_text, trade_id, key_tag))
                    except sqlite3.OperationalError:
                        # 如果strategy列不存在，只更新notes
                        c.execute("UPDATE trades SET notes = ? WHERE id = ? AND api_key_tag = ?", 
                                (note_text, trade_id, key_tag))
                else:
                    c.execute("UPDATE trades SET notes = ? WHERE id = ? AND api_key_tag = ?", 
                            (note_text, trade_id, key_tag))
            else:
                if strategy_text is not None:
                    try:
                        c.execute("UPDATE trades SET notes = ?, strategy = ? WHERE id = ?", 
                                (note_text, strategy_text, trade_id))
                    except sqlite3.OperationalError:
                        c.execute("UPDATE trades SET notes = ? WHERE id = ?", (note_text, trade_id))
                else:
                    c.execute("UPDATE trades SET notes = ? WHERE id = ?", (note_text, trade_id))
            conn.commit()
            return True
        except Exception as e:
            print(f"Update Note Error: {e}")
            return False
        finally:
            conn.close()

    def update_ai_analysis(self, trade_id, analysis_text, api_key=None):
        """更新 AI 分析结果"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            if api_key:
                key_tag = api_key.strip()[-4:]
                c.execute("UPDATE trades SET ai_analysis = ? WHERE id = ? AND api_key_tag = ?", (analysis_text, trade_id, key_tag))
            else:
                c.execute("UPDATE trades SET ai_analysis = ? WHERE id = ?", (analysis_text, trade_id))
            conn.commit()
            return True
        except Exception as e:
            print(f"Update AI Error: {e}")
            return False
        finally:
            conn.close()