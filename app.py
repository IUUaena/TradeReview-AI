import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import time
from datetime import datetime
from data_engine import TradeDataEngine

# -----------------------------------------------------------------------------
# 1. 页面配置：宽屏 + 深色模式兼容
# -----------------------------------------------------------------------------
st.set_page_config(page_title="TradeReview Pro", page_icon="🦅", layout="wide")

# 自定义 CSS 让界面更紧凑、更像专业仪表盘
st.markdown("""
<style>
    .stMetric {
        background-color: #1E1E1E;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #333;
    }
    .stMetric:hover {
        border: 1px solid #555;
    }
    div[data-testid="stExpander"] {
        border: none;
        box-shadow: none;
        background-color: #161616;
    }
</style>
""", unsafe_allow_html=True)

engine = TradeDataEngine()

# -----------------------------------------------------------------------------
# 2. 核心计算逻辑：引入专业交易员指标
# -----------------------------------------------------------------------------
def calculate_advanced_stats(df):
    if df.empty: return {}
    
    # 基础数据
    df['pnl'] = pd.to_numeric(df['pnl'])
    total_trades = len(df)
    total_pnl = df['pnl'].sum()
    
    # 胜负统计
    wins = df[df['pnl'] > 0]
    losses = df[df['pnl'] <= 0]
    win_count = len(wins)
    loss_count = len(losses)
    
    win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0
    
    # 金额统计
    gross_profit = wins['pnl'].sum()
    gross_loss = abs(losses['pnl'].sum())
    
    # 盈亏比 (Profit Factor) = 总盈利 / 总亏损
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 999.0
    
    # 平均单笔
    avg_win = wins['pnl'].mean() if win_count > 0 else 0
    avg_loss = losses['pnl'].mean() if loss_count > 0 else 0
    # 盈亏风险比 (Reward/Risk Ratio)
    risk_reward_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    return {
        "Total PnL": total_pnl,
        "Win Rate": win_rate,
        "Trades": total_trades,
        "Profit Factor": profit_factor,
        "Avg Win": avg_win,
        "Avg Loss": avg_loss,
        "R:R Ratio": risk_reward_ratio
    }

def process_chart_data(df):
    """预处理图表数据"""
    df = df.sort_values('timestamp')
    df['date'] = pd.to_datetime(df['timestamp'], unit='ms')
    df['cumulative_pnl'] = df['pnl'].cumsum()
    # 转换日期为 "YYYY-MM-DD" 格式用于热力图聚合
    df['day_str'] = df['date'].dt.strftime('%Y-%m-%d')
    return df

# -----------------------------------------------------------------------------
# 3. 侧边栏：极简风格
# -----------------------------------------------------------------------------
with st.sidebar:
    st.title("🦅 TradeReview Pro")
    st.markdown("---")
    
    # 账户选择器
    accounts_df = engine.get_all_accounts()
    selected_key, selected_secret, selected_alias = None, None, None

    if not accounts_df.empty:
        alias_map = dict(zip(accounts_df['alias'], accounts_df['api_key']))
        selected_alias = st.selectbox("当前账户", accounts_df['alias'])
        if selected_alias:
            selected_key = alias_map[selected_alias]
            selected_secret = engine.get_credentials(selected_key)
    else:
        st.warning("请先添加账户")

    # 折叠式菜单保持界面整洁
    with st.expander("⚙️ 账户管理 / 同步"):
        tab1, tab2 = st.tabs(["同步数据", "新增/删除"])
        
        with tab1:
            if selected_key:
                mode = st.radio("模式", ["🚀 快速 (7天)", "⛏️ 深度 (1年)"])
                coins = ""
                if "深度" in mode:
                    coins = st.text_input("币种 (BTC, ETH)")
                
                # 进度条
                p_bar = st.progress(0)
                status = st.empty()
                def ui_callback(msg, val):
                    status.text(msg)
                    p_bar.progress(val)

                if st.button("开始同步", use_container_width=True):
                    api_mode = 'recent' if "快速" in mode else 'deep'
                    with st.spinner("Connecting..."):
                        msg, _ = engine.fetch_and_save(selected_key, selected_secret, api_mode, coins, ui_callback)
                        if "成功" in msg: 
                            st.success("同步完成")
                            time.sleep(1)
                            st.rerun()
                        else: st.error(msg)
            else:
                st.info("请先选择账户")

        with tab2:
            n_alias = st.text_input("新账户名")
            n_key = st.text_input("API Key", type="password")
            n_sec = st.text_input("Secret", type="password")
            if st.button("保存", use_container_width=True):
                ok, m = engine.save_api_key(n_key, n_sec, n_alias)
                if ok: st.rerun()
                else: st.error(m)
            
            st.markdown("---")
            if st.button("删除当前账户", type="primary", use_container_width=True):
                if selected_key:
                    engine.delete_account_full(selected_key)
                    st.rerun()

