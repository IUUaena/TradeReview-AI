import streamlit as st
import pandas as pd
import numpy as np  # v5.0 新增：用于蒙特卡洛模拟
import time
import os
import plotly.express as px
from data_engine import TradeDataEngine
from data_processor import process_trades_to_rounds # 引入核心逻辑
from word_exporter import WordExporter
from ai_assistant import generate_batch_review, generate_batch_review_v3, audit_single_trade, review_potential_trade
from risk_simulator import MonteCarloEngine  # v5.0 新增
from datetime import datetime

# ==============================================================================
# 0. 常量定义 (v3.0 核心复盘维度)
# ==============================================================================
MENTAL_STATES = ["🧘 Calm (平静)", "😰 FOMO (错失恐惧)", "😡 Revenge (报复)", "😨 Fear (恐惧)", "😌 Confident (自信)", "😐 Bored (无聊)", "🤯 Tilt (上头)"]

PROCESS_TAGS = ["✅ Good Process (知行合一)", "❌ Bad Process (乱做)", "🍀 Lucky (运气好)", "💀 Disaster (灾难)"]

COMMON_MISTAKES = ["#EarlyExit (早退)", "#NoStop (无止损)", "#Chasing (追涨杀跌)", "#OverSize (重仓)", "#AgainstTrend (逆势)", "#Hesitation (犹豫)", "#Impatience (缺乏耐心)"]

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
# 初始化：从数据库加载 AI 配置到 session_state
# ==============================================================================
if 'ai_key' not in st.session_state:
    st.session_state['ai_key'] = engine.get_setting('ai_key', '')
if 'ai_base_url' not in st.session_state:
    st.session_state['ai_base_url'] = engine.get_setting('ai_base_url', 'https://api.deepseek.com')
if 'system_manifesto' not in st.session_state:
    st.session_state['system_manifesto'] = engine.get_setting('system_manifesto', 
        "1. 绝不扛单，亏损达到 2% 无条件止损。\n2. 只做日线级别的顺势交易。\n3. 连续亏损 2 笔强制停止交易一天。")
