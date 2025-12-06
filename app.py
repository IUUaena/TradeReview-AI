import streamlit as st
import pandas as pd
import time
import plotly.express as px
from data_engine import TradeDataEngine
from data_processor import process_trades_to_rounds # 引入核心逻辑

# ==============================================================================
# 1. 全局配置与样式
# ==============================================================================
st.set_page_config(page_title="TradeReview AI", page_icon="🦅", layout="wide")

COLORS = {
    "bg": "#0E1117", "card_bg": "#1E222D", 
    "up": "#0ECB81", "down": "#F6465D", 
    "text": "#EAECEF", "grid": "#2B2F36"
}

# 注入 CSS：修复顶部遮挡，美化界面
st.markdown(f"""
<style>
    .stApp {{ background-color: {COLORS['bg']}; }}
    
    /* 修复顶部遮挡问题 */
    .block-container {{ padding-top: 3rem; padding-bottom: 2rem; }}
    
    /* 列表选中态 */
    div[data-testid="stDataFrame"] {{ border: 1px solid {COLORS['grid']}; }}
    
    /* 文本框美化 */
    .stTextArea textarea {{ background-color: #161A1E; color: #EEE; border: 1px solid #333; }}
    
    /* 侧边栏背景 */
    section[data-testid="stSidebar"] {{ background-color: #161A1E; }}
    
    /* Metric 卡片美化 */
    div[data-testid="stMetric"] {{
        background-color: {COLORS['card_bg']};
        padding: 10px;
        border-radius: 5px;
        border: 1px solid {COLORS['grid']};
    }}
</style>
""", unsafe_allow_html=True)

engine = TradeDataEngine()

# ==============================================================================
# 2. 侧边栏：经典还原版 (你最喜欢的版本)
# ==============================================================================
with st.sidebar:
    st.header("🦅 复盘工作台")
    
    # --- A. 账户选择 (最清晰的下拉框) ---
    accounts_df = engine.get_all_accounts()
    selected_key = None
    
    if not accounts_df.empty:
        # 创建映射字典
        alias_map = dict(zip(accounts_df['alias'], accounts_df['api_key']))
        selected_alias = st.selectbox("当前账户", accounts_df['alias'])
        
        if selected_alias:
            selected_key = alias_map[selected_alias]
            selected_secret = engine.get_credentials(selected_key)
            st.success(f"已连接: {selected_alias}")
            
        st.divider()
        
        # --- B. 数据同步 (折叠菜单) ---
        with st.expander("🔄 数据同步"):
            mode = st.radio("模式", ["快速 (7天)", "深度 (1年)"], captions=["日常更新", "补录历史"])
            coins = ""
            if "深度" in mode:
                coins = st.text_input("币种 (如 BTC, ETH)")
            
            if st.button("开始同步", use_container_width=True):
                api_mode = 'recent' if "快速" in mode else 'deep'
                status_box = st.empty()
                p_bar = st.progress(0)
                
                def ui_callback(msg, val):
                    status_box.text(msg)
                    p_bar.progress(val)
                
                msg, count = engine.fetch_and_save(selected_key, selected_secret, api_mode, coins, ui_callback)
                if "成功" in msg:
                    st.success(f"同步完成！新增 {count} 条")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error(msg)
                    
        # --- C. 危险区域 (折叠) ---
        with st.expander("⚠️ 危险区域"):
            if st.button("🗑️ 删除当前账户", type="primary"):
                engine.delete_account_full(selected_key)
                st.rerun()
             
    else:
        st.warning("👈 请先添加账户")
        
    # --- D. 添加账户 (折叠菜单) ---
    with st.expander("➕ 添加新账户"):
        n_alias = st.text_input("备注名")
        n_key = st.text_input("API Key", type="password")
        n_sec = st.text_input("Secret", type="password")
        if st.button("保存账户", use_container_width=True):
            ok, m = engine.save_api_key(n_key, n_sec, n_alias)
            if ok: st.rerun()
            else: st.error(m)

