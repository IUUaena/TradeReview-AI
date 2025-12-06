import streamlit as st
import pandas as pd
import plotly.express as px
from data_engine import TradeDataEngine

# -----------------------------------------------------------------------------
# 1. 页面配置：必须放在第一行
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="TradeReview AI",
    page_icon="📈",
    layout="wide",  # 使用宽屏模式，看数据更舒服
    initial_sidebar_state="expanded"
)

# -----------------------------------------------------------------------------
# 2. 辅助函数：计算核心指标
# -----------------------------------------------------------------------------
def calculate_metrics(df):
    if df.empty:
        return 0, 0, 0, 0
    
    total_pnl = df['pnl'].sum()
    total_trades = len(df)
    
    # 胜率计算 (PnL > 0 视为胜)
    winning_trades = len(df[df['pnl'] > 0])
    win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
    
    # 最大单笔盈利
    max_profit = df['pnl'].max()
    
    return total_pnl, win_rate, total_trades, max_profit

# -----------------------------------------------------------------------------
# 3. 初始化引擎
# -----------------------------------------------------------------------------
engine = TradeDataEngine()

# -----------------------------------------------------------------------------
# 4. 侧边栏：控制中心
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("🔐 账户控制台")
    
    # API 输入区 (密码模式，不显示明文)
    api_key = st.text_input("Binance API Key", type="password")
    api_secret = st.text_input("Binance Secret Key", type="password")
    
    st.markdown("---")
    
    # 按钮 A: 同步数据
    if st.button("🔄 同步历史数据 (全量)"):
        if not api_key or not api_secret:
            st.error("请输入 API Key 和 Secret")
        else:
            with st.spinner("正在从交易所挖掘所有历史记录，请稍候..."):
                msg = engine.fetch_and_save_all_history(api_key, api_secret)
                if "成功" in msg:
                    st.success(msg)
                    st.rerun() # 刷新页面显示新数据
                else:
                    st.error(msg)
    
    st.markdown("---")
    
    # 按钮 B: 危险区域 - 隐私清除
    st.subheader("⚠️ 危险区域")
    if st.button("🗑️ 删除该账户所有数据", type="primary"):
        if not api_key:
            st.warning("请输入要删除数据的 API Key 以确认身份")
        else:
            deleted = engine.delete_account_data(api_key)
            st.success(f"安全清除：已物理删除 {deleted} 条与该 Key 关联的记录。")
            st.rerun()

# -----------------------------------------------------------------------------
# 5. 主界面：可视化仪表盘
# -----------------------------------------------------------------------------
st.title("📈 交易复盘 AI 驾驶舱")

# 尝试加载数据
if api_key:
    df = engine.load_trades(api_key)
else:
    df = pd.DataFrame()

if df.empty:
    # 空状态显示
    st.info("👋 欢迎！请在左侧输入 API Key 并点击"同步"以开始复盘之旅。")
    st.markdown("""
    **功能指引：**
    1. 输入 Binance 合约 API Key (只读权限即可)。
    2. 点击 **同步历史数据**，系统将抓取您账户所有的历史记录。
    3. 数据存储在本地数据库，点击 **删除账户数据** 可彻底销毁。
    """)
else:
    # --- A. 核心指标卡片 (Metrics) ---
    t_pnl, win_rate, t_count, max_p = calculate_metrics(df)
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("💰 总盈亏 (USDT)", f"{t_pnl:,.2f}", delta=f"{t_pnl:,.2f}")
    with col2:
        st.metric("🎯 胜率", f"{win_rate:.1f}%")
    with col3:
        st.metric("📊 总交易笔数", f"{t_count}")
    with col4:
        st.metric("🚀 单笔最大盈利", f"{max_p:,.2f}")
    
    st.markdown("---")
    
    # --- B. 资金曲线图 (Visuals) ---
    st.subheader("📉 资金/盈亏走势")
    
    # 数据预处理：按时间正序排列以便画图
    df_chart = df.sort_values('timestamp')
    # 计算累计盈亏 (Cumulative PnL)
    df_chart['cumulative_pnl'] = df_chart['pnl'].cumsum()
    # 转换时间格式方便阅读
    df_chart['date_str'] = pd.to_datetime(df_chart['timestamp'], unit='ms')
    
    # 使用 Plotly 画交互式图表
    fig = px.line(
        df_chart, 
        x='date_str', 
        y='cumulative_pnl', 
        title='累计盈亏曲线 (Cumulative PnL)',
        markers=True
    )
    # 优化图表样式：深色背景，隐藏网格
    fig.update_layout(
        xaxis_title="时间",
        yaxis_title="累计盈亏 (USDT)",
        hovermode="x unified"
    )
    # 如果盈亏是正的，线显示绿色，负的显示红色 (简单处理)
    line_color = '#00FF00' if t_pnl >= 0 else '#FF0000'
    fig.update_traces(line_color=line_color)
    
    st.plotly_chart(fig, use_container_width=True)
    
    # --- C. 详细交易列表 (Data Table) ---
    st.subheader("📝 详细交易记录")
    
    # 简单筛选器
    filter_col1, filter_col2 = st.columns(2)
    with filter_col1:
        symbol_filter = st.multiselect("筛选币种", options=df['symbol'].unique())
    with filter_col2:
        side_filter = st.multiselect("筛选方向 (Long/Short)", options=df['side'].unique())
        
    # 应用筛选
    df_display = df.copy()
    if symbol_filter:
        df_display = df_display[df_display['symbol'].isin(symbol_filter)]
    if side_filter:
        df_display = df_display[df_display['side'].isin(side_filter)]
    
    # 展示表格：只展示关键列，看着清爽
    st.dataframe(
        df_display[['datetime', 'symbol', 'side', 'price', 'amount', 'pnl', 'fee']],
        use_container_width=True,
        height=400,
        column_config={
            "datetime": "时间",
            "symbol": "币种",
            "side": "方向",
            "price": "价格",
            "amount": "数量",
            "pnl": st.column_config.NumberColumn("盈亏 (PnL)", format="$%.2f"),
            "fee": "手续费"
        }
    )
