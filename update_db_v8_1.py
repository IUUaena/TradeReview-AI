import sqlite3
import os

# 锁定数据库路径
base_dir = os.path.dirname(os.path.abspath(__file__))
data_dir = os.path.join(base_dir, 'data')

if os.path.exists(data_dir) and os.path.isdir(data_dir):
    db_path = os.path.join(data_dir, 'trade_review.db')
else:
    db_path = os.path.join(base_dir, 'trade_review.db')

print(f"📂 正在升级数据库 v8.1 (Patterns): {db_path}")

conn = sqlite3.connect(db_path)
c = conn.cursor()

try:
    c.execute("ALTER TABLE trades ADD COLUMN pattern_signal TEXT")
    print("✅ [新增] pattern_signal (形态信号)")
except Exception as e:
    print(f"   [跳过] pattern_signal: {e}")

conn.commit()
conn.close()

print("\n🎉 数据库 v8.1 升级完成！")