# ==============================================================================
# 3. 主界面：复盘工作台 (左列表，右详情)
# ==============================================================================
if selected_key:
    # 1. 加载原始数据
    raw_df = engine.load_trades(selected_key)
    
    if raw_df.empty:
        st.info("👋 暂无数据，请在侧边栏点击【开始同步】。")
    else:
        # 2. 调用处理器：生成完整交易 (Round Trips)
        rounds_df = process_trades_to_rounds(raw_df)
        
        if rounds_df.empty:
            st.warning("🤔 有数据，但没有检测到完整的【开仓-平仓】闭环。请确认是否有已平仓的订单。")
        else:
            # --- 布局：左 40% 列表，右 60% 详情 ---
            col_list, col_detail = st.columns([4, 6])
            
            # === 左侧：交易列表 ===
            with col_list:
                st.subheader("📋 交易列表")
                
                # 简单筛选
                f_sym = st.multiselect("筛选币种", rounds_df['symbol'].unique())
                show_df = rounds_df[rounds_df['symbol'].isin(f_sym)] if f_sym else rounds_df
                
                # 交互式表格
                selection = st.dataframe(
                    show_df[['close_date_str', 'symbol', 'direction', 'duration_str', 'net_pnl']],
                    use_container_width=True,
                    height=750,
                    hide_index=True,
                    on_select="rerun", # 点击即刷新
                    selection_mode="single-row",
                    column_config={
                        "net_pnl": st.column_config.NumberColumn("净盈亏", format="$%.2f"),
                        "close_date_str": st.column_config.TextColumn("平仓时间"),
                        "duration_str": st.column_config.TextColumn("持仓"),
                        "symbol": st.column_config.TextColumn("币种"),
                        "direction": st.column_config.TextColumn("方向")
                    }
                )
            
            # === 右侧：深度复盘区 ===
            with col_detail:
                if selection.selection.rows:
                    idx = selection.selection.rows[0]
                    trade = show_df.iloc[idx]
                    
                    # 1. 顶部数据卡片
                    st.subheader(f"🔍 {trade['symbol']} 复盘详情")
                    
                    # 动态颜色
                    pnl_color = COLORS['up'] if trade['net_pnl'] > 0 else COLORS['down']
                    
                    # 第一行核心指标
                    c1, c2, c3 = st.columns(3)
                    c1.metric("净盈亏 (Net PnL)", f"${trade['net_pnl']}", delta="含手续费")
                    c2.metric("方向", trade['direction'])
                    c3.metric("持仓时长", trade['duration_str'])
                    
                    st.markdown("---")
                    
                    # 第二行辅助信息
                    c4, c5, c6, c7 = st.columns(4)
                    c4.markdown(f"<small style='color:#888'>开仓时间</small><br>{trade['open_date_str']}", unsafe_allow_html=True)
                    c5.markdown(f"<small style='color:#888'>平仓时间</small><br>{trade['close_date_str']}", unsafe_allow_html=True)
                    c6.markdown(f"<small style='color:#888'>手续费</small><br>${trade['total_fee']}", unsafe_allow_html=True)
                    c7.markdown(f"<small style='color:#888'>操作次数</small><br>{trade['trade_count']} 次", unsafe_allow_html=True)
                    
                    st.divider()
                    
                    # 2. 笔记模块 (核心功能)
                    st.markdown("### 📝 交易笔记 (Journal)")
                    
                    # 从数据库重新读取最新笔记 (确保实时性)
                    # trade['round_id'] 是开仓单的 ID
                    current_note_db = raw_df[raw_df['id'] == trade['round_id']].iloc[0].get('notes', '')
                    if pd.isna(current_note_db): current_note_db = ""
                    
                    user_note = st.text_area("记录你的心理状态、入场理由、离场反思...", value=current_note_db, height=200)
                    
                    if st.button("💾 保存笔记", use_container_width=True):
                        # 调用后端保存
                        engine.update_trade_note(trade['round_id'], user_note)
                        st.toast("✅ 笔记已保存！")
                        time.sleep(0.5)
                        st.rerun()

                    # 3. AI 导师区域
                    st.divider()
                    st.markdown("### 🤖 导师点评 (AI Mentor)")
                    
                    ai_res = raw_df[raw_df['id'] == trade['round_id']].iloc[0].get('ai_analysis', '')
                    
                    if ai_res:
                        st.markdown(f"""
                        <div style='background-color: {COLORS['card_bg']}; padding: 15px; border-left: 3px solid {COLORS['up']}; border-radius: 5px;'>
                            {ai_res}
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.info("👈 暂无点评。请在后续版本配置 AI Key。")
                        # 预留按钮
                        st.button("🧠 请求 AI 分析 (即将上线)", disabled=True)

                else:
                    # 空状态引导
                    st.markdown(f"""
                    <div style='height: 600px; display: flex; flex-direction: column; align-items: center; justify-content: center; border: 2px dashed #333; border-radius: 10px; color: #666;'>
                        <h3>👈 请在左侧选择一笔交易</h3>
                        <p>点击列表中的一行，开始深度复盘</p>
                    </div>
                    """, unsafe_allow_html=True)
else:
    # 登录引导页
    st.markdown("""
    <div style='text-align: center; margin-top: 100px;'>
        <h1>🦅 TradeReview AI</h1>
        <p style='color: gray;'>专业的交易复盘工作台</p>
        <br>
        <p>👈 请在左侧侧边栏添加账户以开始</p>
    </div>
    """, unsafe_allow_html=True)