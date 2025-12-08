import ccxt
import sqlite3
import pandas as pd
import time
import os
from datetime import datetime, timedelta

class MarketDataEngine:
    """
    v7.0 核心组件：本地市场数据仓库
    负责：
    1. 批量下载并维护全量 K 线数据 (Local Data Warehouse)
    2. 提供毫秒级的 K 线查询服务 (不再依赖实时 API)
    3. 自动处理交易所权重限制 (Rate Limits)
    """
    def __init__(self, db_path=None):
        # --- 核心修改：自动定位到 data 目录，确保数据持久化 ---
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
        # 优先检查是否存在 data 目录 (Docker 挂载目录)
        data_dir = os.path.join(base_dir, 'data')
        if os.path.exists(data_dir) and os.path.isdir(data_dir):
            self.db_path = os.path.join(data_dir, 'market_data.db')
        else:
            # 如果没有 data 目录，回退到默认路径
            if db_path is None:
                db_path = 'market_data.db'
            self.db_path = os.path.join(base_dir, db_path)
            
        print(f"📉 市场数据仓库位置: {self.db_path}")
        
        # 初始化公开交易所实例 (用于下载 K 线，无需 API Key)
        self.public_exchange = ccxt.binance({
            'enableRateLimit': True,
            'options': {'defaultType': 'future'}  # 默认抓取合约 K 线
        })
        self._init_db()

    def _init_db(self):
        """初始化 K 线专用数据库"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # 创建 K 线表 (复合主键防止重复)
        # 包含: 币种, 周期, 时间戳, 开, 高, 低, 收, 量
        c.execute('''
            CREATE TABLE IF NOT EXISTS klines (
                symbol TEXT,
                timeframe TEXT,
                timestamp INTEGER,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                PRIMARY KEY (symbol, timeframe, timestamp)
            )
        ''')
        # 创建索引加速查询
        c.execute('CREATE INDEX IF NOT EXISTS idx_symbol_ts ON klines (symbol, timestamp)')
        
        conn.commit()
        conn.close()

    def sync_symbol_history(self, symbol, timeframe='1m', days=365, progress_callback=None):
        """
        核心功能：同步单个币种的历史 K 线
        :param symbol: 币种 (如 'BTC/USDT')
        :param timeframe: 周期 (默认 '1m' 最精细)
        :param days: 回溯天数 (默认 1 年)
        :param progress_callback: 回调函数，用于前端显示进度条 (msg, percent)
        """
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        try:
            # 1. 确定抓取起点
            # 先查库里最新的时间是多久
            c.execute("SELECT MAX(timestamp) FROM klines WHERE symbol = ? AND timeframe = ?", (symbol, timeframe))
            last_ts = c.fetchone()[0]
            
            now = self.public_exchange.milliseconds()
            
            if last_ts:
                # 如果库里有数据，从最后一条接着抓 (防止断层)
                start_ts = last_ts + 1
                mode = "增量更新"
            else:
                # 库里没数据，抓过去 N 天
                start_ts = now - (days * 24 * 60 * 60 * 1000)
                mode = "全量下载"
            if progress_callback:
                progress_callback(f"🚀 [{mode}] 正在同步 {symbol}...", 0.0)
            all_ohlcv = []
            current_since = start_ts
            total_duration = now - start_ts
            if total_duration <= 0:
                return 0, "✅ 数据已是最新"
            while current_since < now:
                try:
                    # 每次抓 1000 根 (Binance 上限 1500)
                    ohlcv = self.public_exchange.fetch_ohlcv(symbol, timeframe, since=current_since, limit=1000)
                    
                    if not ohlcv:
                        break
                    
                    # 写入数据库 (批量插入)
                    data_to_insert = []
                    for k in ohlcv:
                        # (symbol, timeframe, ts, o, h, l, c, v)
                        data_to_insert.append((
                            symbol, timeframe, k[0], k[1], k[2], k[3], k[4], k[5]
                        ))
                    
                    c.executemany('''
                        INSERT OR IGNORE INTO klines 
                        (symbol, timeframe, timestamp, open, high, low, close, volume)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', data_to_insert)
                    conn.commit()
                    
                    # 更新进度
                    last_fetched_ts = ohlcv[-1][0]
                    current_since = last_fetched_ts + 1
                    
                    if progress_callback:
                        covered = last_fetched_ts - start_ts
                        pct = min(0.99, covered / total_duration)
                        progress_callback(f"📥 {symbol}: 同步至 {datetime.fromtimestamp(last_fetched_ts/1000).strftime('%Y-%m-%d')}", pct)
                    
                    # 稍微休息一下，虽然 ccxt 开启了 enableRateLimit，但大量循环还是稳一点好
                    time.sleep(0.1)
                    
                    # 如果抓到的最新数据已经接近现在，停止
                    if now - last_fetched_ts < 60000:
                        break
                        
                except Exception as e:
                    print(f"⚠️ 抓取片段失败: {e}")
                    time.sleep(1) # 出错多睡一会
            
            return True, f"✅ {symbol} 同步完成"
        except Exception as e:
            return False, f"❌ 同步失败: {str(e)}"
        finally:
            conn.close()

    def get_klines_df(self, symbol, start_ts, end_ts, timeframe='1m'):
        """
        本地极速查询：获取指定时间段的 K 线 DataFrame
        """
        conn = sqlite3.connect(self.db_path)
        
        # 加上 buffer (前后多取一点，保证画图完整)
        buffer = 60 * 1000 * 60 # 60分钟 buffer
        q_start = start_ts - buffer
        q_end = end_ts + buffer
        
        try:
            query = f"""
                SELECT timestamp, open, high, low, close, volume 
                FROM klines 
                WHERE symbol = '{symbol}' 
                AND timeframe = '{timeframe}'
                AND timestamp >= {q_start}
                AND timestamp <= {q_end}
                ORDER BY timestamp ASC
            """
            df = pd.read_sql_query(query, conn)
            
            if not df.empty:
                # 转换时间格式，方便 Pandas 处理
                df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
            
            return df
            
        except Exception as e:
            print(f"查询失败: {e}")
            return pd.DataFrame()
        finally:
            conn.close()

# 测试代码
if __name__ == "__main__":
    me = MarketDataEngine()
    print("开始测试同步 BTC/USDT...")
    
    def simple_callback(msg, pct):
        print(f"[{pct:.0%}] {msg}")
        
    # 测试同步最近 2 天的数据
    me.sync_symbol_history("BTC/USDT", days=2, progress_callback=simple_callback)
    
    # 测试读取
    now = int(time.time() * 1000)
    df = me.get_klines_df("BTC/USDT", now - 86400000, now)
    print(f"读取到 {len(df)} 条 K 线数据")
    print(df.head())

