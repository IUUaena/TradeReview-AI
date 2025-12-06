import streamlit as st
import pandas as pd
import time
import os
import plotly.express as px
from data_engine import TradeDataEngine
from data_processor import process_trades_to_rounds # 引入核心逻辑
from word_exporter import WordExporter

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
        
        # --- C. Word 导出功能 (新增) ---
        with st.expander("📄 导出 Word 报告"):
            st.markdown("**导出交易复盘报告到 Word 文档**")
            st.caption("包含交易数据、笔记和截图，可直接发给 AI 分析")
            
            export_time_range = st.selectbox(
                "时间范围",
                ["最近一周", "最近一月", "最近一年", "全部历史"],
                key="export_time_range"
            )
            
            # 映射中文到英文
            time_range_map = {
                "最近一周": "week",
                "最近一月": "month",
                "最近一年": "year",
                "全部历史": "all"
            }
            
            if st.button("📥 导出 Word 报告", use_container_width=True, type="primary"):
                if selected_key:
                    # 加载数据
                    raw_df = engine.load_trades(selected_key)
                    
                    if raw_df.empty:
                        st.error("❌ 暂无数据，请先同步数据。")
                    else:
                        # 处理数据
                        rounds_df = process_trades_to_rounds(raw_df)
                        
                        if rounds_df.empty:
                            st.error("❌ 没有完整的交易记录可导出。")
                        else:
                            # 获取 API key tag
                            key_tag = selected_key.strip()[-4:] if selected_key else ""
                            
                            # 创建导出器（默认保存到 D:\TradeReview AI\Trading_Reports）
                            exporter = WordExporter(
                                db_path=engine.db_path
                            )
                            
                            # 导出（rounds_df 和 raw_df 已经按账户筛选过了）
                            with st.spinner("正在生成 Word 文档，请稍候..."):
                                file_path, message = exporter.export_round_trips_to_word(
                                    rounds_df,
                                    raw_df,
                                    api_key_tag=key_tag,
                                    time_range=time_range_map[export_time_range]
                                )
                            
                            if file_path:
                                st.success(message)
                                
                                # 显示文件路径（确保是绝对路径）
                                abs_file_path = os.path.abspath(file_path)
                                st.info(f"📁 文件位置: {abs_file_path}")
                                
                                # 如果是 Windows 路径，额外提示
                                if os.name == 'nt' and abs_file_path.startswith('D:\\'):
                                    st.caption(f"💡 提示：文件已保存在 Windows 本地路径")
                                
                                # 提供下载按钮
                                try:
                                    with open(file_path, 'rb') as f:
                                        st.download_button(
                                            label="💾 下载 Word 文档",
                                            data=f.read(),
                                            file_name=os.path.basename(file_path),
                                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                            use_container_width=True
                                        )
                                except Exception as e:
                                    st.warning(f"无法创建下载链接: {e}")
                            else:
                                st.error(message)
                else:
                    st.warning("请先选择账户。")
                    
        # --- D. 危险区域 (折叠) ---
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