# -----------------------------------------------------------------------------
# 4. 主界面：仪表盘布局
# -----------------------------------------------------------------------------

if selected_key:
    # 加载数据
    raw_df = engine.load_trades(selected_key)
    
    if raw_df.empty:
        st.info("📊 暂无数据，请在侧边栏进行同步。")
    else:
        stats = calculate_advanced_stats(raw_df)
        df = process_chart_data(raw_df)

        # --- 第一排：关键 KPI 卡片 ---
        col1, col2, col3, col4, col5 = st.columns(5)
        
        # 使用 Delta 箭头展示正负
        col1.metric("💰 总盈亏", f"${stats['Total PnL']:,.2f}", delta=f"{stats['Total PnL']:,.2f}")
        col2.metric("🎯 胜率", f"{stats['Win Rate']:.1f}%")
        
        # 盈亏比颜色逻辑
        pf = stats['Profit Factor']
        pf_delta = "优秀" if pf > 1.5 else "需努力"
        col3.metric("⚖️ 盈亏比 (PF)", f"{pf:.2f}", delta=pf_delta, delta_color="normal" if pf > 1.2 else "inverse")
        
        col4.metric("📈 平均盈利", f"${stats['Avg Win']:.2f}")
        col5.metric("📉 平均亏损", f"${stats['Avg Loss']:.2f}")

        st.markdown("---")

        # --- 第二排：图表视窗 (使用 Tabs 分离视图) ---
        chart_tab1, chart_tab2, chart_tab3 = st.tabs(["📈 资金曲线 (Equity)", "📅 日历热力图 (Heatmap)", "📊 盈亏分布"])

        with chart_tab1:
            # 资金曲线：使用面积图，更美观
            fig_equity = px.area(
                df, x='date', y='cumulative_pnl', 
                title=f"{selected_alias} 资金增长曲线",
                color_discrete_sequence=['#00FF00' if stats['Total PnL'] > 0 else '#FF0000']
            )
            fig_equity.update_layout(
                xaxis_title="", yaxis_title="累计盈亏 (USDT)",
                plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
                hovermode="x unified"
            )
            st.plotly_chart(fig_equity, use_container_width=True)

        with chart_tab2:
            # 日历热力图：计算每日盈亏
            daily_pnl = df.groupby('day_str')['pnl'].sum().reset_index()
            
            # 使用柱状图模拟热力分布 (Streamlit 原生暂无好的 Calendar 组件，用 Bar 代替最直观)
            # 绿色代表当日盈利，红色代表当日亏损
            colors = ['#FF4B4B' if val < 0 else '#00C853' for val in daily_pnl['pnl']]
            
            fig_heat = go.Figure(data=[go.Bar(
                x=daily_pnl['day_str'],
                y=daily_pnl['pnl'],
                marker_color=colors
            )])
            fig_heat.update_layout(
                title="每日盈亏表现 (Daily PnL)",
                xaxis_title="日期", yaxis_title="当日盈亏",
                plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)'
            )
            st.plotly_chart(fig_heat, use_container_width=True)

        with chart_tab3:
            # 盈亏分布直方图
            fig_dist = px.histogram(
                df, x="pnl", nbins=50, 
                title="盈亏分布 (PnL Distribution)",
                color_discrete_sequence=['#29B5E8']
            )
            fig_dist.update_layout(plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)')
            # 标记 0轴
            fig_dist.add_vline(x=0, line_width=2, line_dash="dash", line_color="white")
            st.plotly_chart(fig_dist, use_container_width=True)

        # --- 第三排：详细数据列表 (美化表格) ---
        st.subheader("📝 交易流水")
        
        # 格式化表格
        st.dataframe(
            df[['date', 'symbol', 'side', 'price', 'amount', 'pnl', 'fee']],
            use_container_width=True,
            height=400,
            column_config={
                "date": "时间",
                "symbol": "币种",
                "side": st.column_config.TextColumn("方向", help="Long/Short"),
                "pnl": st.column_config.NumberColumn(
                    "盈亏 (PnL)", 
                    format="$%.2f",
                    # 加上进度条视觉效果，一眼看出大肉和大面
                    help="盈亏金额" 
                ),
            }
        )

else:
    # 极简引导页
    st.markdown("""
    <div style='text-align: center; margin-top: 100px;'>
        <h1>🦅 TradeReview Pro</h1>
        <p style='color: gray;'>专业的 AI 交易复盘工作台</p>
        <br>
        <p>👈 请在左侧侧边栏添加 API Key 开始旅程</p>
    </div>
    """, unsafe_allow_html=True)