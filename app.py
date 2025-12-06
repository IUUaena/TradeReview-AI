import streamlit as st
import db_manager as db
import pandas as pd
import sqlite3

# 1. 页面设置
st.set_page_config(
    page_title="TradeReview AI",
    page_icon="🦁",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 🌟 隐藏右上角英文菜单的黑科技 CSS
hide_menu_style = """
        <style>
        #MainMenu {visibility: hidden;}
        header {visibility: hidden;}
        footer {visibility: hidden;}
        </style>
        """
st.markdown(hide_menu_style, unsafe_allow_html=True)

# 2. 初始化数据库
db.init_db()

# 3. 侧边栏
st.sidebar.title("🦁 交易复盘 AI")
page = st.sidebar.radio("导航", ["📊 仪表盘", "🔄 数据同步", "⚙️ 设置 & API"])

# --- 页面 1: 仪表盘 ---
if page == "📊 仪表盘":
    conn = sqlite3.connect(db.DB_NAME)
    try:
        raw_df = pd.read_sql_query("SELECT * FROM trades", conn)
    except:
        raw_df = pd.DataFrame()
    conn.close()
    
    if raw_df.empty:
        st.title("📊 交易总览")
        st.warning("暂无数据。请先前往【🔄 数据同步】页面。")
    
    else:
        import data_processor
        import plotly.express as px
        
        # 转换类型
        raw_df['timestamp'] = pd.to_numeric(raw_df['timestamp'], errors='coerce').fillna(0).astype(int)
        raw_df['realized_pnl'] = pd.to_numeric(raw_df['realized_pnl'], errors='coerce').fillna(0.0)
        # 🌟 关键修复：如果老数据库没有 commission 列，手动补上，防止报错
        if 'commission' not in raw_df.columns:
            raw_df['commission'] = 0.0
        else:
            raw_df['commission'] = pd.to_numeric(raw_df['commission'], errors='coerce').fillna(0.0)
        
        # 处理数据
        try:
            trades_df = data_processor.process_trades_to_rounds(raw_df)
        except Exception as e:
            st.error(f"数据处理出错: {e}")
            trades_df = pd.DataFrame()
        
        if not trades_df.empty:
            # KPI
            total_pnl = trades_df['net_pnl'].sum()
            win_rate = (len(trades_df[trades_df['net_pnl'] > 0]) / len(trades_df) * 100)
            
            st.title("📊 交易复盘仪表盘")
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("💰 净盈亏", f"{total_pnl:,.2f} U")
            k2.metric("🎯 胜率", f"{win_rate:.1f}%")
            k3.metric("🔢 交易笔数", f"{len(trades_df)}")
            k4.metric("手续费总计", f"{trades_df['total_fee'].sum():,.2f} U")
            
            st.divider()
            
            # 图表
            st.subheader("📈 资金曲线")
            chart_df = trades_df.sort_values(by='close_time', ascending=True).copy()
            chart_df['cumulative_pnl'] = chart_df['net_pnl'].cumsum()
            fig = px.area(chart_df, x='open_date', y='cumulative_pnl', title="累计盈亏 (USDT)")
            fig.add_hline(y=0, line_dash="dash", line_color="gray")
            st.plotly_chart(fig, use_container_width=True)
            
            # 列表
            st.subheader("📝 完整交易记录")
            
            # 颜色样式
            def highlight_pnl(val):
                color = '#d4edda' if val > 0 else '#f8d7da' if val < 0 else '' # 浅绿/浅红
                return f'background-color: {color}; color: black'
            
            st.dataframe(
                trades_df[['symbol', 'direction', 'open_date', 'net_pnl', 'duration_min', 'trade_count', 'total_fee']]
                .style.format({'net_pnl': '{:.2f}', 'total_fee': '{:.2f}'})
                .applymap(highlight_pnl, subset=['net_pnl']),
                use_container_width=True
            )
        else:
            st.info("数据已读取，但未能合成完整交易（可能是只有开仓没有平仓）。")

# --- 页面 2: 数据同步 ---
elif page == "🔄 数据同步":
    st.title("🔄 交易数据同步")
    
    keys_df = db.get_all_keys()
    if keys_df.empty:
        st.warning("⚠️ 请先配置 API。")
    else:
        selected_exchange = st.selectbox("选择账户", keys_df['exchange_name'])
        st.divider()
        
        # 🌟 三种模式选择
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
                import sqlite3
                
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
                            # 🌟 插入时带上 commission
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
                        st.warning("同步完成，但没有新增记录（可能已存在）。")
                    st.dataframe(df)
                else:
                    st.error(f"❌ {msg}")

# --- 页面 3: 设置 ---
elif page == "⚙️ 设置 & API":
    st.title("🔑 API 设置")
    with st.form("api_form"):
        exchange = st.selectbox("交易所", ["Binance (U本位合约)"])
        key = st.text_input("API Key", type="password")
        secret = st.text_input("Secret Key", type="password")
        if st.form_submit_button("保存"):
            db.save_api_key(exchange, key, secret)
            st.success("已保存！")
    
    st.subheader("已连接")
    keys = db.get_all_keys()
    if not keys.empty:
        keys['api_key'] = keys['api_key'].apply(lambda x: x[:6]+"******")
        st.dataframe(keys, hide_index=True)
