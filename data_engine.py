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
            # 启动时打印路径以便调试 (Windows控制台可能不支持emoji，使用纯文本)
            print(f"数据库锁定位置: {db_path}")
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # 1. 交易数据表 (v3.0 增强版)
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
        
        # 3. [新增] AI 阶段性报告表
        c.execute('''
            CREATE TABLE IF NOT EXISTS ai_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_type TEXT,      -- 'WEEKLY', 'MONTHLY', 'BATCH_30'
                start_date TEXT,
                end_date TEXT,
                trade_count INTEGER,
                total_pnl REAL,
                win_rate REAL,
                ai_feedback TEXT,      -- AI 的完整分析报告
                created_at INTEGER,    -- 生成时间
                api_key_tag TEXT
            )
        ''')
        
        # 4. [v3.1 新增] 策略库表
        c.execute('''
            CREATE TABLE IF NOT EXISTS strategies (
                name TEXT PRIMARY KEY,
                description TEXT
            )
        ''')
        
        # 5. [Bug Fix] 系统配置表
        c.execute('''
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT
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

    # ===========================
    #  📡 实时数据获取 (v6.0)
    # ===========================
    def get_open_positions(self, api_key, secret):
        """
        获取当前交易所的持仓信息 (仅限 U本位合约)
        """
        exchange = self.get_exchange(api_key, secret)
        if not exchange:
            return None, "❌ 无法连接交易所"
            
        try:
            # 获取余额 (用于计算风险率)
            balance_info = exchange.fetch_balance()
            usdt_equity = balance_info['USDT']['total'] if 'USDT' in balance_info else 0.0
            
            # 获取持仓 (Binance 专属接口优化)
            # fetch_positions 通常返回所有币种，我们需要过滤出有持仓的
            positions = exchange.fetch_positions()
            active_positions = []
            
            for p in positions:
                # 过滤掉数量为 0 的空仓
                if float(p['contracts']) > 0:
                    # 统一数据格式
                    entry_price = float(p['entryPrice'] or 0)
                    current_price = float(p['markPrice'] or 0)
                    amount = float(p['contracts'])
                    side = p['side']  # 'long' or 'short'
                    leverage = p.get('leverage', 1)
                    unrealized_pnl = float(p['unrealizedPnl'] or 0)
                    
                    # 计算盈亏比率
                    roi = (unrealized_pnl / (entry_price * amount / leverage)) * 100 if entry_price else 0
                    
                    active_positions.append({
                        'symbol': p['symbol'],
                        'side': side.upper(),
                        'amount': amount,
                        'entry_price': entry_price,
                        'mark_price': current_price,
                        'leverage': leverage,
                        'pnl': unrealized_pnl,
                        'roi': roi,
                        'liquidation_price': float(p.get('liquidationPrice') or 0)
                    })
            
            return {
                'equity': usdt_equity,
                'positions': active_positions
            }, "OK"
            
        except Exception as e:
            return None, f"获取持仓失败: {str(e)}"

    def fetch_and_save(self, api_key, secret, mode, target_coins_str=None, progress_callback=None):
        try:
            exchange = self.get_exchange(api_key, secret)
            if not exchange: 
                return "❌ 交易所对象创建失败", 0
            
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
                    except Exception as e:
                        print(f"⚠️ 抓取 {symbol} 失败: {e}")  # 打印错误
                        continue

            # --- 模式 B: 深度 (最近1年倒序) ---
            elif mode == 'deep':
                if not target_coins_str: 
                    return "⚠️ 请输入币种", 0
                user_inputs = [s.strip().upper() for s in target_coins_str.split(',') if s.strip()]
                target_symbols = []
                for u_coin in user_inputs:
                    if u_coin in coin_map: target_symbols.append(coin_map[u_coin])
                    else: target_symbols.append(f"{u_coin}/USDT")
                
                if not target_symbols: 
                    return "❌ 无匹配合约", 0

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
                        except Exception as e:
                            print(f"⚠️ Deep抓取失败: {e}")
                            current_end = current_start 
                            time.sleep(1)

            if not all_trades: 
                return f"✅ 扫描完成。未发现新数据。", 0
            if progress_callback: progress_callback(f"💾 保存 {len(all_trades)} 条记录...", 95)
            new_count = self._save_to_db(all_trades, key_tag)
            if progress_callback: progress_callback("✅ 完成！", 100)
            return f"✅ 同步成功！新增 {new_count} 条记录", new_count
        except Exception as e:
            return f"❌ 同步过程出错: {str(e)}", 0
    
    # ===========================
    #  📡 实时数据获取 (v6.1 修复版)
    # ===========================
    def get_open_positions(self, api_key, secret):
        """
        获取当前交易所的持仓信息 (仅限 U本位合约)
        """
        exchange = self.get_exchange(api_key, secret)
        if not exchange:
            return None, "❌ 无法连接交易所"
            
        try:
            # 获取余额
            try:
                balance_info = exchange.fetch_balance()
                usdt_equity = float(balance_info['USDT']['total']) if 'USDT' in balance_info else 0.0
            except:
                usdt_equity = 0.0  # 容错
            
            # 获取持仓
            positions = exchange.fetch_positions()
            active_positions = []
            
            for p in positions:
                # 过滤掉数量为 0 的空仓
                # 有些交易所 contracts 可能是 None，加个安全转换
                contracts = float(p.get('contracts') or 0)
                
                if contracts > 0:
                    entry_price = float(p.get('entryPrice') or 0)
                    current_price = float(p.get('markPrice') or 0)
                    amount = contracts
                    side = str(p.get('side')).upper()
                    unrealized_pnl = float(p.get('unrealizedPnl') or 0)
                    
                    # --- 核心修复：安全获取杠杆 ---
                    # 如果 leverage 是 None 或 0，强制设为 1，防止除法报错
                    raw_leverage = p.get('leverage')
                    leverage = float(raw_leverage) if raw_leverage else 1.0
                    
                    # 计算 ROI (防止除以 0)
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
                'equity': usdt_equity,
                'positions': active_positions
            }, "OK"
            
        except Exception as e:
            import traceback
            traceback.print_exc()  # 打印详细错误堆栈到后台，方便调试
            return None, f"获取持仓失败: {str(e)}"

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
            except Exception as e:
                print(f"❌ 写入单条数据失败: {e}")  # 打印错误
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
    
    def add_manual_trade(self, api_key, symbol, direction, pnl, date_str, strategy="", note=""):
        """手动录入交易（不需要从交易所同步）"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            key_tag = api_key.strip()[-4:] if api_key else "MANU"
            
            # 将日期字符串转换为时间戳
            try:
                dt_obj = datetime.strptime(date_str, '%Y-%m-%d %H:%M')
                timestamp_ms = int(dt_obj.timestamp() * 1000)
                datetime_iso = dt_obj.strftime('%Y-%m-%d %H:%M:%S')
            except:
                timestamp_ms = int(datetime.now().timestamp() * 1000)
                datetime_iso = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # 生成唯一ID（使用时间戳+随机数）
            import uuid
            base_id = f"MANUAL_{timestamp_ms}_{str(uuid.uuid4())[:8]}"
            
            # 确定 side（根据方向）
            side = "buy" if direction.lower() == "long" else "sell"
            
            # 🌟 关键修改：创建两笔记录（开仓+平仓），确保能形成完整的 round trip
            # 这样 process_trades_to_rounds 就能正确处理手动录入的交易
            
            # 第一笔：开仓（数量设为1，盈亏设为0）
            open_id = f"{base_id}_OPEN"
            c.execute('''
                INSERT INTO trades 
                (id, timestamp, datetime, symbol, side, price, amount, cost, fee, fee_currency, pnl, api_key_tag, strategy, notes, screenshot)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                open_id,
                timestamp_ms,
                datetime_iso,
                symbol,
                side,
                0.0,
                1.0,  # 开仓数量设为1
                0.0,
                0.0,
                'USDT',
                0.0,  # 开仓时盈亏为0
                key_tag,
                strategy,
                note,
                None  # 截图在编辑时添加
            ))
            
            # 第二笔：平仓（数量设为1，盈亏为用户输入的值）
            close_id = f"{base_id}_CLOSE"
            close_timestamp_ms = timestamp_ms + 60000  # 平仓时间比开仓晚1分钟
            close_datetime_iso = datetime.fromtimestamp(close_timestamp_ms / 1000).strftime('%Y-%m-%d %H:%M:%S')
            close_side = "sell" if side == "buy" else "buy"  # 平仓方向与开仓相反
            
            c.execute('''
                INSERT INTO trades 
                (id, timestamp, datetime, symbol, side, price, amount, cost, fee, fee_currency, pnl, api_key_tag, strategy, notes, screenshot)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                close_id,
                close_timestamp_ms,
                close_datetime_iso,
                symbol,
                close_side,
                0.0,
                1.0,  # 平仓数量设为1
                0.0,
                0.0,
                'USDT',
                float(pnl),  # 平仓时的盈亏（用户输入的总盈亏）
                key_tag,
                "",  # 平仓记录不重复策略和笔记
                "",
                None  # 截图只保存在开仓记录
            ))
            
            conn.commit()
            conn.close()
            return True, "✅ 交易已成功录入！"
        except Exception as e:
            conn.close()
            return False, f"❌ 录入失败: {str(e)}"
    
    def delete_screenshot(self, trade_id, api_key):
        """删除交易截图"""
        # 提取 ID (兼容 MANUAL_xxx_OPEN 格式)
        key_tag = api_key.strip()[-4:]
        base_id = trade_id.replace('_OPEN', '').replace('_CLOSE', '')
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            # 1. 获取文件名 (用于删文件)
            # 检查手动单
            c.execute("SELECT screenshot FROM trades WHERE id LIKE ? AND api_key_tag = ?", (f"{base_id}%_OPEN", key_tag))
            row = c.fetchone()
            if not row:
                # 检查 API 单
                c.execute("SELECT screenshot FROM trades WHERE id = ? AND api_key_tag = ?", (base_id, key_tag))
                row = c.fetchone()
            
            if row and row[0]:
                filename = row[0]
                # 2. 清空数据库字段
                # 更新手动单 (OPEN)
                c.execute("UPDATE trades SET screenshot = '' WHERE id LIKE ? AND api_key_tag = ?", (f"{base_id}%_OPEN", key_tag))
                # 更新 API 单
                c.execute("UPDATE trades SET screenshot = '' WHERE id = ? AND api_key_tag = ?", (base_id, key_tag))
                
                conn.commit()
                
                # 3. 删除物理文件 (可选，为了节省空间建议删除)
                try:
                    upload_dir = os.path.join(os.path.dirname(self.db_path), 'uploads')
                    file_path = os.path.join(upload_dir, filename)
                    if os.path.exists(file_path):
                        os.remove(file_path)
                except:
                    pass # 文件删不掉也不影响业务
                
                return True, "🗑️ 截图已删除"
            else:
                return False, "未找到截图记录"
        except Exception as e:
            return False, str(e)
        finally:
            conn.close()
    
    def save_screenshot(self, uploaded_file, trade_id):
        """保存上传的截图文件"""
        try:
            # 创建上传文件夹
            upload_dir = os.path.join(os.path.dirname(self.db_path), 'uploads')
            os.makedirs(upload_dir, exist_ok=True)
            
            # 生成安全的文件名
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
            file_extension = uploaded_file.name.split('.')[-1] if '.' in uploaded_file.name else 'png'
            filename = f"trade_{trade_id}_{timestamp}.{file_extension}"
            
            # 保存文件
            file_path = os.path.join(upload_dir, filename)
            with open(file_path, 'wb') as f:
                f.write(uploaded_file.getbuffer())
            
            return filename
        except Exception as e:
            print(f"Save Screenshot Error: {e}")
            return None
    
    def update_trade(self, trade_id, api_key, symbol, direction, pnl, date_str, strategy="", note="", screenshot_filename=None):
        """
        更新交易（支持手动录入和 API 导入的交易）
        
        关键修复：
        - 手动录入：ID 格式为 MANUAL_xxx，需要更新开仓(_OPEN)和平仓(_CLOSE)两笔记录
        - API 导入：round_id 就是原始的开仓记录 id，只更新策略、笔记和截图（不修改交易所的真实交易数据）
        """
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            key_tag = api_key.strip()[-4:] if api_key else ""
            
            # 判断是手动录入还是 API 导入
            is_manual = trade_id.startswith('MANUAL_')
            
            if is_manual:
                # ========== 手动录入的交易 ==========
                # 查找开仓和平仓两笔记录
                c.execute("SELECT id FROM trades WHERE id LIKE ? AND api_key_tag = ?", (f"{trade_id}%", key_tag))
                trade_ids = [row[0] for row in c.fetchall()]
                
                if not trade_ids:
                    conn.close()
                    return False, "❌ 未找到要更新的交易记录"
                
                # 将日期字符串转换为时间戳
                try:
                    dt_obj = datetime.strptime(date_str, '%Y-%m-%d %H:%M')
                    timestamp_ms = int(dt_obj.timestamp() * 1000)
                    datetime_iso = dt_obj.strftime('%Y-%m-%d %H:%M:%S')
                except:
                    # 如果日期格式错误，保持原时间戳
                    c.execute("SELECT timestamp, datetime FROM trades WHERE id = ? AND api_key_tag = ?", 
                             (trade_ids[0], key_tag))
                    result = c.fetchone()
                    if result:
                        timestamp_ms = result[0]
                        datetime_iso = result[1]
                    else:
                        timestamp_ms = int(datetime.now().timestamp() * 1000)
                        datetime_iso = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                # 确定 side
                side = "buy" if direction.lower() == "long" else "sell"
                close_side = "sell" if side == "buy" else "buy"
                
                # 更新开仓记录
                open_id = [tid for tid in trade_ids if tid.endswith('_OPEN')]
                if open_id:
                    if screenshot_filename:
                        c.execute('''
                            UPDATE trades 
                            SET symbol = ?, side = ?, timestamp = ?, datetime = ?, strategy = ?, notes = ?, screenshot = ?
                            WHERE id = ? AND api_key_tag = ?
                        ''', (symbol, side, timestamp_ms, datetime_iso, strategy, note, screenshot_filename, open_id[0], key_tag))
                    else:
                        c.execute('''
                            UPDATE trades 
                            SET symbol = ?, side = ?, timestamp = ?, datetime = ?, strategy = ?, notes = ?
                            WHERE id = ? AND api_key_tag = ?
                        ''', (symbol, side, timestamp_ms, datetime_iso, strategy, note, open_id[0], key_tag))
                
                # 更新平仓记录（更新盈亏和时间）
                close_id = [tid for tid in trade_ids if tid.endswith('_CLOSE')]
                if close_id:
                    close_timestamp_ms = timestamp_ms + 60000
                    close_datetime_iso = datetime.fromtimestamp(close_timestamp_ms / 1000).strftime('%Y-%m-%d %H:%M:%S')
                    c.execute('''
                        UPDATE trades 
                        SET symbol = ?, side = ?, timestamp = ?, datetime = ?, pnl = ?
                        WHERE id = ? AND api_key_tag = ?
                    ''', (symbol, close_side, close_timestamp_ms, close_datetime_iso, float(pnl), close_id[0], key_tag))
                
                conn.commit()
                conn.close()
                return True, "✅ 交易已成功更新！"
                
            else:
                # ========== API 导入的交易 ==========
                # round_id 就是原始的开仓记录 id
                # 检查记录是否存在
                c.execute("SELECT id FROM trades WHERE id = ? AND api_key_tag = ?", (trade_id, key_tag))
                trade_record = c.fetchone()
                
                if not trade_record:
                    conn.close()
                    return False, "❌ 未找到要更新的交易记录"
                
                # API 导入的交易：只更新策略、笔记和截图（不修改交易所的真实交易数据）
                # 这样可以保护交易所的真实数据，只允许添加复盘信息
                if screenshot_filename:
                    c.execute('''
                        UPDATE trades 
                        SET strategy = ?, notes = ?, screenshot = ?
                        WHERE id = ? AND api_key_tag = ?
                    ''', (strategy, note, screenshot_filename, trade_id, key_tag))
                else:
                    # 如果没有新截图，保持原有截图
                    c.execute('''
                        UPDATE trades 
                        SET strategy = ?, notes = ?
                        WHERE id = ? AND api_key_tag = ?
                    ''', (strategy, note, trade_id, key_tag))
                
                conn.commit()
                conn.close()
                return True, "✅ 交易复盘信息已成功更新！（API 导入的交易只能更新策略和笔记）"
                
        except Exception as e:
            conn.close()
            return False, f"❌ 更新失败: {str(e)}"
    
    def delete_trade(self, trade_id, api_key):
        """删除交易（删除开仓和平仓两笔记录）"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            key_tag = api_key.strip()[-4:] if api_key else ""
            
            # 查找所有相关的交易记录（开仓和平仓）
            c.execute("SELECT id FROM trades WHERE id LIKE ? AND api_key_tag = ?", (f"{trade_id}%", key_tag))
            trade_ids = [row[0] for row in c.fetchall()]
            
            if not trade_ids:
                conn.close()
                return False, "❌ 未找到要删除的交易记录"
            
            # 删除所有相关记录
            for tid in trade_ids:
                c.execute("DELETE FROM trades WHERE id = ? AND api_key_tag = ?", (tid, key_tag))
            
            conn.commit()
            conn.close()
            return True, "✅ 交易已成功删除！"
        except Exception as e:
            conn.close()
            return False, f"❌ 删除失败: {str(e)}"
    
    # ===========================
    #  🧠 AI 报告管理 (新增)
    # ===========================
    
    def save_ai_report(self, report_type, start_date, end_date, trade_count, total_pnl, win_rate, ai_feedback, api_key):
        """保存 AI 生成的阶段性报告"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            key_tag = api_key.strip()[-4:] if api_key else "MANU"
            created_at = int(datetime.now().timestamp() * 1000)
            
            c.execute('''
                INSERT INTO ai_reports 
                (report_type, start_date, end_date, trade_count, total_pnl, win_rate, ai_feedback, created_at, api_key_tag)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (report_type, start_date, end_date, trade_count, total_pnl, win_rate, ai_feedback, created_at, key_tag))
            
            conn.commit()
            return True, "✅ 报告已归档"
        except Exception as e:
            return False, f"保存失败: {str(e)}"
        finally:
            conn.close()
    
    def get_ai_reports(self, api_key, limit=10):
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
    
    # ===========================
    #  ⚙️ 系统配置管理 (Bug Fix)
    # ===========================
    def get_setting(self, key, default_value=""):
        """获取系统配置"""
        conn = sqlite3.connect(self.db_path)
        try:
            c = conn.cursor()
            c.execute("SELECT value FROM system_settings WHERE key = ?", (key,))
            result = c.fetchone()
            return result[0] if result else default_value
        except:
            return default_value
        finally:
            conn.close()
    
    def set_setting(self, key, value):
        """保存系统配置"""
        conn = sqlite3.connect(self.db_path)
        try:
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", (key, str(value)))
            conn.commit()
            return True
        except Exception as e:
            print(f"Save setting error: {e}")
            return False
        finally:
            conn.close()
    
    # ===========================
    #  📚 策略库管理 (v3.1 新增)
    # ===========================
    def get_all_strategies(self):
        """获取所有策略及其定义"""
        conn = sqlite3.connect(self.db_path)
        try:
            df = pd.read_sql_query("SELECT * FROM strategies", conn)
            # 转为字典 {name: description}
            if not df.empty:
                return dict(zip(df['name'], df['description']))
            return {}
        except:
            return {}
        finally:
            conn.close()
    
    def save_strategy(self, name, description):
        """新增或更新策略"""
        conn = sqlite3.connect(self.db_path)
        try:
            c = conn.cursor()
            c.execute("INSERT OR REPLACE INTO strategies (name, description) VALUES (?, ?)", (name, description))
            conn.commit()
            return True, "✅ 策略已保存"
        except Exception as e:
            return False, str(e)
        finally:
            conn.close()
    
    def delete_strategy(self, name):
        """删除策略"""
        conn = sqlite3.connect(self.db_path)
        try:
            c = conn.cursor()
            c.execute("DELETE FROM strategies WHERE name = ?", (name,))
            conn.commit()
            return True, "🗑️ 策略已删除"
        except Exception as e:
            return False, str(e)
        finally:
            conn.close()
    
    # ===========================
    #  🎯 v3.0 深度复盘数据更新 (新增)
    # ===========================
    
    def update_trade_extended(self, trade_id, api_key, update_data):
        """
        v3.0 核心更新接口：支持更新所有复盘字段 (字典传参)
        :param trade_id: 交易ID
        :param api_key: API Key (用于权限验证和区分账户)
        :param update_data: 字典，例如 {'mental_state': 'FOMO', 'notes': '...'}
        """
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        try:
            key_tag = api_key.strip()[-4:] if api_key else ""
            
            # 1. 确定是手动录入还是 API 导入
            is_manual = str(trade_id).startswith('MANUAL_')
            
            # 2. 定义允许更新的字段白名单 (安全防护)
            allowed_fields = [
                'symbol', 'side', 'timestamp', 'datetime', 'pnl', # 基础数据(手动单可改)
                'strategy', 'notes', 'screenshot', 'ai_analysis', # v2.0 字段
                'mental_state', 'rr_ratio', 'setup_rating', 'process_tag', 'mistake_tags', # v3.0 新字段
                # === 新增 v4.0 字段 ===
                'mae', 'mfe', 'etd',
                # === 新增 v7.0 字段 ===
                'mad', 'efficiency', 'mae_atr', 'mfe_atr',
                # === 新增 v8.0 字段 ===
                'rvol',  # 相对成交量
                # === 新增 v8.1 字段 ===
                'pattern_signal'  # 形态信号
            ]
            
            # 过滤无效字段
            fields_to_update = {k: v for k, v in update_data.items() if k in allowed_fields}
            
            if not fields_to_update:
                return False, "⚠️ 没有有效的数据需要更新"
            
            # 3. 执行更新
            if is_manual:
                # === 手动录入逻辑 (需同时处理 _OPEN 和 _CLOSE) ===
                # 我们约定：复盘数据主要存在 _OPEN 记录上 (因为是开仓时的决策)
                
                # 查找对应的开仓记录ID
                # 如果传入的是 base_id (无后缀)，加上 _OPEN
                # 如果传入的已经是完整ID，判断后缀
                target_open_id = trade_id
                if not trade_id.endswith('_OPEN') and not trade_id.endswith('_CLOSE'):
                    target_open_id = f"{trade_id}_OPEN"
                elif trade_id.endswith('_CLOSE'):
                    target_open_id = trade_id.replace('_CLOSE', '_OPEN')
                
                # 更新 _OPEN 记录 (存复盘数据)
                set_clause = ", ".join([f"{col} = ?" for col in fields_to_update.keys()])
                values = list(fields_to_update.values())
                values.extend([target_open_id, key_tag])
                
                c.execute(f"UPDATE trades SET {set_clause} WHERE id = ? AND api_key_tag = ?", values)
                
                # 如果修改了 PnL，还需要同步更新 _CLOSE 记录
                if 'pnl' in fields_to_update:
                    target_close_id = target_open_id.replace('_OPEN', '_CLOSE')
                    c.execute("UPDATE trades SET pnl = ? WHERE id = ? AND api_key_tag = ?", 
                             (fields_to_update['pnl'], target_close_id, key_tag))
                
            else:
                # === API 导入逻辑 (直接更新) ===
                # 保护机制：API单不允许修改 symbol, side, pnl 等硬数据
                safe_update = {k: v for k, v in fields_to_update.items() 
                              if k not in ['symbol', 'side', 'pnl', 'amount', 'fee', 'cost']}
                
                if not safe_update:
                    return True, "✅ 基础数据受保护未修改，无复盘数据更新。"
                
                set_clause = ", ".join([f"{col} = ?" for col in safe_update.keys()])
                values = list(safe_update.values())
                values.extend([trade_id, key_tag])
                
                sql = f"UPDATE trades SET {set_clause} WHERE id = ? AND api_key_tag = ?"
                c.execute(sql, values)
            
            conn.commit()
            return True, "✅ 深度复盘数据已保存！"
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return False, f"❌ 更新失败: {str(e)}"
        finally:
            conn.close()
    
    # ===========================
    #  📈 K线数据获取 (v4.0 MAE/MFE)
    # ===========================
    def get_candles_for_trade(self, api_key, secret, symbol, start_ts, end_ts):
        """
        全量获取 1m K线 (方案B：分页抓取)
        逻辑：循环请求，直到覆盖整个持仓时间段
        """
        exchange = self.get_exchange(api_key, secret)
        if not exchange:
            return None, "交易所连接失败"
        
        try:
            all_ohlcv = []
            # 缓冲 1 分钟，确保包住开仓那一刻
            current_since = start_ts - 60000 
            # 设定平仓时间为终点 (稍微多给一点 buffer 防止最后一根没拿全)
            target_end = end_ts + 60000
            
            limit = 1000
            
            while True:
                # 抓取
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1m', since=current_since, limit=limit)
                
                if not ohlcv:
                    break
                
                all_ohlcv.extend(ohlcv)
                
                # 获取这一批最后一条 K 线的时间
                last_time = ohlcv[-1][0]
                
                # 检查是否已经覆盖到平仓时间
                if last_time >= target_end:
                    print(f"✅ K线抓取完成，覆盖至 {pd.to_datetime(last_time, unit='ms')}")
                    break
                
                # 更新下一次抓取的起点 (最后一根时间 + 1分钟)
                current_since = last_time + 60000
                
                # === 安全机制 ===
                # 1. 防止死循环：如果 current_since 超过当前时间，强制退出
                if current_since > int(time.time() * 1000):
                    break
                
                # 2. 速率限制保护：每次休息一下
                time.sleep(0.2) 
            
            if not all_ohlcv:
                return None, "未获取到 K 线数据"
                
            # 转 DataFrame
            df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
            
            # 去重 (防止边界重叠)
            df = df.drop_duplicates(subset=['timestamp']).sort_values('timestamp')
            
            return df, "OK"
            
        except Exception as e:
            return None, f"K线获取失败: {str(e)}"