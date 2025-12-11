import ccxt
import pandas as pd
import sqlite3
import time
import os
from datetime import datetime, timedelta

class TradeDataEngine:
    def __init__(self, db_path=None):
        # --- 核心修改：强制使用绝对路径，避免"幽灵数据库"问题 ---
        if db_path is None:
            # 获取当前脚本所在目录的绝对路径
            basedir = os.path.abspath(os.path.dirname(__file__))
            # 优先使用data目录，如果不存在则使用脚本目录
            data_dir = os.path.join(basedir, 'data')
            if os.path.exists(data_dir) and os.path.isdir(data_dir):
                db_path = os.path.join(data_dir, 'trade_review.db')
            else:
                # 数据库文件固定放在脚本目录下，文件名固定为 trade_review.db
                db_path = os.path.join(basedir, 'trade_review.db')
            # 启动时打印路径以便调试
            print(f"数据库锁定位置: {db_path}")
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # 1. 交易数据表 (包含所有 v8.3 所需字段)
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
                screenshot TEXT,
                -- v3.0 新增核心字段 --
                mental_state TEXT,
                rr_ratio REAL,
                setup_rating INTEGER,
                process_tag TEXT,
                mistake_tags TEXT,
                -- v4.0 新增价格行为字段 --
                mae REAL,
                mfe REAL,
                etd REAL,
                -- v8.0/8.1 新增字段 --
                rvol REAL,
                pattern_signal TEXT,
                UNIQUE(id, api_key_tag)
            )
        ''')
        
        # 2. API 账号管理表
        c.execute('''
            CREATE TABLE IF NOT EXISTS api_configs (
                api_key TEXT PRIMARY KEY,
                secret TEXT,
                alias TEXT
            )
        ''')
        
        # 3. AI 阶段性报告表 (含 title)
        c.execute('''
            CREATE TABLE IF NOT EXISTS ai_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_type TEXT,
                start_date TEXT,
                end_date TEXT,
                trade_count INTEGER,
                total_pnl REAL,
                win_rate REAL,
                ai_feedback TEXT,
                created_at INTEGER,
                api_key_tag TEXT,
                title TEXT
            )
        ''')
        
        # 4. 策略库表
        c.execute('''
            CREATE TABLE IF NOT EXISTS strategies (
                name TEXT PRIMARY KEY,
                description TEXT
            )
        ''')
        
        # 5. 系统配置表
        c.execute('''
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        
        conn.commit()
        conn.close()

    # ===========================
    #  🔑 账户管理功能
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
            c.execute('INSERT OR REPLACE INTO api_configs (api_key, secret, alias) VALUES (?, ?, ?)', 
                      (clean_key, clean_secret, clean_alias))
            conn.commit()
            return True, f"✅ 账户【{clean_alias}】保存成功！"
        except Exception as e:
            return False, str(e)
        finally:
            conn.close()

    def get_all_accounts(self):
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query("SELECT alias, api_key FROM api_configs", conn)
        conn.close()
        return df

    def get_credentials(self, api_key):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("SELECT secret FROM api_configs WHERE api_key = ?", (api_key,))
        result = c.fetchone()
        conn.close()
        return result[0] if result else None

    def delete_account_full(self, api_key):
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
    #  📉 交易所连接与抓取
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
        try:
            exchange = self.get_exchange(api_key, secret)
            if not exchange: 
                return "❌ 交易所对象创建失败", 0
            
            # 1. 获取市场名录 (核心修改：支持 USDC)
            try:
                if progress_callback: progress_callback("📡 连接交易所获取合约名录...", 1)
                markets = exchange.load_markets()
                
                coin_map = {} 
                all_target_symbols = [] # 包含 USDT 和 USDC
                
                for s, m in markets.items():
                    # 过滤条件：必须是合约，且以 /USDT 或 /USDC 结尾
                    is_target_contract = ('/USDT' in s or '/USDC' in s) and m.get('contract')
                    
                    if is_target_contract:
                        all_target_symbols.append(s)
                        base = m.get('base')
                        if base: 
                            base_key = base.upper()
                            if base_key not in coin_map:
                                coin_map[base_key] = []
                            if s not in coin_map[base_key]:
                                coin_map[base_key].append(s)
                                
                all_target_symbols = sorted(list(set(all_target_symbols)))
                total_count = len(all_target_symbols)
                
            except Exception as e:
                return f"❌ 连接失败: {str(e)}", 0

            key_tag = api_key.strip()[-4:]
            all_trades = []

            # --- 辅助函数：抓取资金费用 (v8.3 新增) ---
            def fetch_funding_income(symbol, since_ts, end_ts=None):
                """抓取资金费用并转换为 Pseudo-Trade 格式"""
                funding_trades = []
                try:
                    params = {'incomeType': 'FUNDING_FEE'}
                    if end_ts: params['endTime'] = end_ts
                    
                    # 抓取 Income
                    incomes = exchange.fetch_income(symbol, since=since_ts, limit=1000, params=params)
                    
                    for inc in incomes:
                        # 转换格式
                        funding_trades.append({
                            'id': f"FUND_{inc['id']}", # 特殊 ID 防止冲突
                            'timestamp': inc['timestamp'],
                            'datetime': inc['datetime'],
                            'symbol': inc['symbol'],
                            'side': 'FUNDING', # 特殊方向
                            'price': 0.0,
                            'amount': 0.0,
                            'cost': 0.0,
                            'fee': None, # 资金费没有手续费
                            'info': {'realizedPnl': inc['amount']}, # 将金额放入 PnL
                            'type': 'funding'
                        })
                except Exception:
                    pass
                return funding_trades

            # --- 模式 A: 快速同步 ---
            if mode == 'recent':
                if progress_callback: progress_callback(f"🚀 准备扫描 {total_count} 个合约 (USDT & USDC)...", 5)
                since_time = int((datetime.now() - timedelta(days=7)).timestamp() * 1000)
                
                for i, symbol in enumerate(all_target_symbols):
                    try:
                        if i % 5 == 0 and progress_callback:
                            pct = 5 + int((i / total_count) * 90)
                            progress_callback(f"🔍 [{i}/{total_count}] 扫描: {symbol}", pct)
                        
                        # 1. 抓交易
                        trades = exchange.fetch_my_trades(symbol=symbol, since=since_time, limit=100)
                        if trades: 
                            all_trades.extend(trades)
                        
                        # 2. 抓资金费 (快速模式下也抓取，但加一点延时)
                        funding = fetch_funding_income(symbol, since_time)
                        if funding: 
                            all_trades.extend(funding)
                            
                        time.sleep(0.05) 
                    except Exception as e:
                        continue

            # --- 模式 B: 深度同步 ---
            elif mode == 'deep':
                if not target_coins_str: 
                    return "⚠️ 请输入币种", 0
                
                user_inputs = [s.strip().upper() for s in target_coins_str.split(',') if s.strip()]
                target_symbols = []
                
                for u_coin in user_inputs:
                    # 智能查找：如果输入 BTC，自动加入 BTC/USDT 和 BTC/USDC
                    if u_coin in coin_map: 
                        target_symbols.extend(coin_map[u_coin])
                    else: 
                        target_symbols.append(f"{u_coin}/USDT")
                        target_symbols.append(f"{u_coin}/USDC")
                
                target_symbols = sorted(list(set(target_symbols)))
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
                            # 1. 抓交易
                            trades = exchange.fetch_my_trades(symbol=symbol, since=current_start, limit=1000, params={'endTime': current_end})
                            if trades: all_trades.extend(trades)
                            
                            # 2. 抓资金费
                            funding = fetch_funding_income(symbol, current_start, current_end)
                            if funding: all_trades.extend(funding)
                            
                            current_end = current_start
                            if current_end <= stop_ts: break
                            time.sleep(0.3)
                        except Exception as e:
                            current_end = current_start 
                            time.sleep(0.5)

            if not all_trades: 
                return f"✅ 扫描完成。未发现新数据。", 0
                
            if progress_callback: progress_callback(f"💾 正在保存 (含 BNB 换算 & 资金费)...", 95)
            
            # --- 关键：传入 exchange 以便查询 BNB 汇率 ---
            new_count = self._save_to_db(all_trades, key_tag, exchange=exchange)
            
            if progress_callback: progress_callback("✅ 完成！", 100)
            return f"✅ 同步成功！新增 {new_count} 条记录", new_count
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return f"❌ 同步过程出错: {str(e)}", 0
    
    # ===========================
    #  📡 实时数据获取
    # ===========================
    def get_open_positions(self, api_key, secret):
        """
        获取当前交易所的持仓信息 (支持 USDT 和 USDC 本位权益合计)
        """
        exchange = self.get_exchange(api_key, secret)
        if not exchange:
            return None, "❌ 无法连接交易所"
            
        try:
            # 获取余额 (USDT 和 USDC)
            try:
                balance_info = exchange.fetch_balance()
                usdt_equity = float(balance_info['USDT']['total']) if 'USDT' in balance_info else 0.0
                usdc_equity = float(balance_info['USDC']['total']) if 'USDC' in balance_info else 0.0
                total_equity = usdt_equity + usdc_equity
            except:
                total_equity = 0.0
            
            # 获取持仓
            positions = exchange.fetch_positions()
            active_positions = []
            
            for p in positions:
                contracts = float(p.get('contracts') or 0)
                
                if contracts > 0:
                    entry_price = float(p.get('entryPrice') or 0)
                    current_price = float(p.get('markPrice') or 0)
                    amount = contracts
                    side = str(p.get('side')).upper()
                    unrealized_pnl = float(p.get('unrealizedPnl') or 0)
                    
                    raw_leverage = p.get('leverage')
                    leverage = float(raw_leverage) if raw_leverage else 1.0
                    
                    # 成本 = (均价 * 数量) / 杠杆
                    position_cost = (entry_price * amount) / leverage if leverage > 0 else 0
                    
                    if position_cost > 0:
                        roi = (unrealized_pnl / position_cost) * 100
                    else:
                        roi = 0.0
                    
                    active_positions.append({
                        'symbol': p['symbol'],
                        'side': side,
                        'amount': amount,
                        'entry_price': entry_price,
                        'mark_price': current_price,
                        'leverage': leverage,
                        'pnl': unrealized_pnl,
                        'roi': roi,
                        'liquidation_price': float(p.get('liquidationPrice') or 0)
                    })
            
            return {
                'equity': total_equity,
                'positions': active_positions
            }, "OK"
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return None, f"获取持仓失败: {str(e)}"

    def _save_to_db(self, trades, key_tag, exchange=None):
        """
        保存交易数据 (v8.3: 本地优先查 BNB K线换算费用)
        """
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        count = 0
        
        # 预编译本地查询SQL (依赖 market_data 表)
        check_local_sql = '''
            SELECT close FROM market_data 
            WHERE symbol = 'BNB/USDT' 
            AND timestamp <= ? 
            AND timestamp > ?
            ORDER BY timestamp DESC LIMIT 1
        '''
        
        for t in trades:
            try:
                # 处理 PnL (如果是资金费，这里直接取 info 里的金额)
                pnl = float(t.get('info', {}).get('realizedPnl', 0))
                
                # === 🛠️ 核心修复：BNB 费率动态换算 ===
                fee_cost = 0.0
                fee_currency = 'USDT'
                
                # 资金费没有 Fee，只有 PnL
                if t['side'] != 'FUNDING' and t.get('fee'):
                    fee_data = t.get('fee', {})
                    raw_cost = float(fee_data.get('cost', 0))
                    raw_currency = fee_data.get('currency', 'USDT')
                    
                    # 如果是 BNB 且有 exchange 对象，进行换算
                    if raw_currency == 'BNB' and exchange and raw_cost > 0:
                        trade_ts = t['timestamp']
                        bnb_price = None
                        
                        # 1️⃣ 优先查本地 (极速)
                        try:
                            # 查前 2 分钟内的数据
                            c.execute(check_local_sql, (trade_ts, trade_ts - 120000))
                            row = c.fetchone()
                            if row: bnb_price = row[0]
                        except: pass
                        
                        # 2️⃣ 本地没有则查 API (兜底)
                        if bnb_price is None:
                            try:
                                candles = exchange.fetch_ohlcv('BNB/USDT', '1m', since=trade_ts, limit=1)
                                if candles: bnb_price = candles[0][4]
                            except: pass
                        
                        # 3️⃣ 换算
                        if bnb_price:
                            fee_cost = raw_cost * bnb_price
                            fee_currency = 'USDT' # 换算成功
                        else:
                            fee_cost = raw_cost
                            fee_currency = 'BNB' # 换算失败，保留原样
                    else:
                        fee_cost = raw_cost
                        fee_currency = raw_currency
                
                c.execute('''
                    INSERT OR IGNORE INTO trades 
                    (id, timestamp, datetime, symbol, side, price, amount, cost, fee, fee_currency, pnl, api_key_tag)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (str(t['id']), t['timestamp'], t['datetime'], t['symbol'], t['side'], float(t['price'] or 0), float(t['amount'] or 0), float(t['cost'] or 0), fee_cost, fee_currency, pnl, key_tag))
                if c.rowcount > 0: count += 1
            except Exception as e:
                # print(f"❌ 写入失败: {e}")
                continue
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
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            if api_key:
                key_tag = api_key.strip()[-4:]
                if strategy_text is not None:
                    try:
                        c.execute("UPDATE trades SET notes = ?, strategy = ? WHERE id = ? AND api_key_tag = ?", 
                                (note_text, strategy_text, trade_id, key_tag))
                    except sqlite3.OperationalError:
                        c.execute("UPDATE trades SET notes = ? WHERE id = ? AND api_key_tag = ?", 
                                (note_text, trade_id, key_tag))
                else:
                    c.execute("UPDATE trades SET notes = ? WHERE id = ? AND api_key_tag = ?", 
                            (note_text, trade_id, key_tag))
            else:
                # 兼容旧逻辑
                c.execute("UPDATE trades SET notes = ? WHERE id = ?", (note_text, trade_id))
            conn.commit()
            return True
        except Exception as e:
            return False
        finally:
            conn.close()

    def add_manual_trade(self, api_key, symbol, direction, pnl, date_str, strategy="", note=""):
        """手动录入交易"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            key_tag = api_key.strip()[-4:] if api_key else "MANU"
            
            try:
                dt_obj = datetime.strptime(date_str, '%Y-%m-%d %H:%M')
                timestamp_ms = int(dt_obj.timestamp() * 1000)
                datetime_iso = dt_obj.strftime('%Y-%m-%d %H:%M:%S')
            except:
                timestamp_ms = int(datetime.now().timestamp() * 1000)
                datetime_iso = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            import uuid
            base_id = f"MANUAL_{timestamp_ms}_{str(uuid.uuid4())[:8]}"
            side = "buy" if direction.lower() == "long" else "sell"
            
            # 1. 开仓记录
            open_id = f"{base_id}_OPEN"
            c.execute('''
                INSERT INTO trades 
                (id, timestamp, datetime, symbol, side, price, amount, cost, fee, fee_currency, pnl, api_key_tag, strategy, notes, screenshot)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (open_id, timestamp_ms, datetime_iso, symbol, side, 0.0, 1.0, 0.0, 0.0, 'USDT', 0.0, key_tag, strategy, note, None))
            
            # 2. 平仓记录
            close_id = f"{base_id}_CLOSE"
            close_timestamp_ms = timestamp_ms + 60000 
            close_datetime_iso = datetime.fromtimestamp(close_timestamp_ms / 1000).strftime('%Y-%m-%d %H:%M:%S')
            close_side = "sell" if side == "buy" else "buy"
            
            c.execute('''
                INSERT INTO trades 
                (id, timestamp, datetime, symbol, side, price, amount, cost, fee, fee_currency, pnl, api_key_tag, strategy, notes, screenshot)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (close_id, close_timestamp_ms, close_datetime_iso, symbol, close_side, 0.0, 1.0, 0.0, 0.0, 'USDT', float(pnl), key_tag, "", "", None))
            
            conn.commit()
            return True, "✅ 交易已成功录入！"
        except Exception as e:
            return False, f"❌ 录入失败: {str(e)}"
        finally:
            conn.close()
    
    def delete_screenshot(self, trade_id, api_key):
        key_tag = api_key.strip()[-4:]
        base_id = trade_id.replace('_OPEN', '').replace('_CLOSE', '')
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            c.execute("SELECT screenshot FROM trades WHERE id LIKE ? AND api_key_tag = ?", (f"{base_id}%_OPEN", key_tag))
            row = c.fetchone()
            if not row:
                c.execute("SELECT screenshot FROM trades WHERE id = ? AND api_key_tag = ?", (base_id, key_tag))
                row = c.fetchone()
            
            if row and row[0]:
                filename = row[0]
                c.execute("UPDATE trades SET screenshot = '' WHERE id LIKE ? AND api_key_tag = ?", (f"{base_id}%_OPEN", key_tag))
                c.execute("UPDATE trades SET screenshot = '' WHERE id = ? AND api_key_tag = ?", (base_id, key_tag))
                conn.commit()
                try:
                    upload_dir = os.path.join(os.path.dirname(self.db_path), 'uploads')
                    file_path = os.path.join(upload_dir, filename)
                    if os.path.exists(file_path): os.remove(file_path)
                except: pass
                return True, "🗑️ 截图已删除"
            return False, "未找到截图记录"
        except Exception as e:
            return False, str(e)
        finally:
            conn.close()
    
    def save_screenshot(self, uploaded_file, trade_id):
        try:
            upload_dir = os.path.join(os.path.dirname(self.db_path), 'uploads')
            os.makedirs(upload_dir, exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            file_extension = uploaded_file.name.split('.')[-1] if '.' in uploaded_file.name else 'png'
            filename = f"trade_{trade_id}_{timestamp}.{file_extension}"
            file_path = os.path.join(upload_dir, filename)
            with open(file_path, 'wb') as f:
                f.write(uploaded_file.getbuffer())
            return filename
        except Exception as e:
            print(f"Save Screenshot Error: {e}")
            return None
    
    def update_trade_extended(self, trade_id, api_key, update_data):
        """v3.0 核心更新接口"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            key_tag = api_key.strip()[-4:] if api_key else ""
            is_manual = str(trade_id).startswith('MANUAL_')
            
            allowed_fields = [
                'symbol', 'side', 'timestamp', 'datetime', 'pnl', 
                'strategy', 'notes', 'screenshot', 'ai_analysis',
                'mental_state', 'rr_ratio', 'setup_rating', 'process_tag', 'mistake_tags',
                'mae', 'mfe', 'etd', 'mad', 'efficiency', 'mae_atr', 'mfe_atr',
                'rvol', 'pattern_signal'
            ]
            fields_to_update = {k: v for k, v in update_data.items() if k in allowed_fields}
            
            if not fields_to_update: return False, "⚠️ 没有有效的数据需要更新"
            
            if is_manual:
                target_open_id = trade_id
                if not trade_id.endswith('_OPEN') and not trade_id.endswith('_CLOSE'):
                    target_open_id = f"{trade_id}_OPEN"
                elif trade_id.endswith('_CLOSE'):
                    target_open_id = trade_id.replace('_CLOSE', '_OPEN')
                
                set_clause = ", ".join([f"{col} = ?" for col in fields_to_update.keys()])
                values = list(fields_to_update.values()) + [target_open_id, key_tag]
                c.execute(f"UPDATE trades SET {set_clause} WHERE id = ? AND api_key_tag = ?", values)
                
                if 'pnl' in fields_to_update:
                    target_close_id = target_open_id.replace('_OPEN', '_CLOSE')
                    c.execute("UPDATE trades SET pnl = ? WHERE id = ? AND api_key_tag = ?", 
                             (fields_to_update['pnl'], target_close_id, key_tag))
            else:
                safe_update = {k: v for k, v in fields_to_update.items() 
                              if k not in ['symbol', 'side', 'pnl', 'amount', 'fee', 'cost']}
                if not safe_update: return True, "✅ 基础数据受保护未修改"
                
                set_clause = ", ".join([f"{col} = ?" for col in safe_update.keys()])
                values = list(safe_update.values()) + [trade_id, key_tag]
                c.execute(f"UPDATE trades SET {set_clause} WHERE id = ? AND api_key_tag = ?", values)
            
            conn.commit()
            return True, "✅ 复盘数据已保存！"
        except Exception as e:
            return False, f"❌ 更新失败: {str(e)}"
        finally:
            conn.close()

    def delete_trade(self, trade_id, api_key):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            key_tag = api_key.strip()[-4:] if api_key else ""
            c.execute("DELETE FROM trades WHERE id LIKE ? AND api_key_tag = ?", (f"{trade_id}%", key_tag))
            conn.commit()
            return True, "✅ 交易已删除！"
        except Exception as e:
            return False, str(e)
        finally:
            conn.close()

    # ===========================
    #  🧠 AI 报告管理 (v9.0 增强版)
    # ===========================
    
    def save_ai_report(self, title, report_type, start_date, end_date, trade_count, total_pnl, win_rate, ai_feedback, api_key):
        """保存 AI 生成的阶段性报告"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            key_tag = api_key.strip()[-4:] if api_key else "MANU"
            created_at = int(datetime.now().timestamp() * 1000)
            
            c.execute('''
                INSERT INTO ai_reports 
                (title, report_type, start_date, end_date, trade_count, total_pnl, win_rate, ai_feedback, created_at, api_key_tag)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (title, report_type, start_date, end_date, trade_count, total_pnl, win_rate, ai_feedback, created_at, key_tag))
            
            conn.commit()
            return True, "✅ 报告已归档"
        except Exception as e:
            import traceback
            traceback.print_exc()
            return False, f"保存失败: {str(e)}"
        finally:
            conn.close()
    
    def get_ai_reports(self, api_key, limit=20):
        """获取历史分析报告"""
        conn = sqlite3.connect(self.db_path)
        key_tag = api_key.strip()[-4:] if api_key else "MANU"
        try:
            df = pd.read_sql_query(
                "SELECT * FROM ai_reports WHERE api_key_tag = ? ORDER BY created_at DESC LIMIT ?", 
                conn, params=(key_tag, limit)
            )
        except:
            df = pd.DataFrame()
        conn.close()
        return df

    def delete_ai_report(self, report_id, api_key):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        key_tag = api_key.strip()[-4:] if api_key else "MANU"
        try:
            c.execute("DELETE FROM ai_reports WHERE id = ? AND api_key_tag = ?", (report_id, key_tag))
            conn.commit()
            return True, "🗑️ 报告已删除"
        except Exception as e:
            return False, f"删除失败: {str(e)}"
        finally:
            conn.close()
            
    # ===========================
    #  ⚙️ 系统配置管理
    # ===========================
    def get_setting(self, key, default_value=""):
        conn = sqlite3.connect(self.db_path)
        try:
            c = conn.cursor()
            c.execute("SELECT value FROM system_settings WHERE key = ?", (key,))
            result = c.fetchone()
            return result[0] if result else default_value
        except: return default_value
        finally: conn.close()
    
    def set_setting(self, key, value):
        conn = sqlite3.connect(self.db_path)
        try:
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", (key, str(value)))
            conn.commit()
            return True
        except: return False
        finally: conn.close()
    
    # ===========================
    #  📚 策略库管理
    # ===========================
    def get_all_strategies(self):
        conn = sqlite3.connect(self.db_path)
        try:
            df = pd.read_sql_query("SELECT * FROM strategies", conn)
            if not df.empty: return dict(zip(df['name'], df['description']))
            return {}
        except: return {}
        finally: conn.close()
    
    def save_strategy(self, name, description):
        conn = sqlite3.connect(self.db_path)
        try:
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO strategies (name, description) VALUES (?, ?)", (name, description))
            conn.commit()
            return True, "✅ 策略已保存"
        except Exception as e: return False, str(e)
        finally: conn.close()
    
    def delete_strategy(self, name):
        conn = sqlite3.connect(self.db_path)
        try:
            c = conn.cursor()
            c.execute("DELETE FROM strategies WHERE name = ?", (name,))
            conn.commit()
            return True, "🗑️ 策略已删除"
        except Exception as e: return False, str(e)
        finally: conn.close()