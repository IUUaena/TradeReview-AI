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
    st.title("🔄 全量数据同步")
    
    keys_df = db.get_all_keys()
    
    if keys_df.empty:
        st.warning("⚠️ 请先去【设置 & API】页面配置 Binance API。")
    else:
        st.info("""
        本次更新包含：

        1. **全币种扫描**：自动检测币安所有 USDT 合约（约 200+ 个）。

        2. **深度获取**：单次最大获取 1000 条记录。

        ⚠️ 注意：由于需要扫描所有币种，过程可能需要 1-3 分钟，请耐心等待，不要关闭页面。

        """)
        
        selected_exchange = st.selectbox("选择要同步的账户", keys_df['exchange_name'])
        
        if st.button("🚀 开始全量扫描"):
            key_info = db.get_api_key(selected_exchange)
            if key_info:
                api_key, api_secret = key_info
                
                # 创建一个进度条容器
                progress_bar = st.progress(0)
                status_text = st.empty() # 用来显示文字状态
                
                # 定义回调函数，传给后端用来更新前端
                def update_progress(msg, value):
                    status_text.text(msg)
                    progress_bar.progress(value)

                import exchange_api
                import sqlite3
                
                # 开始跑！
                df, msg = exchange_api.get_binance_futures_history(api_key, api_secret, progress_callback=update_progress)
                
                # 完成后清理进度条
                progress_bar.empty()
                status_text.empty()

                if df is not None:
                    st.success(f"✅ 扫描完成！共抓取到 {len(df)} 笔交易。")
                    
                    # 存入数据库
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
                        except:
                            pass
                    conn.commit()
                    conn.close()
                    
                    if count > 0:
                        st.balloons()
                        st.success(f"成功入库 {count} 条新记录！请前往【仪表盘】查看。")
                    else:
                        st.warning("虽然抓取到了数据，但数据库里似乎已经都有了（没有新增）。")
                    
                    st.write("数据预览：")
                    st.dataframe(df)
                else:
                    st.error(f"❌ {msg}")

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
