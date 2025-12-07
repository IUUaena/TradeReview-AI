# -*- coding: utf-8 -*-

import sqlite3
import os
import sys

# 设置输出编码
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

basedir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(basedir, 'trade_review.db')

if not os.path.exists(db_path):
    print(f"❌ 未找到数据库: {db_path}")
    exit()

print(f"📂 正在升级数据库 (策略库): {db_path}")

try:
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # 创建 strategies 表
    # name: 策略名称 (主键)
    # description: 策略的具体定义/入场条件/出场规则
    c.execute('''
        CREATE TABLE IF NOT EXISTS strategies (
            name TEXT PRIMARY KEY,
            description TEXT
        )
    ''')
    
    # 预置一些默认策略 (如果表是空的)
    c.execute("SELECT count(*) FROM strategies")
    if c.fetchone()[0] == 0:
        defaults = [
            ("趋势突破", "1. 价格突破关键阻力位。\n2. 成交量必须放大 (至少1.5倍)。\n3. 收盘价必须站稳在阻力位之上。"),
            ("区间震荡", "1. 价格触及布林带下轨或支撑位。\n2. 出现反转K线 (锤子线/吞没)。\n3. 盈亏比至少 1:2。"),
            ("EMA回调", "1. 趋势向上 (均线多头排列)。\n2. 价格回踩 EMA20 或 EMA50。\n3. 在均线处出现止跌信号。")
        ]
        c.executemany("INSERT OR IGNORE INTO strategies VALUES (?, ?)", defaults)
        print("✅ 已预置默认策略数据。")
    
    conn.commit()
    conn.close()
    print("🎉 数据库策略库升级完成！")

except Exception as e:
    print(f"❌ 升级失败: {e}")

