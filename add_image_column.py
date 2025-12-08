# -*- coding: utf-8 -*-
import sqlite3
import os
import sys

# 设置输出编码为UTF-8（Windows兼容）
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 数据库文件路径（根据 data_engine.py 中的配置）
basedir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(basedir, 'trade_review.db')

if not os.path.exists(db_path):
    print(f"[ERROR] 未找到数据库文件: {db_path}")
    print("[TIP] 提示：请先运行一次主程序，让它创建数据库和表结构。")
    exit()

print(f"[OK] 找到数据库: {db_path}")
print(f"[INFO] 正在为数据库添加截图字段...")

def column_exists(cursor, table_name, column_name):
    """检查列是否已存在"""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 表名是 'trades'（根据 data_engine.py）
    table_name = 'trades'
    
    # 检查表是否存在
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    if not cursor.fetchone():
        print(f"[ERROR] 表 '{table_name}' 不存在！")
        print("[TIP] 提示：请先运行一次主程序，让它创建数据库和表结构。")
        conn.close()
        exit()
    
    # 检查列是否已存在
    if column_exists(cursor, table_name, 'screenshot'):
        print("[INFO] screenshot 列已存在，无需重复添加。")
    else:
        # 添加 screenshot 列，类型为 TEXT（只存文件名，不存图片二进制数据）
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN screenshot TEXT")
        conn.commit()
        print("[OK] 成功添加 screenshot 列！")
    
    conn.close()
    print("\n--- 数据库升级完成！---")
    print("[OK] 现在可以安全地使用截图上传功能了。")
    
except Exception as e:
    print(f"[ERROR] 发生错误: {e}")
    import traceback
    traceback.print_exc()

