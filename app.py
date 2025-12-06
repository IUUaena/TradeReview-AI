import streamlit as st
import pandas as pd
import plotly.express as px
import time  # <--- 之前漏了这句，导致报错
from data_engine import TradeDataEngine

# 1. 页面配置
st.set_page_config(page_title="TradeReview AI", page_icon="📈", layout="wide")
engine = TradeDataEngine()

# 2. 侧边栏：账户与同步管理
with st.sidebar:
    st.header("👤 账户管理")
    
    # --- A. 账户选择器 ---
    accounts_df = engine.get_all_accounts()
    
    selected_alias = None
    selected_key = None
    selected_secret = None
    
    if not accounts_df.empty:
        # 创建一个字典用于映射：别名 -> Key
        alias_map = dict(zip(accounts_df['alias'], accounts_df['api_key']))
        
        # 下拉菜单选择
        selected_alias = st.selectbox("当前账户", accounts_df['alias'])
        
        # 获取对应的 Key 和 Secret (用于后续操作)
        if selected_alias:
            selected_key = alias_map[selected_alias]
            selected_secret = engine.get_credentials(selected_key)
            st.success(f"已连接: {selected_alias}")
    else:
        st.info("👈 暂无账户，请先添加")

    # --- B. 添加/更新账户 (折叠菜单) ---
    with st.expander("➕ 添加 / 更新账户"):
        new_alias = st.text_input("账户备注 (例如: 币安大号)")
        new_key = st.text_input("API Key", type="password")
        new_secret = st.text_input("Secret Key", type="password")
        
        if st.button("💾 保存账户"):
            success, msg = engine.save_api_key(new_key, new_secret, new_alias)
            if success:
                st.success(msg)
                time.sleep(1) # 让提示停留1秒
                st.rerun()    # 刷新页面
            else:
                st.error(msg)

    st.markdown("---")

    # --- C. 同步操作 (仅当选中账户时显示) ---
    if selected_key and selected_secret:
        st.subheader("🔄 数据同步")
        
        mode = st.radio(
            "选择同步模式", 
            ["🚀 快速扫描 (最近7天)", "⛏️ 深度挖掘 (最近1年)"],
            captions=["扫描所有合约，适合日常更新。", "需要输入币种，倒序查找，适合补录。"]
        )
        
        target_coins = ""
        if "深度" in mode:
            st.info("💡 深度模式：必须指定币种")
            target_coins = st.text_input("输入币种 (如 BTC, ETH, SOL)")
        
        # 进度条UI
        p_bar = st.progress(0)
        status_text = st.empty()
        
        def update_ui(msg, val):
            status_text.text(msg)
            p_bar.progress(val)

        if st.button("开始同步"):
            api_mode = 'recent' if "快速" in mode else 'deep'
            with st.spinner("正在连接交易所..."):
                msg, count = engine.fetch_and_save(
                    selected_key, selected_secret, 
                    mode=api_mode, 
                    target_coins_str=target_coins, 
                    progress_callback=update_ui
                )
                
                p_bar.empty()
                status_text.empty()
                
                if "成功" in msg:
                    st.balloons()
                    st.success(f"🎉 同步完成！新增 {count} 条记录。")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error(msg)
        
        st.markdown("---")
        
        # --- D. 危险区域 (删除当前账户) ---
        with st.expander("⚠️ 危险区域"):
            st.warning(f"确定要删除【{selected_alias}】吗？")
            st.markdown("这将删除：\n1. 本地保存的 Key\n2. 该账户所有的历史交易记录")
            if st.button("🗑️ 确认删除当前账户", type="primary"):
                n = engine.delete_account_full(selected_key)
                st.success(f"已删除账户及 {n} 条关联交易记录。")
                time.sleep(1)
                st.rerun()

# 3. 主界面内容
st.title("📈 交易复盘 AI 驾驶舱")

if selected_key:
    # 加载选中账户的数据
    df = engine.load_trades(selected_key)
    
    if df.empty:
        st.info(f"👋 欢迎，**{selected_alias}**！暂无数据，请点击左侧“开始同步”。")
    else:
        # 核心指标
        pnl = df['pnl'].sum()
        win_trades = len(df[df['pnl']>0])
        win_rate = (win_trades / len(df) * 100) if len(df) > 0 else 0
        
        c1, c2, c3 = st.columns(3)
        c1.metric("💰 总盈亏 (USDT)", f"{pnl:,.2f}", delta=f"{pnl:,.2f}")
        c2.metric("🎯 胜率", f"{win_rate:.1f}%")
        c3.metric("📊 交易笔数", len(df))
        
        st.markdown("---")
        
        # 图表
        st.subheader(f"📉 {selected_alias} 资金曲线")
        df_chart = df.sort_values('timestamp')
        df_chart['cumulative_pnl'] = df_chart['pnl'].cumsum()
        df_chart['date'] = pd.to_datetime(df_chart['timestamp'], unit='ms')
        
        fig = px.line(df_chart, x='date', y='cumulative_pnl')
        fig.update_traces(line_color='#00FF00' if pnl>=0 else '#FF0000')
        st.plotly_chart(fig, use_container_width=True)
        
        # 列表
        st.subheader("📝 详细记录")
        sel_coin = st.multiselect("筛选币种", df['symbol'].unique())
        df_show = df[df['symbol'].isin(sel_coin)] if sel_coin else df
        
        st.dataframe(
            df_show[['datetime', 'symbol', 'side', 'price', 'amount', 'pnl', 'fee']],
            use_container_width=True, 
            height=500,
            column_config={"pnl": st.column_config.NumberColumn("盈亏", format="$%.2f")}
        )

else:
    # 引导页
    st.markdown("""
    ### 👋 欢迎使用 TradeReview AI
    
    请在左侧侧边栏 **添加一个账户** 以开始。
    
    **功能特点：**
    * 🔐 **多账户管理**：支持保存多个 API Key，随时切换。
    * 🏷️ **备注功能**：给账户起个好记的名字。
    * 🗑️ **数据隔离**：删除账户时，该账户的数据会一并销毁，不留痕迹。
    """)