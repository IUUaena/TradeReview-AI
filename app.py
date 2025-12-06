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

# 注入 CSS：专业深色模式 (交易员风格)
st.markdown(f"""
<style>
    /* 深色模式基础 */
    .stApp {{ background-color: #121212; }}
    
    /* 修复顶部遮挡问题 */
    .block-container {{ padding-top: 3rem; padding-bottom: 2rem; }}
    
    /* 专业深色卡片 */
    .ios-stat-card {{
        background: #1E1E1E;
        border: 1px solid #333333;
        border-radius: 16px;
        padding: 24px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.5);
        margin-bottom: 16px;
        transition: transform 0.2s, box-shadow 0.2s;
    }}
    
    .ios-stat-card:hover {{
        transform: translateY(-2px);
        box-shadow: 0 6px 25px rgba(0,0,0,0.7);
        border-color: #444;
    }}
    
    .ios-label {{
        font-size: 12px;
        color: #888888;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        margin-bottom: 8px;
    }}
    
    .ios-value {{
        font-size: 32px;
        font-weight: 700;
        color: #FFFFFF;
        letter-spacing: -0.5px;
    }}
    
    /* 荧光绿/红，带微光效果 */
    .ios-value.green {{ 
        color: #4CAF50 !important; 
        text-shadow: 0 0 10px rgba(76, 175, 80, 0.2);
    }}
    .ios-value.red {{ 
        color: #FF5252 !important; 
        text-shadow: 0 0 10px rgba(255, 82, 82, 0.2);
    }}
    
    /* 列表选中态 - 深色模式 */
    div[data-testid="stDataFrame"] {{ 
        border: 1px solid #333333; 
        border-radius: 16px;
        overflow: hidden;
        background-color: #1E1E1E;
    }}
    
    /* 文本框美化 - 深色 */
    .stTextArea textarea {{ 
        background-color: #1E1E1E; 
        color: #E0E0E0; 
        border: 1px solid #333;
    }}
    
    /* 侧边栏背景 - 深色 */
    section[data-testid="stSidebar"] {{ 
        background-color: #1A1A1A;
    }}
    
    /* 主文本颜色 - 深色模式 */
    .stMarkdown, p, div {{
        color: #E0E0E0;
    }}
    
    /* 标题颜色 */
    h1, h2, h3 {{
        color: #FFFFFF;
    }}
    
    /* 分割线颜色 */
    hr, .stDivider {{
        border-color: #333333;
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
            # ======================================================================
            # iOS 风格数据看板 (Bento Grid)
            # ======================================================================
            st.markdown("### 📊 Dashboard")
            
            # --- 修复后的核心计算逻辑 ---
            total_trades = len(rounds_df)
            total_pnl = rounds_df['net_pnl'].sum()
            
            # 统计盈亏
            win_count = len(rounds_df[rounds_df['net_pnl'] > 0])
            loss_count = len(rounds_df[rounds_df['net_pnl'] < 0])
            
            # 收集所有盈亏值用于计算最佳/最差
            pnl_list = rounds_df['net_pnl'].tolist()
            
            # 计算总盈利和总亏损金额
            win_trades = rounds_df[rounds_df['net_pnl'] > 0]
            loss_trades = rounds_df[rounds_df['net_pnl'] < 0]
            total_win_amt = win_trades['net_pnl'].sum() if len(win_trades) > 0 else 0.0
            total_loss_amt = abs(loss_trades['net_pnl'].sum()) if len(loss_trades) > 0 else 0.0
            
            # 1. 胜率
            win_rate = round((win_count / total_trades * 100), 1) if total_trades > 0 else 0
            
            # 2. 盈亏比 (修复：避免除以0，全胜时显示∞)
            avg_win = total_win_amt / win_count if win_count > 0 else 0
            if loss_count > 0:
                avg_loss = total_loss_amt / loss_count
                rr_ratio = round(avg_win / avg_loss, 2)
            else:
                rr_ratio = "∞"  # 全胜时显示无穷大
            
            # 3. 最佳/最差交易 (修复：确保正确显示)
            if pnl_list:
                best_trade = max(pnl_list)
                worst_trade = min(pnl_list)
            else:
                best_trade = 0
                worst_trade = 0
            
            # 格式化总盈亏
            pnl_sign = "+" if total_pnl > 0 else ""
            total_pnl_display = f"{pnl_sign}{total_pnl:,.2f}"
            
            # iOS 风格卡片布局 (2x2 网格)
            col1, col2 = st.columns(2)
            
            with col1:
                # 总盈亏卡片 (大卡片，跨两列)
                pnl_color_class = "green" if total_pnl >= 0 else "red"
                st.markdown(f"""
                <div class="ios-stat-card">
                    <div class="ios-label">Total PnL (总盈亏)</div>
                    <div class="ios-value {pnl_color_class}">${total_pnl_display}</div>
                </div>
                """, unsafe_allow_html=True)
            
            with col2:
                col2a, col2b = st.columns(2)
                with col2a:
                    st.markdown(f"""
                    <div class="ios-stat-card">
                        <div class="ios-label">Win Rate (胜率)</div>
                        <div class="ios-value">{win_rate}%</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col2b:
                    st.markdown(f"""
                    <div class="ios-stat-card">
                        <div class="ios-label">Avg R:R (盈亏比)</div>
                        <div class="ios-value">{rr_ratio}</div>
                    </div>
                    """, unsafe_allow_html=True)
            
            # 第二行：交易总数和平均持仓时间
            col3, col4, col5 = st.columns(3)
            with col3:
                st.markdown(f"""
                <div class="ios-stat-card">
                    <div class="ios-label">Trades (总数)</div>
                    <div class="ios-value">{total_trades}</div>
                </div>
                """, unsafe_allow_html=True)
            
            with col4:
                # 计算平均持仓时间（使用 duration_min 字段，更可靠）
                closed_trades = rounds_df[rounds_df['status'] == 'Closed']
                if not closed_trades.empty and 'duration_min' in closed_trades.columns:
                    # 直接使用 duration_min 字段（已经是数字）
                    avg_duration = round(closed_trades['duration_min'].mean(), 1)
                    if avg_duration < 60:
                        avg_duration_str = f"{int(avg_duration)}分钟"
                    elif avg_duration < 1440:
                        hours = int(avg_duration // 60)
                        minutes = int(avg_duration % 60)
                        avg_duration_str = f"{hours}小时{minutes}分钟"
                    else:
                        days = int(avg_duration // 1440)
                        hours = int((avg_duration % 1440) // 60)
                        avg_duration_str = f"{days}天{hours}小时"
                else:
                    avg_duration_str = "N/A"
                
                st.markdown(f"""
                <div class="ios-stat-card">
                    <div class="ios-label">Avg Duration (平均持仓)</div>
                    <div class="ios-value" style="font-size: 20px;">{avg_duration_str}</div>
                </div>
                """, unsafe_allow_html=True)
            
            with col5:
                # 修复：正确显示最佳/最差，颜色根据正负值
                best_color = "green" if best_trade > 0 else "red"
                worst_color = "green" if worst_trade > 0 else "red"
                st.markdown(f"""
                <div class="ios-stat-card">
                    <div class="ios-label">Best / Worst</div>
                    <div class="ios-value" style="font-size: 18px;">
                        <span class="{best_color}">${best_trade:.2f}</span>
                        <span style="color: #444; margin: 0 6px;">|</span>
                        <span class="{worst_color}">${worst_trade:.2f}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            
            st.markdown("---")
            
            # ======================================================================
            # 资金曲线图 (Equity Curve) - 交易所专业级
            # ======================================================================
            # 准备完整图表数据：按时间正序排列，计算累计盈亏
            chart_df_full = rounds_df.sort_values(by='close_time', ascending=True).copy()
            chart_df_full['cumulative_pnl'] = chart_df_full['net_pnl'].cumsum()
            chart_df_full['date_str'] = pd.to_datetime(chart_df_full['close_time'], unit='ms')
            
            # 时间筛选器（交易所风格）
            chart_header_col1, chart_header_col2 = st.columns([1, 1])
            with chart_header_col1:
                st.markdown("### 📈 PnL Analysis (资金曲线)")
            with chart_header_col2:
                time_period = st.radio(
                    "时间范围",
                    ["ALL", "90D", "30D", "7D"],
                    horizontal=True,
                    label_visibility="collapsed",
                    key="time_filter"
                )
            
            # 根据选择的时间范围筛选数据
            if time_period == "ALL":
                chart_df = chart_df_full.copy()
            else:
                days = int(time_period.replace("D", ""))
                cutoff_date = pd.Timestamp.now() - pd.Timedelta(days=days)
                chart_df = chart_df_full[chart_df_full['date_str'] >= cutoff_date].copy()
            
            # 如果筛选后没有数据，显示提示
            if chart_df.empty:
                st.info(f"📅 最近 {time_period} 内暂无交易数据。")
            else:
                # 使用 Plotly 绘制专业资金曲线（平滑贝塞尔曲线）
                fig = px.area(
                    chart_df,
                    x='date_str',
                    y='cumulative_pnl',
                    title='',
                    labels={'cumulative_pnl': '累计盈亏 (USDT)', 'date_str': '时间'},
                    color_discrete_sequence=['#4CAF50'] if total_pnl >= 0 else ['#FF5252']
                )
                
                # 交易所级深色模式样式配置
                fig.update_layout(
                    plot_bgcolor='#1E1E1E',   # 图表绘图区背景（深灰）
                    paper_bgcolor='#1E1E1E',  # 整个画布背景（深灰）
                    font=dict(color='#E0E0E0', family='-apple-system, BlinkMacSystemFont, sans-serif'), # 全局字体颜色（浅灰白）
                    
                    # X轴配置
                    xaxis=dict(
                        showgrid=False,       # 不显示纵向网格
                        zeroline=False,       # 不显示X轴的零线
                        tickfont=dict(color='#888888'), # 刻度文字颜色
                        title=dict(font=dict(color='#888888')),
                    ),
                    
                    # Y轴配置
                    yaxis=dict(
                        gridcolor='#333333',  # 横向网格颜色
                        griddash='dash',      # 虚线网格（交易所风格）
                        zeroline=True,        # 显示零线
                        zerolinecolor='#666666', # 零线颜色（稍亮一点的灰色）
                        zerolinewidth=1,      # 零线宽度
                        # 注意：Plotly 不支持 zerolinedash 属性，零线是实线
                        tickfont=dict(color='#888888'),
                        title=dict(font=dict(color='#888888')),
                    ),
                    
                    margin=dict(l=60, r=20, t=10, b=50), # 边距
                    hovermode='x unified', # 鼠标悬停时的交互模式
                    height=380,
                    showlegend=False
                )
                
                # 平滑贝塞尔曲线 + 渐变填充（交易所级效果）
                fig.update_traces(
                    fill='tonexty',
                    mode='lines',  # 只显示线条，不显示数据点
                    line=dict(width=2.5),
                    line_shape='spline',  # 关键：平滑贝塞尔曲线（交易所风格）
                    fillcolor='rgba(76, 175, 80, 0.2)' if total_pnl >= 0 else 'rgba(255, 82, 82, 0.2)',
                    line_color='#4CAF50' if total_pnl >= 0 else '#FF5252',
                    hovertemplate='<b>%{x|%Y-%m-%d %H:%M}</b><br>累计盈亏: $%{y:,.2f}<extra></extra>',
                    hoverlabel=dict(
                        bgcolor='rgba(30, 30, 30, 0.95)',
                        bordercolor='#555555',
                        font_size=12,
                        font_family='-apple-system, BlinkMacSystemFont, sans-serif'
                    )
                )
                
                # 添加0轴线（如果数据跨越0线）
                if chart_df['cumulative_pnl'].min() < 0 < chart_df['cumulative_pnl'].max():
                    fig.add_hline(
                        y=0,
                        line_dash="dash",
                        line_color="#888888",
                        line_width=1.5,
                        opacity=0.6,
                        annotation_text="盈亏分界线",
                        annotation_position="right",
                        annotation_font_size=10,
                        annotation_font_color="#888888"
                    )
                
                # 显示图表（隐藏工具栏，保持简洁）
                st.plotly_chart(fig, use_container_width=True, config={
                    'displayModeBar': False,
                    'displaylogo': False
                })
            
            st.markdown("---")
            
            # ======================================================================
            # 交易列表和复盘区域 (左列表，右详情)
            # ======================================================================
            st.markdown("### 📋 交易列表 & 复盘")
            
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
                    
                    # 1. 顶部大标题卡片 (iOS风格)
                    pnl_color_class = "green" if trade['net_pnl'] >= 0 else "red"
                    pnl_display = f"+{trade['net_pnl']:.2f}" if trade['net_pnl'] > 0 else f"{trade['net_pnl']:.2f}"
                    
                    st.markdown(f"""
                    <div style='background: #1E1E1E; border: 1px solid #333; border-radius: 20px; padding: 30px; text-align: center; margin-bottom: 24px;'>
                        <div style='font-size: 24px; font-weight: 700; color: #FFF; margin-bottom: 10px;'>{trade['symbol']}</div>
                        <span style='display: inline-block; padding: 4px 12px; border-radius: 6px; font-size: 12px; font-weight: bold; 
                            background: {'rgba(76, 175, 80, 0.15)' if 'Long' in trade['direction'] else 'rgba(255, 82, 82, 0.15)'}; 
                            color: {'#66BB6A' if 'Long' in trade['direction'] else '#FF5252'};'>
                            {trade['direction']}
                        </span>
                        <div style='font-size: 42px; font-weight: 800; color: {'#4CAF50' if trade['net_pnl'] >= 0 else '#FF5252'}; 
                            margin: 15px 0; letter-spacing: -1px;'>
                            ${pnl_display}
                        </div>
                        <div style='color: #666; font-size: 13px;'>{trade['close_date_str']}</div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # 2. 信息网格 (iOS风格卡片)
                    st.markdown("""
                    <style>
                    .info-card-custom {
                        background: #1E1E1E;
                        border: 1px solid #333;
                        border-radius: 16px;
                        padding: 16px;
                    }
                    </style>
                    """, unsafe_allow_html=True)
                    
                    info_col1, info_col2 = st.columns(2)
                    with info_col1:
                        st.markdown(f"""
                        <div class="info-card-custom">
                            <div style='font-size: 12px; color: #888; text-transform: uppercase; margin-bottom: 4px;'>开仓时间</div>
                            <div style='font-size: 16px; color: #FFF; font-weight: 600;'>{trade['open_date_str']}</div>
                        </div>
                        """, unsafe_allow_html=True)
                        st.markdown("<br>", unsafe_allow_html=True)
                        st.markdown(f"""
                        <div class="info-card-custom">
                            <div style='font-size: 12px; color: #888; text-transform: uppercase; margin-bottom: 4px;'>持仓时长</div>
                            <div style='font-size: 16px; color: #FFF; font-weight: 600;'>{trade['duration_str']}</div>
                        </div>
                        """, unsafe_allow_html=True)
                    
                    with info_col2:
                        st.markdown(f"""
                        <div class="info-card-custom">
                            <div style='font-size: 12px; color: #888; text-transform: uppercase; margin-bottom: 4px;'>平仓时间</div>
                            <div style='font-size: 16px; color: #FFF; font-weight: 600;'>{trade['close_date_str']}</div>
                        </div>
                        """, unsafe_allow_html=True)
                        st.markdown("<br>", unsafe_allow_html=True)
                        st.markdown(f"""
                        <div class="info-card-custom">
                            <div style='font-size: 12px; color: #888; text-transform: uppercase; margin-bottom: 4px;'>手续费</div>
                            <div style='font-size: 16px; color: #FFF; font-weight: 600;'>${trade['total_fee']:.2f}</div>
                        </div>
                        """, unsafe_allow_html=True)
                    
                    st.markdown("---")
                    
                    # 2. 复盘工作台 (核心功能)
                    st.markdown("### 📝 Trade Review (复盘工作台)")
                    
                    # 从数据库重新读取最新数据 (确保实时性)
                    trade_row = raw_df[raw_df['id'] == trade['round_id']].iloc[0]
                    current_note_db = trade_row.get('notes', '')
                    current_strategy_db = trade_row.get('strategy', '')
                    if pd.isna(current_note_db): current_note_db = ""
                    if pd.isna(current_strategy_db): current_strategy_db = ""
                    
                    # 策略输入框
                    st.markdown("**Strategy / Setup (策略/依据)**")
                    st.caption("例如：趋势突破、EMA回调、支撑位反弹...")
                    user_strategy = st.text_input("策略名称", value=current_strategy_db, placeholder="输入你的交易策略", label_visibility="collapsed")
                    
                    st.markdown("<br>", unsafe_allow_html=True)
                    
                    # 详细笔记输入框
                    st.markdown("**Detailed Notes (详细分析 & 心理状态)**")
                    st.caption("记录入场理由、止损执行情况、以及当时的情绪...")
                    user_note = st.text_area("复盘笔记", value=current_note_db, height=250, 
                                            placeholder="记录你的心理状态、入场理由、离场反思...", label_visibility="collapsed")
                    
                    # 保存按钮区域
                    col_save1, col_save2, col_save3 = st.columns([1, 2, 1])
                    with col_save2:
                        if st.button("💾 保存复盘", use_container_width=True, type="primary"):
                            # 调用后端保存（同时保存策略和笔记）
                            success = engine.update_trade_note(trade['round_id'], user_note, user_strategy, selected_key)
                            if success:
                                st.success("✅ 复盘已保存！")
                                time.sleep(0.5)
                                st.rerun()
                            else:
                                st.error("❌ 保存失败，请重试")

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