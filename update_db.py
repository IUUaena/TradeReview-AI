# -*- coding: utf-8 -*-
import sqlite3
import os
import sys

# 设置输出编码为UTF-8（Windows兼容）
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 数据库文件路径（根据 data_engine.py 中的配置）
db_path = 'trade_review.db'

if not os.path.exists(db_path):
    print(f"[ERROR] 未找到数据库文件: {db_path}")
    print("[TIP] 提示：如果你使用了不同的数据库文件名，请修改脚本中的 db_path 变量。")
    exit()

print(f"[OK] 找到数据库: {db_path}")

def column_exists(cursor, table_name, column_name):
    """检查列是否已存在"""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [row[1] for row in cursor.fetchall()]
    return column_name in columns

def add_column(cursor, table_name, column_name, column_type):
    """安全地添加列（如果不存在）"""
    if column_exists(cursor, table_name, column_name):
        print(f"[INFO] 列已存在，跳过: {column_name}")
        return False
    try:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
        print(f"[OK] 成功添加列: {column_name}")
        return True
    except sqlite3.OperationalError as e:
        print(f"[ERROR] 添加列 {column_name} 失败: {e}")
        return False

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
    
    print("--- 开始更新数据库结构 ---")
    print(f"表名: {table_name}\n")
    
    # 添加 notes (复盘笔记) 字段，类型为 TEXT
    # 注意：数据库中使用的是 'notes'，不是 'note'
    add_column(cursor, table_name, 'notes', 'TEXT')
    
    # 添加 strategy (策略名称) 字段，类型为 TEXT
    add_column(cursor, table_name, 'strategy', 'TEXT')
    
    # 提交更改
    conn.commit()
    conn.close()
    
    print("\n--- 数据库升级完成！---")
    print("[OK] 现在可以安全地使用复盘笔记和策略功能了。")
    
except Exception as e:
    print(f"[ERROR] 发生错误: {e}")
    import traceback
    traceback.print_exc()

