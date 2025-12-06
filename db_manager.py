import sqlite3
import pandas as pd
from datetime import datetime

# 数据库文件名称
DB_NAME = "trading_data.db"

def init_db():
    """初始化数据库：如果不存在表，就创建它们"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # 1. 创建 API 密钥表 (用来存你的交易所账号密码)
    # 注意：为了简单且适合本地运行，我们暂时明文存储。
    # 因为数据库文件在 .gitignore 里，不会上传到 GitHub，所以是安全的。
    c.execute('''CREATE TABLE IF NOT EXISTS api_keys
                 (exchange_name TEXT PRIMARY KEY, 
                  api_key TEXT, 
                  api_secret TEXT)''')
    
    # 2. 创建交易记录表 (用来存你的历史订单)
    # 包含：订单ID, 币种, 方向(开多/开空), 价格, 数量, 盈亏, 时间, 笔记, AI点评
    c.execute('''CREATE TABLE IF NOT EXISTS trades
                 (id TEXT PRIMARY KEY, 
                  exchange TEXT,
                  symbol TEXT, 
                  side TEXT, 
                  price REAL, 
                  qty REAL, 
                  realized_pnl REAL, 
                  timestamp INTEGER,
                  date_str TEXT,
                  notes TEXT, 
                  ai_analysis TEXT)''')
    
    conn.commit()
    conn.close()

def save_api_key(exchange, key, secret):
    """保存 API Key"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # 如果存在就更新，不存在就插入
    c.execute("INSERT OR REPLACE INTO api_keys VALUES (?, ?, ?)", (exchange, key, secret))
    conn.commit()
    conn.close()

def get_api_key(exchange):
    """读取 API Key"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT api_key, api_secret FROM api_keys WHERE exchange_name=?", (exchange,))
    result = c.fetchone()
    conn.close()
    return result if result else (None, None)

def get_all_keys():
    """查看已保存了哪些交易所"""
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT exchange_name, api_key FROM api_keys", conn)
    conn.close()
    return df

