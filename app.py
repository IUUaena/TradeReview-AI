import streamlit as st
import pandas as pd
import plotly.express as px
from data_engine import TradeDataEngine

# 1. 页面配置
st.set_page_config(page_title="TradeReview AI", page_icon="📈", layout="wide")
engine = TradeDataEngine()

# 2. 侧边栏：操作区 (完全还原你的逻辑)
with st.sidebar:
    st.header("🔐 账户设置")
    api_key = st.text_input("Binance API Key", type="password")
    api_secret = st.text_input("Binance Secret Key", type="password")
    
    st.markdown("---")
    st.subheader("🔄 交易同步")
    
    # === 还原：你熟悉的单选框逻辑 ===
    mode = st.radio(
        "选择同步模式", 
        ["🚀 快速扫描 (最近7天)", "⛏️ 深度挖掘 (过去1年)"],
        captions=["扫描所有币种，仅限最近。能立刻找回刚才的记录。", 
                  "突破时间限制！太耗时，必须指定币种。"]
    )
    
    target_coins = ""
    if "深度" in mode:
        st.info("💡 只有指定具体的币种，才能进行深度历史查询。")
        target_coins = st.text_input("请输入交易过的币种 (逗号分隔)", value="BTC, ETH, SOL")
    
    # 进度条占位符
    p_bar = st.progress(0)
    status_text = st.empty()
    
    def update_progress_ui(msg, val):
        status_text.text(msg)
        p_bar.progress(val)

    if st.button("开始同步"):
        if not api_key or not api_secret:
            st.error("请先输入 API Key 和 Secret")
        else:
            # 转换模式参数
            api_mode = 'recent' if "快速" in mode else 'deep'
            
            # 调用引擎
            msg, count = engine.fetch_and_save(
                api_key, api_secret, 
                mode=api_mode, 
                target_coins_str=target_coins,
                progress_callback=update_progress_ui
            )
            
            # 结果反馈
            p_bar.empty()
            status_text.empty()
            if "失败" in msg or "错误" in msg:
                st.error(msg)
            else:
                st.balloons()
                st.success(f"🎉 同步成功！新增 {count} 条记录。")
                st.rerun()

    st.markdown("---")
    if st.button("🗑️ 删除该账户数据", type="primary"):
        if api_key:
            n = engine.delete_account_data(api_key)
            st.warning(f"已删除 {n} 条数据")
            st.rerun()

# 3. 主界面：可视化展示
st.title("📈 交易复盘 AI 驾驶舱")

if api_key:
    df = engine.load_trades(api_key)
else:
    df = pd.DataFrame()

if df.empty:
    # --- 修复点：这里的 "开始同步" 改成了单引号 ---
    st.info("👋 欢迎！请在左侧填入 Key，选择模式并点击 '开始同步'。")
else:
    # 核心指标
    pnl = df['pnl'].sum()
    win_trades = len(df[df['pnl']>0])
    win_rate = (win_trades / len(df) * 100) if len(df) > 0 else 0
    
    c1, c2, c3 = st.columns(3)
    c1.metric("💰 总盈亏", f"{pnl:,.2f}", delta=f"{pnl:,.2f}")
    c2.metric("🎯 胜率", f"{win_rate:.1f}%")
    c3.metric("📊 交易数", len(df))
    
    st.markdown("---")
    
    # 图表
    st.subheader("📉 资金曲线")
    df_chart = df.sort_values('timestamp')
    df_chart['cumulative_pnl'] = df_chart['pnl'].cumsum()
    df_chart['date'] = pd.to_datetime(df_chart['timestamp'], unit='ms')
    
    fig = px.line(df_chart, x='date', y='cumulative_pnl')
    fig.update_traces(line_color='#00FF00' if pnl>=0 else '#FF0000')
    st.plotly_chart(fig, use_container_width=True)
    
    # 列表
    st.subheader("📝 详细记录")
    # 筛选功能
    sel_coin = st.multiselect("筛选币种", df['symbol'].unique())
    df_show = df[df['symbol'].isin(sel_coin)] if sel_coin else df
    
    st.dataframe(
        df_show[['datetime', 'symbol', 'side', 'price', 'amount', 'pnl', 'fee']],
        use_container_width=True, 
        height=500,
        column_config={"pnl": st.column_config.NumberColumn("盈亏", format="$%.2f")}
    )