if 'ai_model' not in st.session_state:
    st.session_state['ai_model'] = engine.get_setting('ai_model', 'deepseek-chat')

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
        
        # --- B. AI 配置 (v3.9 多厂商支持) ---
        with st.expander("🧠 AI 导师 & 系统配置"):
            # 预设厂商配置
            PROVIDER_PRESETS = {
                "DeepSeek (默认)": {
                    "url": "https://api.deepseek.com",
                    "models": ["deepseek-chat", "deepseek-reasoner"]
                },
            "Google Gemini": {
                # 务必确保末尾有斜杠 /，防止 Python openai 库 URL 拼接出错
                "url": "https://generativelanguage.googleapis.com/v1beta/openai/",
                # 模型名直接使用纯 ID（不带 models/ 前缀）
                "models": [
                    "gemini-1.5-flash",      # 推荐：目前最稳的免费版
                    "gemini-1.5-pro",        # 推荐：最聪明的版本
                    "gemini-2.0-flash-exp",  # 实验版：虽然强但极易 429
                    "gemini-1.5-flash-8b"    # 超轻量级
                ]
            },
                "OpenAI (官方)": {
                    "url": "https://api.openai.com/v1",
                    "models": ["gpt-4o", "gpt-4-turbo"]
                }
            }
            
            # 1. 厂商快速选择
            selected_provider = st.selectbox("🌍 快速选择 AI 厂商", list(PROVIDER_PRESETS.keys()))
            
            # 自动填充（如果用户点击了应用预设）
            if st.button("应用厂商预设 (自动填 URL)"):
                preset = PROVIDER_PRESETS[selected_provider]
                engine.set_setting('ai_base_url', preset['url'])
                # 默认选第一个模型
                engine.set_setting('ai_model', preset['models'][0])
                st.rerun()
            
            # === 强制修复 Google 连接按钮 ===
            if st.button("🔧 强制修复 Google 连接 (Fix v1main Error)"):
                # 官方唯一正确的 OpenAI 兼容地址 (必须包含 v1beta 和 openai)
                CORRECT_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
                
                # 强制写入数据库
                engine.set_setting('ai_base_url', CORRECT_URL)
                engine.set_setting('ai_model', "gemini-1.5-flash")  # 重置为最稳的模型
                
                # 强制刷新 Session
                st.session_state['ai_base_url'] = CORRECT_URL
                st.session_state['ai_model'] = "gemini-1.5-flash"
                
                st.success(f"已强制修复 URL 为: {CORRECT_URL}")
                st.info("请重新点击下方的 '保存配置' 按钮以确保生效！")
            
            # 2. 加载当前配置
            db_base_url = engine.get_setting('ai_base_url', "https://api.deepseek.com")
            db_key = engine.get_setting('ai_key', "")
            db_model = engine.get_setting('ai_model', "deepseek-chat") 
            db_manifesto = engine.get_setting('system_manifesto', 
                "1. 绝不扛单，亏损达到 2% 无条件止损。\n2. 只做日线级别的顺势交易。\n3. 连续亏损 2 笔强制停止交易一天。")
            
            # 3. 输入框 (允许微调)
            ai_base_url = st.text_input("API Base URL", value=db_base_url)
            ai_key = st.text_input("AI API Key", type="password", value=db_key)
            
            # 模型选择 (合并预设模型和当前模型)
            current_preset_models = PROVIDER_PRESETS.get(selected_provider, {}).get("models", [])
            if db_model not in current_preset_models:
                current_preset_models.insert(0, db_model)
                
            ai_model = st.selectbox(
                "Model Name (模型选择)", 
                options=current_preset_models,
                index=0 if db_model not in current_preset_models else current_preset_models.index(db_model)
            )
            
            st.markdown("---")
            st.caption("📜 System Manifesto (系统宪法)")
            system_manifesto = st.text_area("我的交易铁律", value=db_manifesto, height=150)
            
            if st.button("💾 保存配置"):
                engine.set_setting('ai_base_url', ai_base_url)
                engine.set_setting('ai_key', ai_key)
                engine.set_setting('ai_model', ai_model)
                engine.set_setting('system_manifesto', system_manifesto)
                
                st.session_state['ai_base_url'] = ai_base_url
                st.session_state['ai_key'] = ai_key
                st.session_state['ai_model'] = ai_model
                st.session_state['system_manifesto'] = system_manifesto
                st.success(f"已保存! 当前模型: {ai_model}")
        
        st.divider()
        
        # --- C. 数据同步 (折叠菜单) ---
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
        # --- C. Word 导出功能 (v3.7 双模式) ---
        with st.expander("📄 导出 Word 报告"):
            st.markdown("**导出复盘数据包**")
            
            export_time_range = st.selectbox(
                "时间范围",
                ["最近一周", "最近一月", "最近一年", "全部历史"],
                key="export_time_range"
            )
            
            # 新增：模式选择
            export_mode_cn = st.radio(
                "报告类型",
                ["完整版 (含 AI 审计结论)", "原始版 (供其他 AI 分析)"],
                captions=["存档用：包含心态评分、执行质量及 AI 的毒舌点评。", "投喂用：仅包含原始数据、截图和你的笔记，纯净无干扰。"]
            )
            
            # 映射参数
            time_range_map = {"最近一周": "week", "最近一月": "month", "最近一年": "year", "全部历史": "all"}
            mode_map = {"完整版 (含 AI 审计结论)": "full", "原始版 (供其他 AI 分析)": "raw"}
            
            if st.button("📥 开始生成报告", use_container_width=True, type="primary"):
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
                            with st.spinner("正在生成文档..."):
                                file_path, message = exporter.export_round_trips_to_word(
                                    rounds_df,
                                    raw_df,
                                    api_key_tag=key_tag,
                                    time_range=time_range_map[export_time_range],
                                    mode=mode_map[export_mode_cn]  # 传入用户选择的模式
                                )
                            
                            if file_path:
                                st.success(message)
                                
                                # 显示文件路径（确保是绝对路径）
                                abs_file_path = os.path.abspath(file_path)
                                st.info(f"📁 文件位置: {abs_file_path}")
                                
                                # 如果是 Windows 路径，额外提示
                                if os.name == 'nt' and abs_file_path.startswith('D:\\'):
                                    st.caption(f"💡 提示：文件已保存在 Windows 本地路径")
                                
                                # 提供下载
                                try:
                                    with open(file_path, 'rb') as f:
                                        st.download_button(
                                            label="💾 点击下载文档",
                                            data=f.read(),
                                            file_name=os.path.basename(file_path),
                                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                            use_container_width=True
                                        )
                                except Exception as e:
                                    st.info(f"文件已保存至: {file_path}")
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
            # 0. v3.3 智能风控沙盘 (Pre-Trade Sandbox)
            # ======================================================================
            with st.expander("🛡️ 智能风控沙盘 (开仓计算器 + AI 拦截)", expanded=False):
                st.caption("✋ 开仓前先来这里！输入你的止损和风险额度，AI 帮你把关。")
                
                sb_col1, sb_col2, sb_col3 = st.columns([1, 1, 2])
                
                with sb_col1:
                    sb_symbol = st.text_input("标的 (Symbol)", value="BTCUSDT", key="sb_symbol").upper()
                    sb_risk = st.number_input("💸 单笔风险金额 ($)", value=100.0, step=10.0, help="以损定仓：这笔交易你最多愿意亏多少钱？")
                    
                with sb_col2:
                    sb_entry = st.number_input("入场价 (Entry)", value=0.0, step=0.1, format="%.5f")
                    sb_sl = st.number_input("🛑 止损价 (Stop Loss)", value=0.0, step=0.1, format="%.5f")
                    sb_tp = st.number_input("🎯 止盈价 (Take Profit)", value=0.0, step=0.1, format="%.5f")
                    
                with sb_col3:
                    st.markdown("##### 📊 实时计算结果")
                    if sb_entry > 0 and sb_sl > 0:
                        # 自动计算
                        risk_diff = abs(sb_entry - sb_sl)
                        direction_str = "🟢 做多 (Long)" if sb_entry > sb_sl else "🔴 做空 (Short)"
                        
                        if risk_diff == 0:
                            st.error("止损价不能等于入场价")
                        else:
                            # 核心公式：数量 = 风险金额 / 止损差价
                            qty_suggest = sb_risk / risk_diff
                            position_value = qty_suggest * sb_entry
                            
                            # 盈亏比
                            rr_display = "N/A"
                            if sb_tp > 0:
                                reward_diff = abs(sb_tp - sb_entry)
                                rr = reward_diff / risk_diff
                                rr_color = "green" if rr >= 2.0 else "red"
                                rr_display = f":{rr_color}[{rr:.2f}]"
                            
                            # 显示大字报
                            st.markdown(f"**方向**: {direction_str}")
                            st.markdown(f"**建议仓位**: :blue[{qty_suggest:.4f} 个] ({sb_symbol})")
                            st.markdown(f"**持仓价值**: ${position_value:,.2f}")
                            st.markdown(f"**盈亏比 (R:R)**: {rr_display}")
                            
                            # AI 拦截按钮
                            if st.button("🤖 呼叫 AI 风控官审查", type="primary", use_container_width=True):
                                if 'ai_key' not in st.session_state or not st.session_state['ai_key']:
                                    st.error("请先在左侧配置 AI Key")
                                else:
                                    with st.spinner("AI 正在核对你的系统宪法..."):
                                        plan_data = {
                                            "symbol": sb_symbol,
                                            "entry": sb_entry,
                                            "sl": sb_sl,
                                            "tp": sb_tp,
                                            "risk_money": sb_risk
                                        }
                                        manifesto = st.session_state.get('system_manifesto', '')
                                        # 获取配置的模型名称 (v3.5)
                                        curr_model = st.session_state.get('ai_model', 'deepseek-chat')
                                        res = review_potential_trade(
                                            st.session_state['ai_key'],
                                            st.session_state['ai_base_url'],
                                            plan_data,
                                            manifesto,
                                            curr_model  # 传入模型名称
                                        )
                                        st.info(res)
                    else:
                        st.info("👈 请输入价格以获取计算结果")
            
            st.markdown("---")
            
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
            # 交易列表和复盘区域 (使用 Tab 分隔)
            # ======================================================================
            # 使用 Tab 分隔功能区
            tab_list, tab_analysis, tab_report, tab_strategy, tab_risk = st.tabs(["📋 交易复盘", "📊 归因分析", "🔥 导师周报", "📚 策略库", "🎲 风险模拟"])
            
            # === Tab 1: 原有的交易列表与详情 ===
            with tab_list:
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
                    
                    # ==================================================================
                    # 2. 深度复盘工作台 (v3.0 Pro)
                    # ==================================================================
                    st.markdown("### 🧘 Deep Review (深度复盘)")
                    
                    # 从数据库重新读取最新数据 (确保实时性)
                    trade_row = raw_df[raw_df['id'] == trade['round_id']].iloc[0]
                    
                    # 获取现有数据 (如果没有则设为默认值)
                    curr_strategy = trade_row.get('strategy', '') or ""
                    curr_note = trade_row.get('notes', '') or ""
                    curr_mental = trade_row.get('mental_state', '') or MENTAL_STATES[0]
                    curr_rr = trade_row.get('rr_ratio', None)
                    if curr_rr is None or pd.isna(curr_rr):
                        curr_rr = 0.0
                    else:
                        curr_rr = float(curr_rr)
                    curr_rating = trade_row.get('setup_rating', None)
                    if curr_rating is None or pd.isna(curr_rating):
                        curr_rating = 5
                    else:
                        curr_rating = int(curr_rating)
                    curr_process = trade_row.get('process_tag', '') or PROCESS_TAGS[0]
                    curr_mistakes = trade_row.get('mistake_tags', '') or ""
                    curr_mistakes_list = [tag.strip() for tag in curr_mistakes.split(',')] if curr_mistakes else []
                    
                    # --- 区域 A: 核心定性 (一行两列) ---
                    with st.container():
                        st.caption("先给这笔交易定性：是凭借实力，还是运气？心态炸了吗？")
                        row1_col1, row1_col2 = st.columns(2)
                        
                        with row1_col1:
                            # 心理状态
                            try:
                                mental_index = MENTAL_STATES.index(curr_mental) if curr_mental in MENTAL_STATES else 0
                            except:
                                mental_index = 0
                            new_mental = st.selectbox(
                                "🧠 Mental State (心理状态)", 
                                options=MENTAL_STATES,
                                index=mental_index,
                                help="诚实面对自己，当时下单的那一刻，你在想什么？"
                            )
                            # 过程质量
                            try:
                                process_index = PROCESS_TAGS.index(curr_process) if curr_process in PROCESS_TAGS else 0
                            except:
                                process_index = 0
                            new_process = st.selectbox(
                                "⚖️ Process Quality (执行质量)",
                                options=PROCESS_TAGS,
                                index=process_index,
                                help="抛开盈亏，你的执行符合系统吗？"
                            )
                            
                        with row1_col2:
                            # 形态评分 (滑块)
                            new_rating = st.slider(
                                "⭐ Setup Rating (机会评分)", 
                                min_value=1, max_value=10, value=curr_rating,
                                help="1分是垃圾行情强行做，10分是完美的教科书式机会"
                            )
                            # 预期盈亏比
                            new_rr = st.number_input(
                                "🎯 Expected R:R (计划盈亏比)",
                                min_value=0.0, step=0.1, value=curr_rr,
                                help="下单时你计划赚赔比是多少？"
                            )
                    st.markdown("<br>", unsafe_allow_html=True)
                    # --- 区域 B: 策略与细节 ---
                    col_strat, col_tags = st.columns([1, 1])
                    
                    with col_strat:
                        # 动态获取策略列表
                        all_strategies_dict = engine.get_all_strategies()
                        available_strategies = list(all_strategies_dict.keys())
                        
                        # 确保当前策略在列表里
                        if curr_strategy and curr_strategy not in available_strategies:
                            available_strategies.append(curr_strategy)
                        
                        # 如果列表为空，提供默认提示
                        if not available_strategies:
                            available_strategies = ["请先在侧边栏添加策略"]
                        
                        new_strategy = st.selectbox(
                            "📉 Strategy (策略依据)",
                            options=available_strategies,
                            index=available_strategies.index(curr_strategy) if curr_strategy in available_strategies else 0,
                            help="AI 会根据侧边栏配置的策略规则进行审核"
                        )
                        
                        # 显示选中策略的规则提示 (方便你自己看)
                        if new_strategy in all_strategies_dict:
                            st.caption(f"📝 规则: {all_strategies_dict[new_strategy][:50]}...")
                    with col_tags:
                        # 错误标签 (多选)
                        new_mistakes = st.multiselect(
                            "❌ Mistakes (犯错检讨)",
                            options=COMMON_MISTAKES,
                            default=[tag for tag in curr_mistakes_list if tag in COMMON_MISTAKES],
                            help="如果没犯错留空即可"
                        )
                    # --- 区域 C: 深度笔记与截图 ---
                    st.markdown("**📝 Detailed Notes (交易日记)**")
                    new_note = st.text_area(
                        "label", 
                        value=curr_note, 
                        height=150, 
                        placeholder="在此记录你的心路历程：\n1. 为什么在这个位置入场？\n2. 止损是怎么设的？\n3. 持仓时有没有动摇？",
                        label_visibility="collapsed"
                    )
                    # 截图展示与上传 (放在折叠区域，节省空间)
                    screenshot_name = trade_row.get('screenshot', '')
                    with st.expander("📸 图表截图 (点击展开)", expanded=False):
                        if pd.notna(screenshot_name) and screenshot_name:
                            upload_dir = os.path.join(os.path.dirname(engine.db_path), 'uploads')
                            screenshot_path = os.path.join(upload_dir, screenshot_name)
                            if os.path.exists(screenshot_path):
                                st.image(screenshot_path, use_container_width=True)
                                
                                # === 新增：删除按钮 ===
                                if st.button("🗑️ 删除这张截图", key=f"del_img_{trade['round_id']}"):
                                    ok, msg = engine.delete_screenshot(trade['round_id'], selected_key)
                                    if ok:
                                        st.success(msg)
                                        time.sleep(0.5)
                                        st.rerun()
                                    else:
                                        st.error(msg)
                            else:
                                st.warning("⚠️ 截图文件丢失")
                        
                        # 允许重新上传
                        new_screenshot = st.file_uploader("上传/替换截图", type=['png', 'jpg', 'jpeg'])
                    # --- 保存按钮 ---
                    save_col1, save_col2 = st.columns([3, 1])
                    with save_col2:
                        if st.button("💾 保存复盘", use_container_width=True, type="primary"):
                            # 1. 准备数据包
                            update_data = {
                                'mental_state': new_mental,
                                'process_tag': new_process,
                                'setup_rating': new_rating,
                                'rr_ratio': new_rr,
                                'strategy': new_strategy,
                                'mistake_tags': ",".join(new_mistakes),
                                'notes': new_note
                            }
                            
                            # 2. 如果有新图，先保存图
                            if new_screenshot:
                                # 提取基础ID
                                base_id = trade['round_id'].replace('_OPEN', '').replace('_CLOSE', '')
                                fname = engine.save_screenshot(new_screenshot, base_id)
                                if fname:
                                    update_data['screenshot'] = fname
                            
                            # 3. 调用 v3.0 增强更新接口
                            # 提取基础ID
                            base_id = trade['round_id'].replace('_OPEN', '').replace('_CLOSE', '')
                            success, msg = engine.update_trade_extended(base_id, selected_key, update_data)
                            
                            if success:
                                st.success(msg)
                                time.sleep(0.5)
                                st.rerun()
                            else:
                                st.error(msg)
                    # ==================================================================
                    # 3. AI 审计员 (The Auditor)
                    # ==================================================================
                    st.divider()
                    st.markdown("### 🤖 AI Auditor (交易审计)")
                    
                    ai_res = trade_row.get('ai_analysis', '')
                    
                    if ai_res:
                        st.info(ai_res)
                    else:
                        st.caption("保存复盘笔记后，可请求 AI 进行单笔审计。")
                        
                    # 单笔审计按钮 (v3.0 正式版)
                    if st.button("🔍 请求 AI 审计这笔交易", use_container_width=True):
                        if 'ai_key' not in st.session_state or not st.session_state.get('ai_key'):
                            st.error("请先在左侧配置 AI Key")
                        else:
                            with st.spinner("👮 审计师正在核对你的系统宪法..."):
                                from ai_assistant import audit_single_trade
                                
                                # 准备数据字典
                                trade_data_dict = trade_row.to_dict()
                                # 确保包含 v3.0 字段 (如果 row 里没有，手动补上当前界面的值)
                                trade_data_dict['mental_state'] = new_mental
                                trade_data_dict['process_tag'] = new_process
                                trade_data_dict['setup_rating'] = new_rating
                                trade_data_dict['rr_ratio'] = new_rr
                                trade_data_dict['mistake_tags'] = ",".join(new_mistakes)
                                trade_data_dict['strategy'] = new_strategy
                                trade_data_dict['notes'] = new_note
                                # 添加必要的时间字段
                                if 'open_date_str' not in trade_data_dict:
                                    trade_data_dict['open_date_str'] = trade.get('open_date_str', '')
                                if 'close_date_str' not in trade_data_dict:
                                    trade_data_dict['close_date_str'] = trade.get('close_date_str', '')
                                if 'duration_str' not in trade_data_dict:
                                    trade_data_dict['duration_str'] = trade.get('duration_str', '')
                                if 'net_pnl' not in trade_data_dict:
                                    trade_data_dict['net_pnl'] = trade.get('net_pnl', 0)
                                if 'symbol' not in trade_data_dict:
                                    trade_data_dict['symbol'] = trade.get('symbol', '')
                                if 'direction' not in trade_data_dict:
                                    trade_data_dict['direction'] = trade.get('direction', '')
                                
                                # 获取当前策略的规则描述
                                all_strats = engine.get_all_strategies()
                                current_strat_rules = all_strats.get(new_strategy, "")
                                
                                # 获取图片路径 (v3.4 Vision)
                                screenshot_full_path = None
                                if pd.notna(screenshot_name) and screenshot_name:
                                    upload_dir = os.path.join(os.path.dirname(engine.db_path), 'uploads')
                                    possible_path = os.path.join(upload_dir, screenshot_name)
                                    if os.path.exists(possible_path):
                                        screenshot_full_path = possible_path
                                
                                # 获取配置的模型名称
                                curr_model = st.session_state.get('ai_model', 'deepseek-chat')
                                
                                # 调用 AI
                                audit_result = audit_single_trade(
                                    st.session_state['ai_key'],
                                    st.session_state.get('ai_base_url', 'https://api.deepseek.com'),
                                    trade_data_dict,
                                    st.session_state.get('system_manifesto', ''),
                                    current_strat_rules,  # 传入策略规则
                                    image_path=screenshot_full_path,  # 传入图片路径 (v3.4)
                                    model_name=curr_model  # 传入模型名称 (v3.4)
                                )
                                
                                # 保存结果到数据库
                                if "失败" not in audit_result:
                                    # 提取基础ID
                                    base_id = trade['round_id'].replace('_OPEN', '').replace('_CLOSE', '')
                                    engine.update_ai_analysis(base_id, audit_result, selected_key)
                                    st.success("审计完成！结果已存档。")
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error(audit_result)

                else:
                    # 空状态引导
                    st.markdown(f"""
                    <div style='height: 600px; display: flex; flex-direction: column; align-items: center; justify-content: center; border: 2px dashed #333; border-radius: 10px; color: #666;'>
                        <h3>👈 请在左侧选择一笔交易</h3>
                        <p>点击列表中的一行，开始深度复盘</p>
                    </div>
                    """, unsafe_allow_html=True)
            
            # === Tab 2: 归因分析 (v4.0 交互式复盘) ===
            with tab_analysis:
                st.subheader("📊 交易归因分析 (Interactive Dashboard)")
                st.caption("💡 Tip: 点击下方的图表（柱子或饼图区域），可以直接筛选出对应的交易记录！")
                
                if rounds_df.empty:
                    st.info("暂无数据，请先录入交易。")
                else:
                    # 1. 数据准备
                    analysis_df = rounds_df.copy()
                    
                    # 辅助函数：补全 v3.0 字段
                    def get_meta_field(round_id, field_name, default_val):
                        rows = raw_df[raw_df['id'] == round_id]
                        if not rows.empty:
                            val = rows.iloc[0].get(field_name)
                            return val if pd.notna(val) and val != "" else default_val
                        return default_val
                    
                    # 批量补全
                    for col, default in [('mental_state', 'Unknown'), ('strategy', 'Undefined'), 
                                         ('process_tag', 'Unknown'), ('setup_rating', 0)]:
                        analysis_df[col] = analysis_df['round_id'].apply(lambda x: get_meta_field(x, col, default))
                    
                    # 将时间转换为 datetime 对象以便绘图
                    analysis_df['date_dt'] = pd.to_datetime(analysis_df['close_date_str'])
                    analysis_df['date_day'] = analysis_df['date_dt'].dt.date
                    
                    # ==========================================================
                    # A. 交易日历热力图 (Calendar Heatmap)
                    # ==========================================================
                    st.markdown("### 📅 交易频率热力图 (Trading Heatmap)")
                    
                    # 统计每天的交易次数和盈亏
                    daily_stats = analysis_df.groupby('date_day').agg(
                        count=('round_id', 'count'),
                        pnl=('net_pnl', 'sum')
                    ).reset_index()
                    
                    # 补全日期范围（为了画出完整的日历网格）
                    if not daily_stats.empty:
                        idx = pd.date_range(daily_stats['date_day'].min(), daily_stats['date_day'].max())
                        daily_stats = daily_stats.set_index('date_day').reindex(idx).fillna(0).reset_index()
                        daily_stats.columns = ['date', 'count', 'pnl']
                    
                    # 使用 Plotly 绘制热力图
                    # 颜色映射：亏损(红) -> 0(灰) -> 盈利(绿)
                    # 为了更直观，我们可以用 count 做热度，hover 显示 PnL
                    import plotly.graph_objects as go
                    
                    fig_cal = px.bar(
                        daily_stats, x='date', y='count',
                        color='pnl',
                        color_continuous_scale=['#FF5252', '#2C2C2C', '#4CAF50'],
                        color_continuous_midpoint=0,
                        labels={'count': '交易笔数', 'date': '日期', 'pnl': '当日盈亏'},
                        title="每日交易活跃度与盈亏 (颜色=盈亏, 高度=笔数)"
                    )
                    fig_cal.update_layout(
                        plot_bgcolor='#1E1E1E', paper_bgcolor='#1E1E1E', 
                        font=dict(color='#E0E0E0'),
                        xaxis_title="", yaxis_title="交易笔数",
                        hovermode="x unified"
                    )
                    
                    # 启用交互：点击柱子筛选那天的数据
                    selected_date_event = st.plotly_chart(fig_cal, use_container_width=True, on_select="rerun", selection_mode="points")
                    st.markdown("---")
                    
                    # ==========================================================
                    # B. 交互式归因图表 (Interactive Charts)
                    # ==========================================================
                    
                    # 初始化筛选掩码 (默认全选)
                    mask = pd.Series([True] * len(analysis_df))
                    filter_reason = "全部数据"
                    
                    # 处理日历筛选
                    if selected_date_event and len(selected_date_event.selection["points"]) > 0:
                        point = selected_date_event.selection["points"][0]
                        # Plotly 返回的 x 通常是日期字符串
                        if "x" in point:
                            clicked_date = point["x"]  # '2023-10-05'
                            mask = analysis_df['date_day'].astype(str) == clicked_date
                            filter_reason = f"📅 日期: {clicked_date}"
                    
                    # 布局：心态 & 策略
                    col_chart1, col_chart2 = st.columns(2)
                    
                    with col_chart1:
                        st.markdown("**🧠 心态盈亏 (点击筛选)**")
                        mental_pnl = analysis_df.groupby('mental_state')['net_pnl'].sum().reset_index()
                        fig_mental = px.bar(
                            mental_pnl, x='mental_state', y='net_pnl',
                            color='net_pnl', color_continuous_scale=['#FF5252', '#4CAF50'],
                        )
                        fig_mental.update_layout(clickmode='event+select', plot_bgcolor='#1E1E1E', paper_bgcolor='#1E1E1E', font=dict(color='#E0E0E0'))
                        # 交互
                        sel_mental = st.plotly_chart(fig_mental, use_container_width=True, on_select="rerun", key="chart_mental")
                        
                        if sel_mental and len(sel_mental.selection["points"]) > 0:
                            clicked_mental = sel_mental.selection["points"][0]["x"]
                            mask = analysis_df['mental_state'] == clicked_mental
                            filter_reason = f"🧠 心态: {clicked_mental}"
                    
                    with col_chart2:
                        st.markdown("**📉 策略效能 (点击筛选)**")
                        strat_stats = analysis_df.groupby('strategy')['net_pnl'].sum().reset_index().sort_values('net_pnl')
                        fig_strat = px.bar(
                            strat_stats, x='net_pnl', y='strategy', orientation='h',
                            color='net_pnl', color_continuous_scale=['#FF5252', '#4CAF50']
                        )
                        fig_strat.update_layout(clickmode='event+select', plot_bgcolor='#1E1E1E', paper_bgcolor='#1E1E1E', font=dict(color='#E0E0E0'))
                        # 交互
                        sel_strat = st.plotly_chart(fig_strat, use_container_width=True, on_select="rerun", key="chart_strat")
                        
                        if sel_strat and len(sel_strat.selection["points"]) > 0:
                            clicked_strat = sel_strat.selection["points"][0]["y"]
                            mask = analysis_df['strategy'] == clicked_strat
                            filter_reason = f"📉 策略: {clicked_strat}"
                    
                    # ==========================================================
                    # C. 联动交易列表 (Drill-down List)
                    # ==========================================================
                    
                    # 应用筛选
                    filtered_df = analysis_df[mask]
                    
                    st.divider()
                    st.markdown(f"### 🔍 关联交易明细 ({filter_reason})")
                    
                    if filtered_df.empty:
                        st.warning("该筛选条件下没有交易记录。")
                    else:
                        st.caption(f"共找到 {len(filtered_df)} 笔交易，总盈亏: ${filtered_df['net_pnl'].sum():.2f}")
                        
                        # 显示精简表格
                        st.dataframe(
                            filtered_df[['close_date_str', 'symbol', 'direction', 'net_pnl', 'mental_state', 'strategy', 'process_tag']],
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "net_pnl": st.column_config.NumberColumn("净盈亏", format="$%.2f"),
                                "mental_state": "心态",
                                "strategy": "策略",
                                "process_tag": "执行"
                            }
                        )
                        
                        # 如果只有少量数据，直接显示详情卡片
                        if len(filtered_df) <= 5:
                            for _, row in filtered_df.iterrows():
                                with st.expander(f"{row['symbol']} {row['direction']} (${row['net_pnl']}) - {row['close_date_str']}"):
                                    c1, c2 = st.columns([2, 1])
                                    with c1:
                                        st.markdown(f"**笔记**: {row.get('notes', '无')}")
                                        st.markdown(f"**AI审计**: {row.get('ai_analysis', '无')}")
                                    with c2:
                                        # 尝试显示图片
                                        raw_row = raw_df[raw_df['id'] == row['round_id']]
                                        if not raw_row.empty:
                                            img_name = raw_row.iloc[0].get('screenshot')
                                            if img_name:
                                                upload_dir = os.path.join(os.path.dirname(engine.db_path), 'uploads')
                                                img_path = os.path.join(upload_dir, img_name)
                                                if os.path.exists(img_path):
                                                    st.image(img_path)
            
            # === Tab 3: 新增的 AI 批量分析 ===
            with tab_report:
                st.subheader("🔥 交易行为深度诊断")
                st.caption('AI 导师将分析你最近的交易记录，寻找那些你自己都没发现的"亏损模式"。')
                
                col_r1, col_r2 = st.columns([1, 3])
                
                with col_r1:
                    report_mode = st.selectbox("分析范围", ["最近 30 笔交易", "本周交易", "本月交易"])
                    
                    if st.button("🚀 生成诊断报告", type="primary", use_container_width=True):
                        # 检查 AI 配置
                        if 'ai_key' not in st.session_state or not st.session_state.get('ai_key'):
                            st.error("请先在左侧侧边栏配置 AI API Key！")
                        else:
                            with st.spinner("AI 导师正在逐笔审查你的操作，请做好心理准备..."):
                                # 1. 筛选数据
                                target_df = rounds_df.copy()  # 使用处理好的 Round Trips
                                if report_mode == "最近 30 笔交易":
                                    target_df = target_df.head(30)
                                elif report_mode == "本周交易":
                                    # 筛选本周交易（简化处理，按最近7天）
                                    from datetime import timedelta
                                    now = datetime.now()
                                    week_ago = now - timedelta(days=7)
                                    # 这里需要根据实际数据的时间字段调整
                                    target_df = target_df.head(50)  # 临时方案
                                elif report_mode == "本月交易":
                                    target_df = target_df.head(100)  # 临时方案
                                
                                # === 核心修复：给缺失的列打补丁 ===
                                # 防止老数据没有这些列导致报错
                                # 从 raw_df 中补充 v3.0 字段（process_trades_to_rounds 可能没有这些字段）
                                required_cols = ['mental_state', 'process_tag', 'mistake_tags', 'setup_rating']
                                for col in required_cols:
                                    if col not in target_df.columns:
                                        # 尝试从 raw_df 中获取该字段
                                        target_df[col] = target_df['round_id'].apply(
                                            lambda rid: raw_df[raw_df['id'] == rid][col].iloc[0] 
                                            if not raw_df[raw_df['id'] == rid].empty and col in raw_df.columns 
                                            else '-'
                                        )
                                    else:
                                        # 填充 NaN 值
                                        target_df[col] = target_df[col].fillna('-')
                                
                                # 确保 notes 和 strategy 也填充默认值
                                if 'notes' not in target_df.columns:
                                    target_df['notes'] = '-'
                                else:
                                    target_df['notes'] = target_df['notes'].fillna('-')
                                
                                if 'strategy' not in target_df.columns:
                                    target_df['strategy'] = '-'
                                else:
                                    target_df['strategy'] = target_df['strategy'].fillna('-')
                                
                                # 2. 调用 AI (v3.0)
                                from ai_assistant import generate_batch_review_v3
                                ai_key = st.session_state.get('ai_key', '')
                                ai_base_url = st.session_state.get('ai_base_url', 'https://api.deepseek.com')
                                
                                # 获取配置的模型名称 (v3.5)
                                curr_model = st.session_state.get('ai_model', 'deepseek-chat')
                                report_content = generate_batch_review_v3(
                                    ai_key, 
                                    ai_base_url, 
                                    target_df,
                                    st.session_state.get('system_manifesto', ''),  # 传入宪法
                                    report_mode,
                                    curr_model  # 传入模型名称
                                )
                                
                                # 3. 保存报告
                                if "失败" not in report_content and "数据不足" not in report_content:
                                    # 计算统计数据
                                    t_count = len(target_df)
                                    t_pnl = target_df['net_pnl'].sum() if not target_df.empty else 0
                                    t_win_count = len(target_df[target_df['net_pnl'] > 0]) if not target_df.empty else 0
                                    t_win = (t_win_count / t_count * 100) if t_count > 0 else 0
                                    
                                    start_date = str(target_df.iloc[-1]['close_date_str']) if not target_df.empty else ""
                                    end_date = str(target_df.iloc[0]['close_date_str']) if not target_df.empty else ""
                                    
                                    engine.save_ai_report(
                                        report_mode, 
                                        start_date,
                                        end_date,
                                        t_count, t_pnl, t_win, report_content, selected_key
                                    )
                                    st.success("诊断完成！报告已归档。")
                                    time.sleep(1)
                                    st.rerun()
                                else:
                                    st.error(report_content)
                    
                    st.markdown("---")
                    st.markdown("**📜 历史报告档案**")
                    # 加载历史报告
                    if selected_key:
                        history_reports = engine.get_ai_reports(selected_key)
                        if not history_reports.empty:
                            for _, r in history_reports.iterrows():
                                # 格式化时间戳
                                r_date = datetime.fromtimestamp(r['created_at']/1000).strftime('%m-%d %H:%M')
                                if st.button(f"📄 {r_date} ({r['report_type']})", key=f"hist_{r['id']}", use_container_width=True):
                                    st.session_state['current_report'] = r['ai_feedback']
                        else:
                            st.caption("暂无历史报告")
                    else:
                        st.caption("请先选择账户")
                
                with col_r2:
                    # 显示报告内容
                    if 'current_report' in st.session_state:
                        st.markdown(st.session_state['current_report'])
                    else:
                        # 显示最新的一份报告
                        if selected_key:
                            history_reports = engine.get_ai_reports(selected_key)
                            if not history_reports.empty:
                                st.markdown(history_reports.iloc[0]['ai_feedback'])
                            else:
                                st.info("👈 请点击左侧按钮生成你的第一份诊断报告。")
                        else:
                            st.info("👈 请先选择账户并配置 AI API Key。")
            
            # === Tab 4: 策略库管理 (从侧边栏移到这里) ===
            with tab_strategy:
                st.subheader("📚 策略库管理 (Strategy Library)")
                st.caption("定义你的每一招，AI 会检查你是否动作变形。")
                
                all_strategies = engine.get_all_strategies()
                strategy_names = list(all_strategies.keys()) if all_strategies else []
                
                col_st1, col_st2 = st.columns([1, 1])
                
                with col_st1:
                    st.markdown("##### ➕ 新建策略")
                    new_strat_name = st.text_input("策略名称", placeholder="例如：超跌反弹", key="new_strat_name_main")
                    new_strat_desc = st.text_area("策略军规 (AI 审核依据)", placeholder="1. 必须偏离均线过远...\n2. 必须出现背离...", height=150, key="new_strat_desc_main")
                    if st.button("添加策略", key="add_strat_main"):
                        if new_strat_name and new_strat_desc:
                            ok, msg = engine.save_strategy(new_strat_name, new_strat_desc)
                            if ok: 
                                st.success(msg)
                                time.sleep(0.5)
                                st.rerun()
                        else:
                            st.error("请填写完整")
                
                with col_st2:
                    st.markdown("##### ✏️ 编辑现有策略")
                    if strategy_names:
                        edit_target = st.selectbox("选择策略", strategy_names, key="edit_target_main")
                        edit_desc_input = st.text_area("编辑规则", value=all_strategies[edit_target], height=150, key="edit_strat_desc_main")
                        
                        btn_col1, btn_col2 = st.columns(2)
                        with btn_col1:
                            if st.button("保存修改", key="save_strat_btn_main", use_container_width=True):
                                engine.save_strategy(edit_target, edit_desc_input)
                                st.success("已更新")
                                time.sleep(0.5)
                                st.rerun()
                        with btn_col2:
                            if st.button("删除策略", key="del_strat_btn_main", use_container_width=True):
                                engine.delete_strategy(edit_target)
                                st.success("已删除")
                                time.sleep(0.5)
                                st.rerun()
                    else:
                        st.info("暂无策略，请在左侧创建第一个策略")
            
