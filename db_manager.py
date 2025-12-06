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

# === 新增功能 ===
def update_trade_note(trade_id, note, ai_result=None):
    """更新某笔交易的笔记和AI点评"""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    
    # 这里的 trade_id 对应的是 trades 表里的 id
    # 注意：我们这里是根据 'id' 更新。
    # 如果是合成的 Round Trip，我们通常把笔记存给开仓的那一笔订单(Open Trade)，
    # 或者你需要一种机制把笔记关联到整个回合。
    # 为了简单，我们目前假设 trade_id 就是开仓单的 ID。
    
    if ai_result:
        c.execute("UPDATE trades SET notes=?, ai_analysis=? WHERE id=?", (note, ai_result, trade_id))
    else:
        c.execute("UPDATE trades SET notes=? WHERE id=?", (note, trade_id))
        
    conn.commit()
    conn.close()

def save_ai_settings(provider, api_key, base_url):
    """专门保存 AI 的配置"""
    # 我们复用 api_keys 表，exchange_name 填 "AI_Provider"
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # 存成: exchange_name="AI", api_key=key, api_secret=base_url (复用secret字段存url)
    c.execute("INSERT OR REPLACE INTO api_keys VALUES (?, ?, ?)", ("AI_Config", api_key, base_url))
    conn.commit()
    conn.close()

def get_ai_settings():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT api_key, api_secret FROM api_keys WHERE exchange_name='AI_Config'")
    result = c.fetchone()
    conn.close()
    if result:
        return result[0], result[1] # key, base_url
    return None, None
