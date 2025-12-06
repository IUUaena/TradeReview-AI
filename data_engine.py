import ccxt
import pandas as pd
import sqlite3
import time
from datetime import datetime

class TradeDataEngine:
    def __init__(self, db_path='trade_review.db'):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """初始化数据库：确保表结构包含 API Key 字段，用于隔离账户"""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        # 创建交易表，注意我们加了 api_key_tag 字段来区分不同账户的数据
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

    def get_exchange_instance(self, api_key, secret, exchange_id='binance'):
        """初始化交易所实例（强制 U本位合约）"""
        try:
            exchange_class = getattr(ccxt, exchange_id)
            exchange = exchange_class({
                'apiKey': api_key,
                'secret': secret,
                'timeout': 30000,
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'future'  # 核心：强制指定为合约(Future)交易
                }
            })
            return exchange
        except Exception as e:
            return None

    def fetch_and_save_all_history(self, api_key, secret):
        """
        核心功能：分页抓取所有历史记录
        """
        exchange = self.get_exchange_instance(api_key, secret)
        if not exchange:
            return "❌ 交易所连接失败，请检查 API Key"
        
        # 生成一个 API Key 的标签（取后4位），用于在数据库里标记数据归属
        # 这样既能区分账户，又不会明文存储完整的 Key
        key_tag = api_key[-4:] 
        all_trades = []
        
        # 起始时间：2020年1月1日 (你可以根据需要调整更早)
        since = exchange.parse8601('2020-01-01T00:00:00Z') 
        
        print("🔄 开始全量抓取，这可能需要一点时间...")
        
        while True:
            try:
                # 每次抓取 1000 条（币安上限）
                trades = exchange.fetch_my_trades(symbol=None, since=since, limit=1000)
                
                if len(trades) == 0:
                    break
                    
                all_trades.extend(trades)
                
                # 更新时间游标：取最后一条交易的时间 + 1毫秒，作为下一次抓取的起点
                since = trades[-1]['timestamp'] + 1
                
                # 简单的防死循环：如果抓到了当前时间，就停止
                if since > exchange.milliseconds():
                    break
                    
                print(f"✅ 已获取 {len(all_trades)} 条记录，正在继续...")
                
            except Exception as e:
                print(f"⚠️ 抓取中断: {e}")
                break
        
        # 保存到数据库
        count = self._save_to_db(all_trades, key_tag)
        return f"🎉 成功同步 {count} 条历史交易数据！"

    def _save_to_db(self, trades_data, key_tag):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        new_count = 0
        
        for t in trades_data:
            # 提取我们需要的数据
            trade_id = t['id']
            ts = t['timestamp']
            dt = t['datetime']
            symbol = t['symbol']
            side = t['side'] # buy/sell
            price = t['price']
            amount = t['amount']
            cost = t['cost']
            
            # 处理手续费
            fee_cost = 0
            fee_currency = 'USDT'
            if t.get('fee'):
                fee_cost = t['fee'].get('cost', 0)
                fee_currency = t['fee'].get('currency', 'USDT')
            
            # 尝试获取 PnL (盈亏)，币安合约通常在 info 里的 realizedPnl 字段
            pnl = 0.0
            if 'info' in t and 'realizedPnl' in t['info']:
                pnl = float(t['info']['realizedPnl'])
            
            try:
                # 插入数据，如果 ID 重复则忽略 (INSERT OR IGNORE)
                c.execute('''
                    INSERT OR IGNORE INTO trades 
                    (id, timestamp, datetime, symbol, side, price, amount, cost, fee, fee_currency, pnl, api_key_tag)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (trade_id, ts, dt, symbol, side, price, amount, cost, fee_cost, fee_currency, pnl, key_tag))
                
                if c.rowcount > 0:
                    new_count += 1
            except Exception as e:
                pass
        
        conn.commit()
        conn.close()
        return new_count

    def load_trades(self, api_key):
        """读取数据：只读取当前 API Key 对应的数据"""
        if not api_key: return pd.DataFrame()
        key_tag = api_key[-4:]
        
        conn = sqlite3.connect(self.db_path)
        # 按照时间倒序排列，最新的在前面
        df = pd.read_sql_query("SELECT * FROM trades WHERE api_key_tag = ? ORDER BY timestamp DESC", conn, params=(key_tag,))
        conn.close()
        return df

    def delete_account_data(self, api_key):
        """❌ 毁灭模式：根据 API Key 删除所有相关数据"""
        if not api_key: return False
        key_tag = api_key[-4:]
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute("DELETE FROM trades WHERE api_key_tag = ?", (key_tag,))
        deleted_rows = c.rowcount
        conn.commit()
        conn.close()
        return deleted_rows