# === Tab 5: 蒙特卡洛模拟 (v5.1 交互增强版) ===
            with tab_risk:
                st.subheader("🎲 蒙特卡洛模拟 (Monte Carlo Simulation)")
                st.caption("基于你的历史表现，模拟未来 1000 种可能的结局。")
                
                if len(rounds_df) < 10:
                    st.warning(f"⚠️ 数据量不足：当前只有 {len(rounds_df)} 笔交易，至少需要 10 笔才能进行有效模拟。")
                else:
                    # --- 参数设置区域 (双向同步逻辑) ---
                    
                    # 1. 初始化 Session State (如果还没存过)
                    if 'mc_sim_runs' not in st.session_state: st.session_state.mc_sim_runs = 100
                    if 'mc_sim_trades' not in st.session_state: st.session_state.mc_sim_trades = 50

                    # 2. 定义回调函数 (同步滑块和输入框)
                    def sync_runs_slider(): st.session_state.mc_sim_runs = st.session_state.slider_runs
                    def sync_runs_input(): st.session_state.mc_sim_runs = st.session_state.input_runs
                    def sync_trades_slider(): st.session_state.mc_sim_trades = st.session_state.slider_trades
                    def sync_trades_input(): st.session_state.mc_sim_trades = st.session_state.input_trades

                    col_p1, col_p2, col_p3 = st.columns(3)
                    
                    with col_p1:
                        sim_start_equity = st.number_input("初始模拟资金 ($)", value=10000.0, step=1000.0)
                    
                    with col_p2:
                        st.markdown("**模拟次数 (平行宇宙)**")
                        # 滑块 (Key: slider_runs)
                        st.slider(
                            "Runs Slider", 50, 1000, 
                            value=st.session_state.mc_sim_runs, 
                            key='slider_runs', on_change=sync_runs_slider, 
                            label_visibility="collapsed"
                        )
                        # 输入框 (Key: input_runs)
                        st.number_input(
                            "Runs Input", 50, 1000, 
                            value=st.session_state.mc_sim_runs, 
                            key='input_runs', on_change=sync_runs_input, 
                            label_visibility="collapsed"
                        )

                    with col_p3:
                        st.markdown("**未来交易笔数**")
                        # 滑块 (Key: slider_trades) - 上限改为 10000
                        st.slider(
                            "Trades Slider", 10, 10000, 
                            value=st.session_state.mc_sim_trades, 
                            key='slider_trades', on_change=sync_trades_slider,
                            label_visibility="collapsed"
                        )
                        # 输入框 (Key: input_trades)
                        st.number_input(
                            "Trades Input", 10, 10000, 
                            value=st.session_state.mc_sim_trades, 
                            key='input_trades', on_change=sync_trades_input,
                            label_visibility="collapsed"
                        )
                    
                    # 使用 session_state 里的最新值进行模拟
                    if st.button("🎰 开始模拟未来", use_container_width=True, type="primary"):
                        mc_engine = MonteCarloEngine(rounds_df)
                        
                        # 获取同步后的值
                        final_runs = st.session_state.mc_sim_runs
                        final_trades = st.session_state.mc_sim_trades
                        
                        with st.spinner(f"正在模拟 {final_runs} 个平行宇宙，每个宇宙交易 {final_trades} 笔..."):
                            res, msg = mc_engine.run_simulation(sim_start_equity, final_runs, final_trades)
                            
                        if res:
                            # --- 1. 核心指标卡片 ---
                            st.markdown("### 🔮 预言结果")
                            m1, m2, m3, m4 = st.columns(4)
                            
                            m1.metric("🔥 破产概率 (Risk of Ruin)", f"{res['risk_of_ruin']:.1f}%", 
                                      help="未来这几笔交易中，账户归零的概率")
                            
                            m2.metric("📉 预期最大回撤", f"{res['avg_max_dd']:.1f}%", 
                                      help="平均情况下的最大资金回撤幅度")
                            
                            profit_exp = res['median_final'] - sim_start_equity
                            m3.metric("💰 预期收益 (中位数)", f"${profit_exp:,.0f}", 
                                      delta_color="normal" if profit_exp > 0 else "inverse")
                            
                            m4.metric("🤕 最坏情况 (95%置信)", f"${res['worst_case']:,.0f}", 
                                      help="在最倒霉的5%的情况下，你的资金余额")

                            # --- 2. 意大利面图 (Spaghetti Chart) ---
                            st.markdown("---")
                            st.markdown("**📈 资金曲线分布图**")
                            
                            # 准备 Plotly 数据
                            # 为了性能，如果模拟次数太多，只画前 100 条线
                            display_lines = 100 if final_runs > 100 else final_runs
                            plot_lines = res['equity_curves'][:display_lines] 
                            
                            import plotly.graph_objects as go
                            
                            fig_mc = go.Figure()
                            
                            # A. 绘制模拟线 (细线，半透明)
                            x_axis = list(range(1, res['trades_per_run'] + 1))
                            for line in plot_lines:
                                fig_mc.add_trace(go.Scatter(
                                    x=x_axis, y=line,
                                    mode='lines',
                                    line=dict(color='rgba(100, 100, 100, 0.1)', width=1),
                                    showlegend=False,
                                    hoverinfo='skip'
                                ))
                            
                            # B. 绘制平均线 (亮色，粗线)
                            avg_line = np.mean(res['equity_curves'], axis=0)
                            fig_mc.add_trace(go.Scatter(
                                x=x_axis, y=avg_line,
                                mode='lines',
                                name='平均预期',
                                line=dict(color='#2196F3', width=3)
                            ))
                            
                            # C. 绘制起始资金线
                            fig_mc.add_hline(y=sim_start_equity, line_dash="dash", line_color="white", annotation_text="本金线")
                            
                            fig_mc.update_layout(
                                title=f"未来 {final_trades} 笔交易的资金演变 (展示前 {display_lines}/{final_runs} 条路径)",
                                xaxis_title="交易笔数",
                                yaxis_title="账户资金",
                                plot_bgcolor='#1E1E1E', 
                                paper_bgcolor='#1E1E1E', 
                                font=dict(color='#E0E0E0'),
                                height=500
                            )
                            
                            st.plotly_chart(fig_mc, use_container_width=True)
                            
                            # --- 3. 导师点评 ---
                            st.info(f"💡 **风控导师点评**：如果你的破产率 > 0%，请立即缩小仓位！目前最坏的情况下，你的账户会变成 ${res['worst_case']:,.0f}。")
                            
                        else:
                            st.error(msg)
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