# -*- coding: utf-8 -*-

import sqlite3
import os
import sys

# 设置输出编码为UTF-8（Windows兼容）
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 锁定数据库路径
basedir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(basedir, 'trade_review.db')

if not os.path.exists(db_path):
    print(f"❌ [错误] 未找到数据库文件: {db_path}")
    print("   请确认你是否运行过 app.py 生成了数据库。")
    exit()

print(f"📂 正在升级数据库: {db_path}")

def add_column(cursor, table_name, column_name, column_type):
    """安全添加列的辅助函数"""
    try:
        # 检查列是否存在
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [row[1] for row in cursor.fetchall()]
        if column_name in columns:
            print(f"   [跳过] 列 '{column_name}' 已存在")
            return
        
        # 添加列
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
        print(f"✅ [新增] 成功添加列: {column_name}")
    except Exception as e:
        print(f"❌ [错误] 添加列 {column_name} 失败: {e}")

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    table_name = 'trades'
    print("--- 开始添加 v3.0 核心字段 ---")
    
    # 1. 心理状态 (Mental State)
    # 存: "FOMO", "Calm", "Revenge", "Fear", "Greed"
    add_column(cursor, table_name, 'mental_state', 'TEXT')
    
    # 2. 预期盈亏比 (Expected R:R Ratio)
    # 存: 2.5, 3.0 (入场时计划好的盈亏比)
    add_column(cursor, table_name, 'rr_ratio', 'REAL')
    
    # 3. 形态/机会评分 (Setup Rating)
    # 存: 1-10 的整数 (你觉得这个机会质量如何)
    add_column(cursor, table_name, 'setup_rating', 'INTEGER')
    
    # 4. 过程执行质量 (Process Tag)
    # 存: "Good Process" (知行合一), "Bad Process" (乱做), "Lucky" (运气单)
    add_column(cursor, table_name, 'process_tag', 'TEXT')
    
    # 5. 错误标签 (Mistake Tags)
    # 存: "#EarlyExit #NoStop #OverSize" (方便后期 AI 统计通病)
    add_column(cursor, table_name, 'mistake_tags', 'TEXT')
    
    conn.commit()
    conn.close()
    
    print("\n🎉 数据库 v3.0 结构升级完成！")
    print("现在的交易记录不仅能存【赚了多少】，还能存【是不是凭本事赚的】。")
    
except Exception as e:
    print(f"❌ 升级过程中发生严重错误: {e}")

