import sqlite3
import os
from market_engine import MarketDataEngine

def smart_sync():
    print("🦅 开始执行智能同步 (Smart Sync)...")
    
    # 1. 初始化市场数据引擎
    market = MarketDataEngine()
    
    # 2. 连接交易记录数据库
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 优先查找 data 目录下的数据库
    data_dir = os.path.join(base_dir, 'data')
    trade_db_path = os.path.join(data_dir, 'trade_review.db')
    
    if not os.path.exists(trade_db_path):
        # 回退查找
        trade_db_path = os.path.join(base_dir, 'trade_review.db')
    
    if not os.path.exists(trade_db_path):
        print(f"❌ 找不到交易记录数据库: {trade_db_path}")
        print("   请先运行 app.py 并同步你的交易历史。")
        return
    print(f"📂 读取交易记录: {trade_db_path}")
    conn = sqlite3.connect(trade_db_path)
    c = conn.cursor()
    
    # 3. 找出所有交易过的币种
    try:
        c.execute("SELECT DISTINCT symbol FROM trades")
        rows = c.fetchall()
    except Exception as e:
        print(f"❌ 读取交易表失败: {e}")
        return
    finally:
        conn.close()
    
    # 4. 清洗币种名称 (标准化)
    my_coins = set()
    for r in rows:
        raw_symbol = r[0] # 例如 "BTCUSDT" 或 "ETH/USDT:USDT"
        
        # 清洗逻辑：移除无关后缀，确保格式为 Base/Quote
        clean = raw_symbol.split(':')[0] # 移除 :USDT 后缀
        if "USDT" in clean and "/" not in clean:
            clean = clean.replace("USDT", "/USDT")
            
        my_coins.add(clean)
        
    # 额外加上 BTC 和 ETH (作为市场锚点)
    my_coins.add("BTC/USDT")
    my_coins.add("ETH/USDT")
    
    target_list = sorted(list(my_coins))
    print(f"📋 你的专属同步列表 ({len(target_list)} 个): {target_list}")
    
    # 5. 开始循环进货
    for symbol in target_list:
        print(f"\n🔄 [正在同步] {symbol} ...")
        
        # 简单的进度回调
        def show_progress(msg, pct):
            print(f"\r   {msg} {int(pct*100)}%", end="")
            
        # 同步最近 1 年 (365天) 的 1分钟 K线
        success, msg = market.sync_symbol_history(symbol, timeframe='1m', days=365, progress_callback=show_progress)
        print("") # 换行
        
        if success:
            print(f"   ✅ {msg}")
        else:
            print(f"   ⚠️ {msg}")
            
    print("\n🎉 所有数据同步完成！现在去 app.py 点击【极速还原】吧！")

if __name__ == "__main__":
    smart_sync()