# 筛选器重置回调函数（必须在组件渲染前定义）
def reset_filters_callback():
    """重置所有筛选条件到默认值"""
    st.session_state.filter_symbol = "全部"
    st.session_state.filter_strategy = "全部"
    st.session_state.filter_direction = "全部"

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
            # 顶部标题栏（带手动录入按钮）
            # ======================================================================
            dashboard_header_col1, dashboard_header_col2 = st.columns([1, 0.05])
            with dashboard_header_col1:
                st.markdown("### 📊 Dashboard")
            with dashboard_header_col2:
                if st.button("➕", help="手动录入交易", use_container_width=True, key="add_btn_top"):
                    if 'show_add_form' not in st.session_state:
                        st.session_state.show_add_form = False
                    st.session_state.show_add_form = not st.session_state.show_add_form
                    st.rerun()
            
            # ======================================================================
            # 高级筛选栏 (Advanced Filtering)
            # ======================================================================
            st.markdown("---")
            
            # 提取所有唯一的币种和策略（从原始数据中提取，用于下拉菜单）
            all_symbols = sorted([s for s in rounds_df['symbol'].unique() if pd.notna(s) and s])
            
            # 从原始数据中提取策略（因为 rounds_df 可能没有策略字段）
            all_strategies_raw = raw_df['strategy'].dropna().unique()
            all_strategies = sorted([s for s in all_strategies_raw if s and s.strip()])
            
            # 初始化筛选器默认值（如果不存在）
            if 'filter_symbol' not in st.session_state:
                st.session_state.filter_symbol = "全部"
            if 'filter_strategy' not in st.session_state:
                st.session_state.filter_strategy = "全部"
            if 'filter_direction' not in st.session_state:
                st.session_state.filter_direction = "全部"
            
            # 筛选栏
            filter_col1, filter_col2, filter_col3, filter_col4 = st.columns([2, 2, 2, 1])
            
            with filter_col1:
                symbol_options = ["全部"] + all_symbols
                filter_symbol = st.selectbox(
                    "🔍 Symbol (币种)",
                    options=symbol_options,
                    key="filter_symbol",
                    help="按币种筛选交易"
                )
            
            with filter_col2:
                strategy_options = ["全部"] + all_strategies if all_strategies else ["全部"]
                filter_strategy = st.selectbox(
                    "📊 Strategy (策略)",
                    options=strategy_options,
                    key="filter_strategy",
                    help="按策略筛选交易"
                )
            
            with filter_col3:
                direction_options = ["全部", "做多 (Long)", "做空 (Short)"]
                filter_direction = st.selectbox(
                    "↕️ Direction (方向)",
                    options=direction_options,
                    key="filter_direction",
                    help="按方向筛选交易"
                )
            
            with filter_col4:
                st.markdown("<br>", unsafe_allow_html=True)  # 对齐按钮
                # 使用 on_click 回调函数，而不是在 if 中修改 session_state
                st.button("🔄 Reset", use_container_width=True, key="reset_filter", on_click=reset_filters_callback)
            
            # 应用筛选条件
            filtered_rounds_df = rounds_df.copy()
            
            if filter_symbol != "全部":
                filtered_rounds_df = filtered_rounds_df[filtered_rounds_df['symbol'] == filter_symbol]
            
            if filter_strategy != "全部":
                # 直接使用 rounds_df 中的 strategy 字段筛选（已通过 data_processor 添加）
                filtered_rounds_df = filtered_rounds_df[
                    filtered_rounds_df['strategy'].apply(
                        lambda x: str(x) == filter_strategy if pd.notna(x) and x else False
                    )
                ]
            
            if filter_direction != "全部":
                direction_keyword = "Long" if "Long" in filter_direction else "Short"
                filtered_rounds_df = filtered_rounds_df[filtered_rounds_df['direction'].str.contains(direction_keyword, na=False)]
            
            # 显示筛选状态
            if filter_symbol != "全部" or filter_strategy != "全部" or filter_direction != "全部":
                active_filters = []
                if filter_symbol != "全部":
                    active_filters.append(f"币种: {filter_symbol}")
                if filter_strategy != "全部":
                    active_filters.append(f"策略: {filter_strategy}")
                if filter_direction != "全部":
                    active_filters.append(f"方向: {filter_direction}")
                st.info(f"📌 当前筛选: {', '.join(active_filters)} | 显示 {len(filtered_rounds_df)} 笔交易")
            
            st.markdown("---")
            
            # 使用筛选后的数据更新 rounds_df
            rounds_df = filtered_rounds_df
            
            if rounds_df.empty:
                st.warning("⚠️ 没有符合筛选条件的交易。请调整筛选条件。")
                st.stop()
            
            # ======================================================================
            # 手动录入表单（可折叠，在 Dashboard 下方）
            # ======================================================================
            if st.session_state.get('show_add_form', False):
                st.markdown("---")
                with st.expander("➕ 手动录入交易", expanded=True):
                    with st.form("add_trade_form", clear_on_submit=True):
                        form_col1, form_col2 = st.columns(2)
                        
                        with form_col1:
                            manual_symbol = st.text_input("币种 (Symbol)", placeholder="BTCUSDT", key="manual_symbol")
                            manual_direction = st.selectbox("方向 (Direction)", ["做多 (Long)", "做空 (Short)"], key="manual_direction")
                        
                        with form_col2:
                            manual_pnl = st.number_input("盈亏 (PnL) $", step=0.01, format="%.2f", key="manual_pnl")
                            manual_date = st.date_input("日期", value=pd.Timestamp.now().date(), key="manual_date")
                            manual_time = st.time_input("时间", value=pd.Timestamp.now().time(), key="manual_time")
                        
                        manual_strategy = st.text_input("策略 (Strategy)", placeholder="例如：趋势突破", key="manual_strategy")
                        
                        # 图片上传
                        manual_screenshot = st.file_uploader("📸 Chart Screenshot (图表截图)", 
                                                             type=['png', 'jpg', 'jpeg', 'gif'],
                                                             key="manual_screenshot")
                        if manual_screenshot:
                            st.image(manual_screenshot, caption="预览", width=300)
                        
                        manual_note = st.text_area("初始笔记 (Note)", placeholder="开仓理由、心理状态...", height=100, key="manual_note")
                        
                        submit_col1, submit_col2, submit_col3 = st.columns([1, 2, 1])
                        with submit_col2:
                            submitted = st.form_submit_button("💾 保存交易", use_container_width=True, type="primary")
                        
                        if submitted:
                            if not manual_symbol or manual_pnl is None:
                                st.error("❌ 请填写币种和盈亏金额！")
                            else:
                                # 组合日期和时间
                                date_time_str = f"{manual_date} {manual_time.strftime('%H:%M')}"
                                # 提取方向（"做多 (Long)" -> "Long"）
                                direction_clean = "Long" if "Long" in manual_direction else "Short"
                                
                                # 先保存交易，获取 trade_id
                                success, msg = engine.add_manual_trade(
                                    selected_key,
                                    manual_symbol.upper(),
                                    direction_clean,
                                    manual_pnl,
                                    date_time_str,
                                    manual_strategy,
                                    manual_note
                                )
                                
                                # 如果有上传图片，保存图片并更新交易记录
                                if success and manual_screenshot is not None:
                                    # 获取刚创建的交易ID（通过时间戳匹配）
                                    import uuid
                                    timestamp_ms = int(pd.Timestamp(date_time_str).timestamp() * 1000)
                                    base_id = f"MANUAL_{timestamp_ms}"
                                    screenshot_filename = engine.save_screenshot(manual_screenshot, base_id)
                                    if screenshot_filename:
                                        # 更新开仓记录的截图字段
                                        engine.update_trade(base_id, selected_key, manual_symbol.upper(), 
                                                           direction_clean, manual_pnl, date_time_str,
                                                           manual_strategy, manual_note, screenshot_filename)
                                
                                if success:
                                    st.success(msg)
                                    st.session_state.show_add_form = False
                                    time.sleep(0.5)
                                    st.rerun()
                                else:
                                    st.error(msg)
                
                st.markdown("---")
            
            # ======================================================================
            # iOS 风格数据看板 (Bento Grid)
            # ======================================================================
            
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
                    
                    # 操作按钮区域（编辑和删除）
                    action_col1, action_col2, action_col3 = st.columns([1, 1, 4])
                    
                    # 初始化 session_state
                    edit_key = f"edit_{trade['round_id']}"
                    if edit_key not in st.session_state:
                        st.session_state[edit_key] = False
                    
                    with action_col1:
                        if st.button("✏️ 编辑", use_container_width=True, key=f"edit_btn_{trade['round_id']}"):
                            st.session_state[edit_key] = not st.session_state[edit_key]
                            st.rerun()
                    
                    with action_col2:
                        if st.button("🗑️ 删除", use_container_width=True, type="secondary", key=f"delete_btn_{trade['round_id']}"):
                            # 删除确认对话框
                            st.session_state[f"confirm_delete_{trade['round_id']}"] = True
                            st.rerun()
                    
                    # 删除确认逻辑
                    if st.session_state.get(f"confirm_delete_{trade['round_id']}", False):
                        st.warning("⚠️ 确定要删除这笔交易吗？此操作不可恢复！")
                        confirm_col1, confirm_col2 = st.columns(2)
                        with confirm_col1:
                            if st.button("✅ 确认删除", use_container_width=True, type="primary", key=f"confirm_yes_{trade['round_id']}"):
                                # 提取基础ID（去掉_OPEN或_CLOSE后缀）
                                base_id = trade['round_id'].replace('_OPEN', '').replace('_CLOSE', '')
                                success, msg = engine.delete_trade(base_id, selected_key)
                                if success:
                                    st.success(msg)
                                    time.sleep(0.5)
                                    # 清除所有相关session_state
                                    for key in list(st.session_state.keys()):
                                        if trade['round_id'] in str(key):
                                            del st.session_state[key]
                                    st.rerun()
                                else:
                                    st.error(msg)
                        with confirm_col2:
                            if st.button("❌ 取消", use_container_width=True, key=f"confirm_no_{trade['round_id']}"):
                                st.session_state[f"confirm_delete_{trade['round_id']}"] = False
                                st.rerun()
                    
                    # 编辑表单（可折叠）
                    if st.session_state.get(edit_key, False):
                        st.markdown("---")
                        with st.expander("✏️ 编辑交易", expanded=True):
                            # 获取原始数据
                            trade_row = raw_df[raw_df['id'] == trade['round_id']].iloc[0]
                            current_strategy = trade_row.get('strategy', '')
                            current_note = trade_row.get('notes', '')
                            if pd.isna(current_strategy): current_strategy = ""
                            if pd.isna(current_note): current_note = ""
                            
                            with st.form(f"edit_form_{trade['round_id']}", clear_on_submit=False):
                                edit_form_col1, edit_form_col2 = st.columns(2)
                                
                                with edit_form_col1:
                                    edit_symbol = st.text_input("币种 (Symbol)", value=trade['symbol'], key=f"edit_symbol_{trade['round_id']}")
                                    edit_direction = st.selectbox("方向 (Direction)", 
                                                                 ["做多 (Long)", "做空 (Short)"],
                                                                 index=0 if "Long" in trade['direction'] else 1,
                                                                 key=f"edit_direction_{trade['round_id']}")
                                
                                with edit_form_col2:
                                    edit_pnl = st.number_input("盈亏 (PnL) $", value=float(trade['net_pnl']), 
                                                               step=0.01, format="%.2f", key=f"edit_pnl_{trade['round_id']}")
                                    # 提取日期和时间
                                    try:
                                        dt_obj = pd.to_datetime(trade['close_date_str'])
                                        edit_date = st.date_input("日期", value=dt_obj.date(), key=f"edit_date_{trade['round_id']}")
                                        edit_time = st.time_input("时间", value=dt_obj.time(), key=f"edit_time_{trade['round_id']}")
                                    except:
                                        edit_date = st.date_input("日期", value=pd.Timestamp.now().date(), key=f"edit_date_{trade['round_id']}")
                                        edit_time = st.time_input("时间", value=pd.Timestamp.now().time(), key=f"edit_time_{trade['round_id']}")
                                
                                edit_strategy = st.text_input("策略 (Strategy)", value=current_strategy, key=f"edit_strategy_{trade['round_id']}")
                                
                                # 图片上传
                                current_screenshot = trade_row.get('screenshot', '')
                                if pd.notna(current_screenshot) and current_screenshot:
                                    upload_dir = os.path.join(os.path.dirname(engine.db_path), 'uploads')
                                    screenshot_path = os.path.join(upload_dir, current_screenshot)
                                    if os.path.exists(screenshot_path):
                                        st.image(screenshot_path, caption="当前截图", width=300)
                                edit_screenshot = st.file_uploader("📸 Chart Screenshot (图表截图)", 
                                                                   type=['png', 'jpg', 'jpeg', 'gif'],
                                                                   key=f"edit_screenshot_{trade['round_id']}")
                                if edit_screenshot:
                                    st.image(edit_screenshot, caption="新截图预览", width=300)
                                
                                edit_note = st.text_area("初始笔记 (Note)", value=current_note, height=100, key=f"edit_note_{trade['round_id']}")
                                
                                submit_edit_col1, submit_edit_col2, submit_edit_col3 = st.columns([1, 2, 1])
                                with submit_edit_col2:
                                    submitted_edit = st.form_submit_button("💾 保存修改", use_container_width=True, type="primary")
                                
                                if submitted_edit:
                                    # 组合日期和时间
                                    date_time_str = f"{edit_date} {edit_time.strftime('%H:%M')}"
                                    direction_clean = "Long" if "Long" in edit_direction else "Short"
                                    
                                    # 提取基础ID（区分手动录入和 API 导入）
                                    round_id = trade['round_id']
                                    if round_id.startswith('MANUAL_'):
                                        # 手动录入：去掉 _OPEN 或 _CLOSE 后缀
                                        base_id = round_id.replace('_OPEN', '').replace('_CLOSE', '')
                                    else:
                                        # API 导入：round_id 本身就是原始 ID，直接使用
                                        base_id = round_id
                                    
                                    # 处理图片上传
                                    screenshot_filename = None
                                    if edit_screenshot is not None:
                                        screenshot_filename = engine.save_screenshot(edit_screenshot, base_id)
                                    
                                    # 调用更新方法
                                    success, msg = engine.update_trade(
                                        base_id,
                                        selected_key,
                                        edit_symbol.upper(),
                                        direction_clean,
                                        edit_pnl,
                                        date_time_str,
                                        edit_strategy,
                                        edit_note,
                                        screenshot_filename
                                    )
                                    
                                    if success:
                                        st.success(msg)
                                        st.session_state[edit_key] = False
                                        time.sleep(0.5)
                                        st.rerun()
                                    else:
                                        st.error(msg)
                        
                        st.markdown("---")
                    
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
                    
                    # 显示截图（如果有）
                    screenshot_name = trade_row.get('screenshot', '')
                    if pd.notna(screenshot_name) and screenshot_name:
                        upload_dir = os.path.join(os.path.dirname(engine.db_path), 'uploads')
                        screenshot_path = os.path.join(upload_dir, screenshot_name)
                        if os.path.exists(screenshot_path):
                            st.markdown("#### 📸 Chart Screenshot (图表截图)")
                            st.image(screenshot_path, use_container_width=True)
                            st.markdown("---")
                    
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