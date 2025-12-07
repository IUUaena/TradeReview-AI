# -*- coding: utf-8 -*-

import sqlite3
import os
import sys

# 设置输出编码
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 锁定数据库路径
basedir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(basedir, 'trade_review.db')

# 如果数据库不存在，先创建一个基础数据库（至少要有 trades 表）
if not os.path.exists(db_path):
    print(f"⚠️ 数据库不存在，正在创建: {db_path}")
    # 先连接创建数据库文件，然后创建基础表结构
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    # 创建基础 trades 表（只包含必要的字段，升级脚本会添加其他字段）
    c.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id TEXT PRIMARY KEY,
            timestamp INTEGER,
            datetime TEXT,
            symbol TEXT,
            side TEXT,
            amount REAL,
            price REAL,
            cost REAL,
            fee REAL,
            pnl REAL,
            api_key_tag TEXT
        )
    ''')
    conn.commit()
    conn.close()
    print(f"✅ 数据库创建成功")

print(f"📂 正在升级数据库 v4.0 (价格行为字段): {db_path}")

def add_column(cursor, table_name, column_name, column_type):
    try:
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [row[1] for row in cursor.fetchall()]
        if column_name in columns:
            print(f"   [跳过] {column_name} 已存在")
            return
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
        print(f"✅ [新增] {column_name} 添加成功")
    except Exception as e:
        print(f"❌ [错误] 添加 {column_name} 失败: {e}")

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # === v4.0 新增字段 ===
    # MAE: 最大浮亏 (例如 -5.2，代表持仓期间最差亏了5.2%)
    add_column(cursor, 'trades', 'mae', 'REAL')
    
    # MFE: 最大浮盈 (例如 +12.5，代表持仓期间最好赚了12.5%)
    add_column(cursor, 'trades', 'mfe', 'REAL')
    
    # ETD: 利润回撤 (例如 20.0，代表从最高点回撤了20%才走)
    add_column(cursor, 'trades', 'etd', 'REAL')
    
    conn.commit()
    conn.close()
    print("\n🎉 数据库 v4.0 升级完成！现在可以记录 MAE/MFE 价格行为数据了。")
except Exception as e:
    print(f"❌ 升级失败: {e}")

