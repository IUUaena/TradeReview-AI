import streamlit as st
import db_manager as db
import pandas as pd
import sqlite3

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

# --- 页面 1: 仪表盘 ---
if page == "📊 仪表盘":
    # 1. 尝试从数据库加载原始数据
    conn = sqlite3.connect(db.DB_NAME)
    try:
        raw_df = pd.read_sql_query("SELECT * FROM trades", conn)
    except:
        raw_df = pd.DataFrame()
    conn.close()
    
    if raw_df.empty:
        st.title("📊 交易总览")
        st.warning("暂无数据。请先前往【🔄 数据同步】页面获取你的历史交易。")
        st.info("💡 提示：同步完成后，这里将自动展示你的资金曲线和交易分析。")
    
    else:
        # 2. 调用大脑进行数据处理
        import data_processor
        import plotly.express as px
        import plotly.graph_objects as go
        
        # 转换数据类型，确保计算正确
        raw_df['timestamp'] = raw_df['timestamp'].astype(int)
        raw_df['realized_pnl'] = raw_df['realized_pnl'].astype(float)
        
        # 计算完整回合
        trades_df = data_processor.process_trades_to_rounds(raw_df)
        
        # 检查处理后的数据是否为空
        if trades_df.empty:
            st.title("📊 交易总览")
            st.warning("已检测到交易数据，但尚未形成完整的交易回合（可能都是未平仓的持仓）。")
            st.info("💡 提示：请等待持仓平仓后，或确保数据中包含完整的开仓-平仓记录。")
        else:
            # --- A. 顶栏 KPI 指标 ---
            st.title("📊 交易复盘仪表盘")
            
            # 计算核心指标
            total_pnl = trades_df['net_pnl'].sum()
            total_trades = len(trades_df)
            winning_trades = trades_df[trades_df['net_pnl'] > 0]
            win_rate = (len(winning_trades) / total_trades * 100) if total_trades > 0 else 0
            
            # 渲染 KPIs
            kpi1, kpi2, kpi3, kpi4 = st.columns(4)
            kpi1.metric("💰 净盈亏 (Net PnL)", f"{total_pnl:,.2f} U", delta_color="normal")
            kpi2.metric("🎯 胜率 (Win Rate)", f"{win_rate:.1f}%")
            kpi3.metric("🔢 总交易数", f"{total_trades} 笔")
            
            # 计算最大单笔亏损 (用来警示)
            max_loss = trades_df['net_pnl'].min()
            kpi4.metric("⚠️ 最大单笔亏损", f"{max_loss:,.2f} U")
            
            st.divider()
            
            # --- B. 核心图表：资金累积曲线 (Equity Curve) ---
            st.subheader("📈 资金增长曲线")
            
            # 按时间正序排列以计算累积
            chart_df = trades_df.sort_values(by='close_time', ascending=True).copy()
            chart_df['cumulative_pnl'] = chart_df['net_pnl'].cumsum()
            
            # 使用 Plotly 画面积图
            fig = px.area(chart_df, x='open_date', y='cumulative_pnl', 
                          title="累计盈亏走势 (Cumulative PnL)",
                          labels={'cumulative_pnl': '累计盈亏 (USDT)', 'open_date': '日期'},
                          color_discrete_sequence=['#00CC96']) # 绿色
            
            # 加一条 0 轴线
            fig.add_hline(y=0, line_dash="dash", line_color="gray")
            st.plotly_chart(fig, use_container_width=True)
            
            # --- C. 详细交易列表 (Round Trips) ---
            st.subheader("📝 完整交易记录 (Round Trips)")
            st.caption("这里将原本零散的买卖记录合并为了完整的 '开仓-平仓' 回合。")
            
            # 简单的筛选器
            filter_col1, filter_col2 = st.columns([1, 3])
            with filter_col1:
                symbol_filter = st.selectbox("筛选币种", ["All"] + list(trades_df['symbol'].unique()))
            
            display_df = trades_df.copy()
            if symbol_filter != "All":
                display_df = display_df[display_df['symbol'] == symbol_filter]
            
            # 美化表格显示
            # 定义样式：盈利用绿色，亏损用红色
            def highlight_pnl(val):
                color = '#90EE90' if val > 0 else '#FFB6C1' if val < 0 else ''
                return f'background-color: {color}; color: black'
            
            # 只展示关键列
            show_cols = ['symbol', 'direction', 'open_date', 'net_pnl', 'duration_min', 'status', 'total_fee']
            
            # 使用 Streamlit 的 dataframe 展示，并应用颜色
            st.dataframe(
                display_df[show_cols].style.format({
                    'net_pnl': '{:.2f}',
                    'total_fee': '{:.2f}'
                }).applymap(highlight_pnl, subset=['net_pnl']),
                use_container_width=True,
                height=400
            )

# --- 页面 2: 数据同步 ---
elif page == "🔄 数据同步":
    st.title("🔄 交易数据同步")
    
    keys_df = db.get_all_keys()
    
    if keys_df.empty:
        st.warning("⚠️ 请先去【设置 & API】页面配置 Binance API。")
    else:
        selected_exchange = st.selectbox("选择账户", keys_df['exchange_name'])
        
        st.divider()
        
        # 模式选择
        mode = st.radio("选择同步模式", 
                        ["🚀 月度扫描 (最近30天)", "⛏️ 深度挖掘 (过去1年)"],
                        captions=["扫描所有币种，覆盖最近30天。使用分片技术突破7天限制。", 
                                  "突破时间限制！但因为太耗时，需要你指定币种。"])
        
        target_coins = ""
        if "深度" in mode:
            st.info("💡 只有指定具体的币种，才能进行按周切片的深度历史查询。")
            target_coins = st.text_input("请输入你交易过的币种 (用逗号分隔，例如: BTC, ETH, SOL, PEPE)", value="BTC, ETH")
        
        if st.button("开始同步"):
            key_info = db.get_api_key(selected_exchange)
            if key_info:
                api_key, api_secret = key_info
                
                # 准备 UI
                progress_bar = st.progress(0)
                status_text = st.empty()
                def update_progress(msg, value):
                    status_text.text(msg)
                    progress_bar.progress(value)

                import exchange_api
                import sqlite3
                
                # 判定模式参数
                api_mode = "recent" if "月度" in mode else "deep"
                
                # 调用后端
                df, msg = exchange_api.get_binance_data(api_key, api_secret, 
                                                        mode=api_mode, 
                                                        target_coins_str=target_coins,
                                                        progress_callback=update_progress)
                
                progress_bar.empty()
                status_text.empty()

                if df is not None:
                    # 入库逻辑
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
                        st.success(f"🎉 成功同步！数据库新增 {count} 条记录。")
                    else:
                        st.warning("同步成功，但这些记录数据库里好像都已经有了。")
                        
                    st.write(f"本次获取到的原始记录 ({len(df)}条):")
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
