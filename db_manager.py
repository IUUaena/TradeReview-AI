import sqlite3
import pandas as pd
from datetime import datetime

# 数据库文件名称
DB_NAME = "trading_data.db"

def init_db():
    """初始化数据库"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # 1. API 密钥表
    c.execute('''CREATE TABLE IF NOT EXISTS api_keys
                 (exchange_name TEXT PRIMARY KEY, 
                  api_key TEXT, 
                  api_secret TEXT)''')
    
    # 2. 交易记录表 - 🌟 修复：增加了 commission 字段
    # 为了避免旧表冲突，如果字段不够会报错。
    # 简单起见，我们建议用户删除旧的 .db 文件或重建容器。
    c.execute('''CREATE TABLE IF NOT EXISTS trades
                 (id TEXT PRIMARY KEY, 
                  exchange TEXT,
                  symbol TEXT, 
                  side TEXT, 
                  price REAL, 
                  qty REAL, 
                  realized_pnl REAL, 
                  commission REAL, 
                  timestamp INTEGER,
                  date_str TEXT,
                  notes TEXT, 
                  ai_analysis TEXT)''')
    
    conn.commit()
    conn.close()

def save_api_key(exchange, key, secret):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO api_keys VALUES (?, ?, ?)", (exchange, key, secret))
    conn.commit()
    conn.close()

def get_api_key(exchange):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT api_key, api_secret FROM api_keys WHERE exchange_name=?", (exchange,))
    result = c.fetchone()
    conn.close()
    return result if result else (None, None)

def get_all_keys():
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT exchange_name, api_key FROM api_keys", conn)
    conn.close()
    return df
