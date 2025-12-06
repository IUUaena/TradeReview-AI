import streamlit as st
import db_manager as db
import pandas as pd
import sqlite3

# 1. 基础配置
st.set_page_config(
    page_title="TradeReview AI",
    page_icon="🦁",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 隐藏右上角菜单
st.markdown("""<style>#MainMenu {visibility: hidden;} header {visibility: hidden;} footer {visibility: hidden;}</style>""", unsafe_allow_html=True)

# 初始化
db.init_db()

# 侧边栏
st.sidebar.title("🦁 交易复盘 AI")
page = st.sidebar.radio("导航", ["📊 仪表盘 & 复盘", "🔄 数据同步", "⚙️ 设置 & API"])

# =========================================================
# 页面 1: 仪表盘 & 复盘工作台 (核心功能)
# =========================================================
if page == "📊 仪表盘 & 复盘":
    # 1. 读取数据
    conn = sqlite3.connect(db.DB_NAME)
    try:
        raw_df = pd.read_sql_query("SELECT * FROM trades", conn)
    except:
        raw_df = pd.DataFrame()
    conn.close()

    if raw_df.empty:
        st.warning("暂无数据，请先前往【🔄 数据同步】页面获取数据。")
    else:
        import data_processor
        import plotly.express as px

        # 2. 数据预处理
        raw_df['timestamp'] = pd.to_numeric(raw_df['timestamp'], errors='coerce').fillna(0).astype(int)
        raw_df['realized_pnl'] = pd.to_numeric(raw_df['realized_pnl'], errors='coerce').fillna(0.0)
        if 'commission' not in raw_df.columns: raw_df['commission'] = 0.0
        
        # 3. 核心计算
        try:
            trades_df = data_processor.process_trades_to_rounds(raw_df)
        except Exception as e:
            st.error(f"数据计算错误: {e}")
            trades_df = pd.DataFrame()

        if not trades_df.empty:
            # --- Part A: 顶部 KPI ---
            total_pnl = trades_df['net_pnl'].sum()
            win_rate = (len(trades_df[trades_df['net_pnl'] > 0]) / len(trades_df) * 100)
            
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("💰 净盈亏", f"{total_pnl:,.2f} U", delta_color="normal")
            k2.metric("🎯 胜率", f"{win_rate:.1f}%")
            k3.metric("🔢 交易笔数", f"{len(trades_df)}")
            k4.metric("手续费总计", f"{trades_df['total_fee'].sum():,.2f} U")
            
            st.divider()

            # --- Part B: 左右分栏布局 ---
            col_left, col_right = st.columns([3, 2])
            
            # === 左侧：交易列表 ===
            with col_left:
                st.subheader("📝 交易列表")
                
                # 样式着色
                def highlight_pnl(val):
                    color = '#d4edda' if val > 0 else '#f8d7da' if val < 0 else ''
                    return f'background-color: {color}; color: black'

                # 展示表格
                st.dataframe(
                    trades_df[['symbol', 'direction', 'open_date', 'net_pnl', 'duration_min', 'trade_count']]
                    .style.format({'net_pnl': '{:.2f}'})
                    .applymap(highlight_pnl, subset=['net_pnl']),
                    use_container_width=True,
                    height=500
                )

            # === 右侧：复盘工作台 ===
            with col_right:
                st.subheader("🕵️‍♂️ 复盘工作台")
                st.caption("选择一笔交易，写下笔记，或让 AI 点评。")
                
                # 构造下拉选择框
                options = []
                # 将 dataframe 的 index 和 open_id 绑定
                for idx, row in trades_df.iterrows():
                    label = f"#{idx} | {row['symbol']} ({row['direction']}) | {row['open_date']} | {row['net_pnl']} U"
                    options.append(label)
                
                selected_label = st.selectbox("👉 选择要复盘的交易:", options)
                
                if selected_label:
                    # 1. 获取选中的交易数据
                    selected_index = int(selected_label.split("|")[0].replace("#", "").strip())
                    trade_data = trades_df.loc[selected_index]
                    target_id = trade_data['open_id'] # 🌟 获取到了具体的 ID！

                    # 2. 从数据库读取已存在的笔记和 AI 点评
                    conn = sqlite3.connect(db.DB_NAME)
                    c = conn.cursor()
                    c.execute("SELECT notes, ai_analysis FROM trades WHERE id=?", (target_id,))
                    row_db = c.fetchone()
                    conn.close()
                    
                    existing_note = row_db[0] if row_db and row_db[0] else ""
                    existing_ai = row_db[1] if row_db and row_db[1] else ""

                    # 3. 展示详情卡片
                    st.info(f"""
                    **标的**: {trade_data['symbol']}   |   **方向**: {trade_data['direction']}
                    \n**盈亏**: {trade_data['net_pnl']} U   |   **持仓**: {trade_data['duration_min']} 分钟
                    \n**开仓时间**: {trade_data['open_date']}
                    """)

                    # 4. 笔记输入框
                    user_note = st.text_area("✍️ 复盘笔记 (自动加载已保存内容):", value=existing_note, height=150)
                    
                    # 5. 操作按钮区
                    col_save, col_ai = st.columns(2)
                    
                    # 保存按钮
                    if col_save.button("💾 保存笔记"):
                        db.update_trade_note(target_id, user_note, existing_ai)
                        st.success("✅ 笔记已保存到数据库！")
                        # 强制刷新一下页面以显示最新状态（可选）
                        st.rerun()

                    # AI 按钮
                    if col_ai.button("🤖 呼叫 AI 毒舌导师"):
                        ai_key, base_url = db.get_ai_settings()
                        if not ai_key:
                            st.error("❌ 未配置 AI Key！请去设置页面。")
                        else:
                            with st.spinner("🦁 导师正在分析 K 线和你的操作..."):
                                import ai_assistant
                                analysis = ai_assistant.get_ai_analysis(ai_key, base_url, trade_data, user_note)
                                
                                # 自动保存 AI 结果
                                db.update_trade_note(target_id, user_note, analysis)
                                st.success("点评完成并已保存！")
                                st.rerun() # 刷新显示结果

                    # 6. 展示 AI 点评结果
                    if existing_ai:
                        st.markdown("### 🦁 导师点评：")
                        st.info(existing_ai)

# =========================================================
# 页面 2: 数据同步
# =========================================================
elif page == "🔄 数据同步":
    st.title("🔄 交易数据同步")
    
    keys_df = db.get_all_keys()
    # 过滤掉 AI Config
    exchange_keys = keys_df[keys_df['exchange_name'] != 'AI_Config']
    
    if exchange_keys.empty:
        st.warning("⚠️ 请先去【设置】页面配置交易所 API。")
    else:
        selected_exchange = st.selectbox("选择账户", exchange_keys['exchange_name'])
        st.divider()
        
        mode_label = st.radio("选择扫描模式", 
            ["🚀 极速扫描 (最近7天)", "📅 月度扫描 (最近30天)", "⛏️ 深度挖掘 (过去1年)"],
            captions=["最快。补全最近遗漏。", "推荐。适合常规复盘。", "最慢。需指定币种。"]
        )
        
        target_coins = ""
        mode_code = "fast"
        if "月度" in mode_label: mode_code = "month"
        if "深度" in mode_label: 
            mode_code = "deep"
            st.info("💡 深度模式需要逐个扫描，请输入币种。")
            target_coins = st.text_input("目标币种 (例如: BTC, ETH)", value="BTC, ETH")
        
        if st.button("🚀 开始同步"):
            key_info = db.get_api_key(selected_exchange)
            if key_info:
                api_key, api_secret = key_info
                pb = st.progress(0)
                status = st.empty()
                
                def update_progress(msg, value):
                    status.text(msg)
                    pb.progress(value)

                import exchange_api
                
                df, msg = exchange_api.get_binance_data(api_key, api_secret, 
                                                        mode=mode_code, 
                                                        target_coins_str=target_coins,
                                                        progress_callback=update_progress)
                pb.empty()
                status.empty()

                if df is not None:
                    # 入库
                    conn = sqlite3.connect(db.DB_NAME)
                    cursor = conn.cursor()
                    count = 0
                    for index, row in df.iterrows():
                        try:
                            cursor.execute('''
                                INSERT OR IGNORE INTO trades 
                                (id, exchange, symbol, side, price, qty, realized_pnl, commission, timestamp, date_str, notes, ai_analysis)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            ''', (
                                row['id'], row['exchange'], row['symbol'], row['side'], 
                                row['price'], row['qty'], row['realized_pnl'], row['commission'],
                                row['timestamp'], row['date_str'], '', ''
                            ))
                            if cursor.rowcount > 0: count += 1
                        except: pass
                    conn.commit()
                    conn.close()
                    
                    if count > 0:
                        st.balloons()
                        st.success(f"成功入库 {count} 条新记录！")
                    else:
                        st.warning("同步完成，但没有新增记录。")
                    st.dataframe(df)
                else:
                    st.error(f"❌ {msg}")

# =========================================================
# 页面 3: 设置 & API
# =========================================================
elif page == "⚙️ 设置 & API":
    st.title("⚙️ 系统设置")
    
    tab1, tab2 = st.tabs(["交易所 API", "AI 导师配置"])
    
    with tab1:
        st.subheader("Binance API")
        with st.form("binance_form"):
            exchange = st.selectbox("交易所", ["Binance (U本位合约)"])
            key = st.text_input("API Key", type="password")
            secret = st.text_input("Secret Key", type="password")
            if st.form_submit_button("💾 保存交易所配置"):
                db.save_api_key(exchange, key, secret)
                st.success("Binance 配置已保存！")
                
        st.caption("已连接账户:")
        keys = db.get_all_keys()
        real_keys = keys[keys['exchange_name'] != 'AI_Config']
        if not real_keys.empty:
            real_keys['api_key'] = real_keys['api_key'].apply(lambda x: x[:6]+"******")
            st.dataframe(real_keys, hide_index=True)

    with tab2:
        st.subheader("🤖 AI 导师配置 (支持 DeepSeek)")
        st.markdown("""
        1. 推荐使用 [DeepSeek](https://platform.deepseek.com/) (性价比高)。

        2. Base URL 默认为 `https://api.deepseek.com`。

        """)
        
        with st.form("ai_form"):
            ai_key = st.text_input("AI API Key (sk-...)", type="password")
            ai_base = st.text_input("Base URL", value="https://api.deepseek.com")
            
            if st.form_submit_button("💾 保存 AI 配置"):
                db.save_ai_settings("AI_Config", ai_key, ai_base)
                st.success("AI 导师已就位！")
