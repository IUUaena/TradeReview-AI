import streamlit as st
import db_manager as db
import pandas as pd

# 1. 页面基础设置
st.set_page_config(
    page_title="TradeReview AI",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 2. 初始化数据库 (每次启动时检查)
db.init_db()

# 3. 侧边栏导航
st.sidebar.title("🦁 交易复盘 AI")
page = st.sidebar.radio("导航", ["📊 仪表盘", "🔄 数据同步", "⚙️ 设置 & API"])

# --- 页面 1: 仪表盘 (暂时留空) ---
if page == "📊 仪表盘":
    st.title("交易总览")
    st.info("👋 欢迎回来！请先去【设置】页面配置你的交易所 API，再去【数据同步】页面抓取数据。")
    
    # 只有当有数据时才显示（未来实现）
    st.write("waiting for data...")

# --- 页面 2: 数据同步 ---
elif page == "🔄 数据同步":
    st.title("🔄 数据同步中心")
    
    # 1. 先去数据库读取已保存的 API Key
    keys_df = db.get_all_keys()
    
    if keys_df.empty:
        st.warning("⚠️ 你还没有配置 API Key。请先去【设置 & API】页面配置。")
    else:
        st.info("点击下方按钮，将从币安拉取最近的 100 笔合约交易记录并存入本地数据库。")
        
        # 让用户选择用哪个账号同步（目前主要是 Binance）
        selected_exchange = st.selectbox("选择要同步的账户", keys_df['exchange_name'])
        
        if st.button("🚀 开始同步数据"):
            # 获取具体的 Key 和 Secret
            key_info = db.get_api_key(selected_exchange)
            if key_info:
                api_key, api_secret = key_info
                
                with st.spinner(f"正在连接 {selected_exchange} ... 请稍候"):
                    # 这里的 import 放在里面是为了避免循环引用
                    import exchange_api
                    import sqlite3
                    
                    # 调用刚才写的抓取函数
                    df, msg = exchange_api.get_binance_futures_history(api_key, api_secret)
                    
                    if df is not None:
                        st.success(f"成功获取 {len(df)} 笔交易！正在存入数据库...")
                        
                        # 存入数据库 (使用 append 模式，如果 ID 重复会被忽略或报错，我们需要处理一下)
                        # 为了简单，我们先用 pandas 的 to_sql，但要注意去重
                        # 这里我们用一个简单的循环来插入，避免 ID 冲突报错
                        conn = sqlite3.connect(db.DB_NAME)
                        cursor = conn.cursor()
                        count = 0
                        for index, row in df.iterrows():
                            try:
                                cursor.execute('''
                                    INSERT OR IGNORE INTO trades 
                                    (id, exchange, symbol, side, price, qty, realized_pnl, timestamp, date_str, notes, ai_analysis)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                ''', (
                                    row['id'], row['exchange'], row['symbol'], row['side'], 
                                    row['price'], row['qty'], row['realized_pnl'], 
                                    row['timestamp'], row['date_str'], '', ''
                                ))
                                if cursor.rowcount > 0:
                                    count += 1
                            except Exception as e:
                                pass # 忽略错误
                        
                        conn.commit()
                        conn.close()
                        
                        st.balloons() # 撒花庆祝
                        st.success(f"同步完成！新增了 {count} 笔新交易。请去【仪表盘】查看。")
                        
                        # 展示一下刚刚抓到的数据预览
                        st.dataframe(df)
                        
                    else:
                        st.error(msg)

# --- 页面 3: 设置 & API ---
elif page == "⚙️ 设置 & API":
    st.title("🔑 API 密钥管理")
    st.markdown("""
    请在这里输入你的 **Binance (币安)** API Key。
    
    * 数据存储在本地数据库中，**不会上传到 GitHub**，请放心。
    * 删除 Key 意味着你需要重新输入才能同步数据。
    
    """)
    # 输入表单
    with st.form("api_form"):
        col1, col2 = st.columns(2)
        with col1:
            exchange_select = st.selectbox("选择交易所", ["Binance (U本位合约)"])
        with col2:
            st.write("") # 占位
        
        input_key = st.text_input("API Key (公钥)", type="password")
        input_secret = st.text_input("Secret Key (私钥)", type="password")
        
        submitted = st.form_submit_button("💾 保存配置")
        
        if submitted:
            if input_key and input_secret:
                db.save_api_key(exchange_select, input_key, input_secret)
                st.success(f"✅ {exchange_select} 的 API Key 已保存！")
            else:
                st.error("❌ 请填写完整的 Key 和 Secret。")
    st.divider()
    
    # 显示已保存的交易所状态
    st.subheader("已连接的交易所")
    keys_df = db.get_all_keys()
    if not keys_df.empty:
        # 为了安全，只显示 Key 的前几位
        keys_df['api_key'] = keys_df['api_key'].apply(lambda x: x[:6] + "******" if x else "")
        st.dataframe(keys_df, hide_index=True)
    else:
        st.caption("暂无已连接的交易所")
