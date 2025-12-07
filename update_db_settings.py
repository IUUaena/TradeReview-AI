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

print(f"📂 正在升级数据库 (系统配置表): {db_path}")

try:
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    
    # 创建 settings 表 (Key-Value 存储)
    c.execute('''
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    conn.commit()
    conn.close()
    print("🎉 配置表创建完成！现在 AI Key 不会丢了。")

except Exception as e:
    print(f"❌ 升级失败: {e}")

