import sqlite3
import os

# 锁定数据库路径
base_dir = os.path.dirname(os.path.abspath(__file__))
data_dir = os.path.join(base_dir, 'data')

if os.path.exists(data_dir) and os.path.isdir(data_dir):
    db_path = os.path.join(data_dir, 'trade_review.db')
else:
    db_path = os.path.join(base_dir, 'trade_review.db')

print(f"📂 正在升级数据库 v9.0 (AI Report Title): {db_path}")

conn = sqlite3.connect(db_path)
c = conn.cursor()

try:
    # 给 ai_reports 表增加 title 字段
    c.execute("ALTER TABLE ai_reports ADD COLUMN title TEXT")
    print("✅ [新增] title (报告标题)")
except Exception as e:
    print(f"   [跳过] title: {e} (可能已存在)")

conn.commit()
conn.close()

print("\n🎉 数据库 v9.0 升级完成！")

