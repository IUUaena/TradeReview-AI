import streamlit as st
import pandas as pd
import numpy as np  # v5.0 新增：用于蒙特卡洛模拟
import time
import os
import sqlite3  # v7.0 新增：用于 K 线数据同步
import plotly.express as px
from data_engine import TradeDataEngine
from data_processor import process_trades_to_rounds, calc_price_action_stats # 引入核心逻辑
from word_exporter import create_word_report
from market_engine import MarketDataEngine
from ai_assistant import generate_batch_review, generate_batch_review_v3, audit_single_trade, review_potential_trade, analyze_live_positions
from risk_simulator import MonteCarloEngine  # v5.0 新增
from memory_engine import MemoryEngine  # v5.0 RAG 记忆系统
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

# 初始化记忆引擎 (放在这里保证全局只初始化一次)
if 'memory_engine' not in st.session_state:
    st.session_state.memory_engine = MemoryEngine()
memory_engine = st.session_state.memory_engine

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
        
        # === ⚙️ AI 模型配置 (v8.7 优选版) ===
        with st.sidebar.expander("⚙️ AI 模型配置", expanded=True):
            st.caption("选择 AI 分析引擎 (默认 DeepSeek)")
            
            # 1. 定义主流模型列表 (DeepSeek 优先)
            model_options = [
                "deepseek-chat",          # DeepSeek V3 (当前主流)
                "deepseek-reasoner",      # DeepSeek R1 (推理模型)
                "gemini-2.0-flash-exp",   # Google Gemini (需兼容接口)
                "gemini-1.5-pro",         # Google Gemini
                "gpt-4o",                 # OpenAI 旗舰
                "gpt-4-turbo",            # OpenAI 稳定版
                "gpt-3.5-turbo",          # OpenAI 性价比
                "自定义 (Custom)"          # 手动输入入口
            ]
            
            # 2. 状态管理：初始化选中项
            current_model = st.session_state.get('user_ai_model', 'deepseek-chat')
            
            # 确定下拉框的默认 index
            if current_model in model_options:
                default_index = model_options.index(current_model)
            else:
                default_index = len(model_options) - 1 # 选"自定义"
                
            # 3. 下拉选择框
            selected_option = st.selectbox(
                "选择模型",
                options=model_options,
                index=default_index,
                key="model_selectbox"
            )
            
            # 4. 逻辑判断
            if selected_option == "自定义 (Custom)":
                # 如果选了自定义，显示输入框，并填入当前存的值
                custom_model = st.text_input(
                    "请输入模型名称", 
                    value=current_model if current_model not in model_options else "",
                    placeholder="例如: claude-3-5-sonnet",
                    help="请输入你的 API 提供商支持的确切模型名称"
                )
                if custom_model:
                    st.session_state.user_ai_model = custom_model
            else:
                st.session_state.user_ai_model = selected_option
                
            st.caption(f"✅ 当前生效: `{st.session_state.user_ai_model}`")
        
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
        
        # --- C2. 市场数据同步 (v7.0 新增) ---
        with st.expander("📚 市场数据同步 (K线)"):
            st.caption("下载 K 线到本地仓库，用于计算 ATR 和 痛苦时长(MAD)。")
            
            # 选项：同步天数
            sync_days = st.selectbox("回溯时间", [365, 90, 30], format_func=lambda x: f"最近 {x} 天")
            
            if st.button("🚀 一键同步 K 线", use_container_width=True, type="primary"):
                # 1. 初始化引擎
                if 'market_engine' not in st.session_state:
                    st.session_state.market_engine = MarketDataEngine()
                me = st.session_state.market_engine
                
                # 2. 找出需要同步的币种 (从交易记录中提取)
                status_box = st.status("正在分析交易记录...", expanded=True)
                
                try:
                    # 连接数据库读取交易过的 symbol
                    db_path = engine.db_path
                    conn = sqlite3.connect(db_path)
                    c = conn.cursor()
                    c.execute("SELECT DISTINCT symbol FROM trades")
                    rows = c.fetchall()
                    conn.close()
                    
                    # 清洗币种列表
                    target_coins = set()
                    for r in rows:
                        raw = r[0]
                        # 移除可能的后缀 (如 :USDT) 并确保格式为 BASE/QUOTE
                        clean = raw.split(':')[0]
                        if "USDT" in clean and "/" not in clean:
                            clean = clean.replace("USDT", "/USDT")
                        target_coins.add(clean)
                    
                    # 加上 BTC 和 ETH
                    target_coins.add("BTC/USDT")
                    target_coins.add("ETH/USDT")
                    
                    target_list = sorted(list(target_coins))
                    total_coins = len(target_list)
                    
                    status_box.write(f"📋 发现 {total_coins} 个关注币种，准备同步...")
                    progress_bar = status_box.progress(0)
                    
                    # 3. 循环同步
                    success_count = 0
                    for i, symbol in enumerate(target_list):
                        status_box.write(f"🔄 [{i+1}/{total_coins}] 正在同步 {symbol}...")
                        
                        # 定义回调更新进度
                        def sync_callback(msg, pct):
                            # 这里不更新主进度条，以免闪烁，只在后台打印或忽略
                            pass
                            
                        ok, msg = me.sync_symbol_history(symbol, timeframe='1m', days=sync_days)
                        
                        if ok:
                            success_count += 1
                        else:
                            st.toast(f"⚠️ {symbol} 同步失败: {msg}")
                            
                        # 更新总进度
                        progress_bar.progress((i + 1) / total_coins)
                    
                    status_box.update(label=f"✅ 同步完成！成功更新 {success_count}/{total_coins} 个币种", state="complete", expanded=False)
                    st.success("本地数据仓库已更新，现在可以进行极速复盘了！")
                    time.sleep(2)
                    st.rerun()
                    
                except Exception as e:
                    status_box.update(label="❌ 发生错误", state="error")
                    st.error(f"同步流程出错: {str(e)}")
        
        # --- C. Word 导出功能 (新增) ---
        # --- C. Word 导出功能 (v3.7 双模式) ---
        with st.expander("📄 导出 Word 报告"):
            st.caption("将交易记录导出为 Docx 文档，支持打印或分享。")
            
            # v7.0 新增：模式选择
            report_mode = st.radio(
                "报告模式", 
                ["完整版 (含 AI 点评)", "纯净版 (仅原始数据)"],
                help="纯净版不包含 AI 的分析，适合将数据喂给其他 AI 模型进行二次诊断。"
            )
            
            # 映射布尔值
            include_ai_flag = True if "完整版" in report_mode else False
            
            if st.button("生成 Word 文档", use_container_width=True):
                if selected_key:
                    try:
                        # 1. 获取最新数据 (带 v7.0 指标)
                        # 先加载原始数据
                        raw_df = engine.load_trades(selected_key)
                        
                        if raw_df.empty:
                            st.error("没有交易记录可导出！")
                        else:
                            # 处理数据：合成回合
                            df_export = process_trades_to_rounds(raw_df)
                            
                            if df_export.empty:
                                st.error("❌ 没有完整的交易记录可导出。")
                            else:
                                # 2. 调用导出函数
                                # 临时文件名
                                from datetime import datetime
                                temp_filename = f"TradeReview_Report_v7_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
                                
                                # 引用 word_exporter (确保已 import)
                                with st.spinner("正在生成文档..."):
                                    create_word_report(df_export, temp_filename, include_ai=include_ai_flag)
                                
                                # 3. 提供下载按钮
                                if os.path.exists(temp_filename):
                                    with open(temp_filename, "rb") as file:
                                        btn = st.download_button(
                                            label="📥 点击下载 .docx",
                                            data=file,
                                            file_name=f"复盘报告_{datetime.now().strftime('%Y%m%d')}_{'Full' if include_ai_flag else 'Raw'}.docx",
                                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                            use_container_width=True
                                        )
                                    st.success(f"✅ 报告生成成功！({report_mode})")
                                    
                                    # 显示文件路径
                                    abs_file_path = os.path.abspath(temp_filename)
                                    st.info(f"📁 文件位置: {abs_file_path}")
                                else:
                                    st.error("文件生成失败，请检查权限。")
                    except Exception as e:
                        st.error(f"导出失败: {e}")
                        import traceback
                        st.code(traceback.format_exc())
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
            # ==============================================================================
            # 00. v6.0 实时战场 (Live Cockpit) - 放在最顶端
            # ==============================================================================
            with st.expander("📡 实时战场 (Live Positions & Risk)", expanded=False):
                if not selected_key:
                    st.info("👈 请先在左侧选择账户以查看实时持仓。")
                else:
                    col_live_btn, col_live_info = st.columns([1, 4])
                    
                    with col_live_btn:
                        if st.button("🔄 刷新实时数据", use_container_width=True, type="primary"):
                            st.session_state.need_live_refresh = True
                    
                    # 获取数据 (为了不拖慢页面，只在点击刷新或首次加载时获取)
                    if 'live_data' not in st.session_state or st.session_state.get('need_live_refresh', False):
                        with st.spinner("正在连接交易所获取最新行情..."):
                            live_res, live_msg = engine.get_open_positions(selected_key, selected_secret)
                            if live_res:
                                st.session_state.live_data = live_res
                                st.session_state.live_update_time = datetime.now().strftime("%H:%M:%S")
                            else:
                                st.error(live_msg)
                            st.session_state.need_live_refresh = False
                    
                    # 显示数据
                    if 'live_data' in st.session_state and st.session_state.live_data:
                        data = st.session_state.live_data
                        positions = data['positions']
                        equity = data['equity']
                        
                        # A. 账户概览
                        with col_live_info:
                            st.caption(f"上次更新: {st.session_state.live_update_time}")
                        
                        l1, l2, l3 = st.columns(3)
                        l1.metric("账户净值 (Equity)", f"${equity:,.2f}")
                        
                        total_unrealized = sum([p['pnl'] for p in positions])
                        l2.metric("当前浮动盈亏", f"${total_unrealized:,.2f}", 
                                  delta_color="normal" if total_unrealized >= 0 else "inverse")
                        
                        position_count = len(positions)
                        l3.metric("持仓数量", f"{position_count} 个")
                        
                        st.markdown("---")
                        
                        # B. 持仓详情卡片
                        if positions:
                            for p in positions:
                                # 颜色定义
                                card_color = "rgba(76, 175, 80, 0.1)" if p['pnl'] >= 0 else "rgba(255, 82, 82, 0.1)"
                                pnl_color = "green" if p['pnl'] >= 0 else "red"
                                side_icon = "🟢" if "LONG" in p['side'] else "🔴"
                                
                                st.markdown(f"""
                                <div style="background-color: {card_color}; padding: 15px; border-radius: 10px; margin-bottom: 10px; border: 1px solid #444;">
                                    <div style="display: flex; justify-content: space-between; align-items: center;">
                                        <div>
                                            <span style="font-size: 18px; font-weight: bold;">{side_icon} {p['symbol']}</span>
                                            <span style="background: #333; padding: 2px 6px; border-radius: 4px; font-size: 12px; margin-left: 8px;">{p['side']} x{p['leverage']}</span>
                                        </div>
                                        <div style="text-align: right;">
                                            <div style="font-size: 20px; font-weight: bold; color: {pnl_color};">${p['pnl']:.2f}</div>
                                            <div style="font-size: 12px; color: #888;">{p['roi']:.2f}%</div>
                                        </div>
                                    </div>
                                    <div style="margin-top: 8px; font-size: 13px; color: #ccc; display: flex; justify-content: space-between;">
                                        <span>开仓: {p['entry_price']} ➝ 现价: {p['mark_price']}</span>
                                        <span>强平: <span style="color: #FF5252;">{p['liquidation_price']}</span></span>
                                    </div>
                                </div>
                                """, unsafe_allow_html=True)
                            
                            # C. AI 实时战术顾问
                            st.markdown("##### 🧠 AI 战术顾问")
                            if st.button("🆘 分析当前持仓风险", use_container_width=True):
                                if 'ai_key' not in st.session_state or not st.session_state['ai_key']:
                                    st.error("请配置 AI Key")
                                else:
                                    with st.spinner("🧠 AI 正在对比历史持仓风险..."):
                                        from ai_assistant import analyze_live_positions
                                        
                                        # 1. 检索记忆：查询 "持仓风险 浮亏" 相关的记忆
                                        # 也可以提取当前持仓的币种作为关键词
                                        symbols = [p['symbol'] for p in positions]
                                        query = f"持仓风险 {' '.join(symbols)} 处理浮亏"
                                        memories = memory_engine.retrieve_similar_memories(query, n_results=3)
                                        
                                        # 2. 调用 AI
                                        advice = analyze_live_positions(
                                            st.session_state['ai_key'],
                                            st.session_state['ai_base_url'],
                                            data,
                                            st.session_state.get('system_manifesto', ''),
                                            st.session_state.get('ai_model', 'deepseek-chat'),
                                            related_memories=memories  # v5.0 RAG 记忆系统
                                        )
                                        st.info(advice)
                        else:
                            st.success("✅ 当前空仓 (Flat)。好好休息，等待机会。")
            
            st.markdown("---")
            
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
                                    with st.spinner("🧠 AI 正在检索历史血泪史..."):
                                        # 1. 检索记忆：用 "计划做多/空 币种" 作为查询词
                                        direction_str = "做多" if sb_entry > sb_sl else "做空"
                                        query = f"计划交易 {sb_symbol} {direction_str}"
                                        memories = memory_engine.retrieve_similar_memories(query, n_results=3)
                                        
                                        # 2. 调用 AI
                                        plan_data = {
                                            "symbol": sb_symbol,
                                            "entry": sb_entry,
                                            "sl": sb_sl,
                                            "tp": sb_tp,
                                            "risk_money": sb_risk
                                        }
                                        manifesto = st.session_state.get('system_manifesto', '')
                                        curr_model = st.session_state.get('ai_model', 'deepseek-chat')
                                        
                                        res = review_potential_trade(
                                            st.session_state['ai_key'],
                                            st.session_state['ai_base_url'],
                                            plan_data,
                                            manifesto,
                                            curr_model,
                                            related_memories=memories  # v5.0 RAG 记忆系统
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
            
            # === 🆕 V6.0 新增：计算优势比率 (E-Ratio) ===
            # E-Ratio = 平均 MFE / |平均 MAE|
            # 衡量捕捉趋势的能力 vs 承受痛苦的程度
            e_ratio_display = "N/A"
            if 'mfe' in rounds_df.columns and 'mae' in rounds_df.columns:
                # 过滤掉没有数据的记录 (0 或 NaN)
                valid_pa = rounds_df[(rounds_df['mfe'] != 0) & (rounds_df['mae'] != 0)]
                # 进一步过滤 NaN 值
                valid_pa = valid_pa[valid_pa['mfe'].notna() & valid_pa['mae'].notna()]
                if not valid_pa.empty:
                    avg_mfe = valid_pa['mfe'].mean()
                    avg_mae = abs(valid_pa['mae'].mean())
                    
                    if avg_mae > 0:
                        e_ratio = avg_mfe / avg_mae
                        # 颜色逻辑：>1.0 为健康(绿)，<1.0 为亚健康(红)
                        e_color = "green" if e_ratio >= 1.0 else "red"
                        e_ratio_display = f":{e_color}[{e_ratio:.2f}]"
            # ===========================================
            
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
                # 把列分为 胜率 | 盈亏比 | 优势比
                c2a, c2b, c2c = st.columns(3)
                with c2a:
                    st.markdown(f"""
                    <div class="ios-stat-card">
                        <div class="ios-label">Win Rate (胜率)</div>
                        <div class="ios-value">{win_rate}%</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with c2b:
                    st.markdown(f"""
                    <div class="ios-stat-card">
                        <div class="ios-label">Avg R:R (盈亏比)</div>
                        <div class="ios-value">{rr_ratio}</div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                with c2c:  # 新增卡片
                    st.markdown(f"""
                    <div class="ios-stat-card" title="优势比率 = Avg MFE / Avg MAE。大于 1.0 代表系统健康">
                        <div class="ios-label">E-Ratio (优势)</div>
                        <div class="ios-value">{e_ratio_display}</div>
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
                    
                    # 从数据库重新读取最新数据 (确保实时性，价格行为分析需要用到)
                    trade_row = raw_df[raw_df['id'] == trade['round_id']].iloc[0]
                    
                    # ==================================================================
                    # 🔬 价格行为透视 (v7.0 Local Warehouse & ATR)
                    # ==================================================================
                    # 🔬 Price Action (v8.2 Pro: Price + Volume + Structure + Pattern)
                    # ==================================================================
                    st.divider()
                    st.markdown("### 🔬 Price Action (v8.2 Pro)")
                    
                    has_pa_data = False
                    raw_mae = trade_row.get('mae')
                    if raw_mae is not None and str(raw_mae) != 'nan':
                        has_pa_data = True
                    
                    pa_col_input, pa_col_btn = st.columns([2, 2])
                    with pa_col_input:
                        risk_input = st.number_input("📉 单笔风险 ($ Risk)", value=100.0, step=10.0, key=f"risk_{trade['round_id']}")
                    
                    with pa_col_btn:
                        st.markdown("<br>", unsafe_allow_html=True)
                        btn_label = "🚀 计算 v7.0 指标" if has_pa_data else "🚀 还原过程 (本地极速版)"
                        if st.button(btn_label, key=f"btn_pa_{trade['round_id']}"):
                            st.session_state[f"show_pa_{trade['round_id']}"] = True
                    
                    # === 核心逻辑块 ===
                    if st.session_state.get(f"show_pa_{trade['round_id']}", False) or has_pa_data:
                        
                        # 1. 计算逻辑 (Calculation)
                        if st.session_state.get(f"show_pa_{trade['round_id']}", False):
                            if 'market_engine' not in st.session_state:
                                st.session_state.market_engine = MarketDataEngine()
                            
                            me = st.session_state.market_engine
                            
                            # 清洗 Symbol
                            raw_symbol = trade['symbol']
                            clean_symbol = raw_symbol.split(':')[0] 
                            if "USDT" in clean_symbol and "/" not in clean_symbol:
                                clean_symbol = clean_symbol.replace("USDT", "/USDT")
                            
                            entry_price = float(trade_row['price'])
                            amount = float(trade_row.get('amount', 0) or trade.get('amount', 0) or 0)
                            
                            if entry_price <= 0 or amount <= 0:
                                st.error("❌ 价格或数量无效，请先编辑交易。")
                            else:
                                with st.spinner("📦 正在从本地仓库调取数据..."):
                                    query_start = trade['open_time'] - (200 * 60 * 1000) 
                                    query_end = trade['close_time']
                                    
                                    candles = me.get_klines_df(clean_symbol, query_start, query_end)
                                    
                                    if not candles.empty:
                                        # 计算指标
                                        exit_price = candles.iloc[-1]['close']
                                        stats = calc_price_action_stats(
                                            candles, trade['direction'], entry_price, exit_price,
                                            trade['open_time'], trade['close_time'], 
                                            amount, risk_input
                                        )
                                        
                                        if stats:
                                            # 保存数据 (v8.2 全字段)
                                            save_data = {
                                                'mae': float(stats['MAE']),
                                                'mfe': float(stats['MFE']),
                                                'etd': float(stats['ETD']),
                                                'mad': int(stats['MAD']),
                                                'efficiency': float(stats['Efficiency']),
                                                'mae_atr': float(stats['MAE_ATR']),
                                                'mfe_atr': float(stats['MFE_ATR']),
                                                'rvol': float(stats['RVOL']),
                                                'pattern_signal': stats['Pattern'],
                                                # structure_info 暂时不存库或根据需要存
                                            }
                                            base_id = trade['round_id'].replace('_OPEN', '').replace('_CLOSE', '')
                                            success, save_msg = engine.update_trade_extended(base_id, selected_key, save_data)
                                            
                                            st.session_state[f"v7_stats_{trade['round_id']}"] = stats
                                            
                                            if success:
                                                st.success("✅ 计算完成！")
                                                st.session_state[f"show_pa_{trade['round_id']}"] = False 
                                                if 'trades_df' in st.session_state: del st.session_state['trades_df']
                                                time.sleep(0.5)
                                                st.rerun()
                                    else:
                                        st.error(f"❌ 本地仓库没有 {clean_symbol} 的数据。请点击侧边栏的【一键同步 K 线】！")
                        
                        # 2. 展示逻辑 (Display)
                        v7_stats = st.session_state.get(f"v7_stats_{trade['round_id']}")
                        
                        # --- 修复点：这里是之前报错的地方，确保缩进与上面的 if 对齐 ---
                        curr_mae = float(trade_row.get('mae', 0))
                        curr_mfe = float(trade_row.get('mfe', 0))
                        curr_etd = float(trade_row.get('etd', 0))
                        
                        # 第一行：基础 R 倍数
                        m1, m2, m3 = st.columns(3)
                        m1.metric("💔 MAE (最大浮亏)", f"{curr_mae:.2f} R")
                        m2.metric("💰 MFE (最大浮盈)", f"{curr_mfe:.2f} R")
                        m3.metric("📉 ETD (利润回撤)", f"{curr_etd:.2f} R")
                        
                        # 第二行：v7.0/v8.0 高级指标
                        if v7_stats or has_pa_data:
                            st.caption("🧠 心理/效率/热度 (v8.2 Pro)")
                            p1, p2, p3 = st.columns(3)
                            
                            # 从 stats 或 row 读取
                            val_mad = v7_stats.get('MAD') if v7_stats else trade_row.get('mad')
                            val_eff = v7_stats.get('Efficiency') if v7_stats else trade_row.get('efficiency')
                            val_atr = v7_stats.get('MAE_ATR') if v7_stats else trade_row.get('mae_atr')
                            
                            p1.metric("⏳ MAD (痛苦时长)", f"{val_mad} min" if val_mad else "N/A")
                            p2.metric("🎯 交易效率", f"{float(val_eff):.2f}" if val_eff else "N/A")
                            p3.metric("🌊 MAE (ATR)", f"{float(val_atr):.1f} x" if val_atr else "N/A")
                            
                            # 第三行：成交量 & 形态
                            val_rvol = v7_stats.get('RVOL') if v7_stats else trade_row.get('rvol')
                            val_pat = v7_stats.get('Pattern') if v7_stats else trade_row.get('pattern_signal')
                            val_struct = v7_stats.get('Structure') if v7_stats else trade_row.get('structure_info')
                            c_vol, c_pat, c_str = st.columns(3)
                            c_vol.metric("📊 RVOL (热度)", f"{float(val_rvol):.2f}" if val_rvol else "N/A")
                            c_pat.info(f"信号: **{val_pat if val_pat else '无'}**")
                            
                            if val_struct:
                                if "⚠️" in str(val_struct): c_str.warning(f"结构: **{val_struct}**")
                                elif "✅" in str(val_struct): c_str.success(f"结构: **{val_struct}**")
                                else: c_str.info(f"结构: {val_struct}")
                            
                        # 3. 绘图逻辑 (Charts)
                        # ------------------------------------------------------
                        # 再次尝试获取 entry_price (防止绘图时丢失)
                        try:
                            entry_price = float(trade_row.get('price', 0))
                            if entry_price == 0: entry_price = float(trade.get('price', 0))
                        except:
                            entry_price = 0
                        chart_df = v7_stats.get('Charts')
                        
                        # 🟢 IF 语句开始
                        if chart_df is not None and not chart_df.empty and entry_price > 0:
                            from plotly.subplots import make_subplots
                            import plotly.graph_objects as go
                            
                            # 创建 2 行 1 列的子图
                            fig = make_subplots(
                                rows=2, cols=1, 
                                shared_xaxes=True, 
                                vertical_spacing=0.03,
                                row_heights=[0.7, 0.3]
                            )
                            
                            # --- 主图：K 线 ---
                            fig.add_trace(go.Candlestick(
                                x=chart_df['datetime'],
                                open=chart_df['open'], high=chart_df['high'],
                                low=chart_df['low'], close=chart_df['close'],
                                name='Price'
                            ), row=1, col=1)
                            
                            # 入场线
                            fig.add_hline(y=entry_price, line_dash="dash", line_color="yellow", row=1, col=1, annotation_text="Entry")
                            
                            # ATR 通道
                            first_row = chart_df.iloc[0]
                            entry_atr = first_row.get('atr', 0)
                            if pd.notna(entry_atr) and entry_atr > 0:
                                fig.add_hrect(
                                    y0=entry_price - entry_atr, y1=entry_price + entry_atr, 
                                    fillcolor="gray", opacity=0.15, line_width=0, row=1, col=1
                                )
                            
                            # --- 红点 (浮亏时刻) ---
                            if "Long" in trade['direction']:
                                pain_mask_strict = chart_df['close'] < entry_price
                            else:
                                pain_mask_strict = chart_df['close'] > entry_price
                                
                            pain_df = chart_df[pain_mask_strict]
                            if not pain_df.empty:
                                fig.add_trace(go.Scatter(
                                    x=pain_df['datetime'], y=pain_df['close'],
                                    mode='markers', 
                                    marker=dict(color='#FF5252', size=4, symbol='circle'),
                                    name='浮亏时刻'
                                ), row=1, col=1)
                            
                            # --- 副图：成交量 ---
                            colors = ['#26A69A' if c >= o else '#EF5350' for c, o in zip(chart_df['close'], chart_df['open'])]
                            fig.add_trace(go.Bar(
                                x=chart_df['datetime'],
                                y=chart_df['volume'],
                                marker_color=colors,
                                name='Volume'
                            ), row=2, col=1)
                            # --- 结构位标注 ---
                            res_price = v7_stats.get('Resistance')
                            sup_price = v7_stats.get('Support')
                            if res_price:
                                fig.add_hline(y=res_price, line_dash="dot", line_color="#EF5350", annotation_text="Res", row=1, col=1)
                            if sup_price:
                                fig.add_hline(y=sup_price, line_dash="dot", line_color="#00E676", annotation_text="Sup", row=1, col=1)
                            # --- 形态标注 ---
                            pattern_cols = ['CDL_ENGULFING', 'CDL_HAMMER', 'CDL_DOJI', 'CDL_STAR', 'CDL_SHOOTINGSTAR']
                            pat_map = {'CDL_ENGULFING':'吞没', 'CDL_HAMMER':'锤子', 'CDL_DOJI':'十字', 'CDL_STAR':'星', 'CDL_SHOOTINGSTAR':'流星'}
                            for col in pattern_cols:
                                if col in chart_df.columns:
                                    sig_df = chart_df[chart_df[col] != 0]
                                    for idx, row in sig_df.iterrows():
                                        pat_name = pat_map.get(col, col)
                                        y_pos = row['low'] if row[col] > 0 else row['high']
                                        color = '#00E676' if row[col] > 0 else '#FF5252'
                                        ay = 20 if row[col] > 0 else -20
                                        fig.add_annotation(x=row['datetime'], y=y_pos, text=pat_name, showarrow=True, arrowhead=1, arrowcolor=color, ax=0, ay=ay, font=dict(color=color, size=10), row=1, col=1)
                            # 布局
                            fig.update_layout(height=550, margin=dict(l=10, r=10, t=10, b=10), plot_bgcolor='#1E1E1E', paper_bgcolor='#1E1E1E', font=dict(color='#E0E0E0'), xaxis_rangeslider_visible=False, showlegend=False)
                            fig.update_xaxes(showticklabels=False, row=1, col=1)
                            fig.update_yaxes(gridcolor='#333', row=1, col=1)
                            fig.update_yaxes(gridcolor='#333', title="Vol", row=2, col=1)
                            
                            st.plotly_chart(fig, use_container_width=True)
                        
                        # 🟢 ELSE 语句 (必须与上面的 IF 垂直对齐)
                        else:
                            if entry_price <= 0:
                                st.warning("⚠️ 无法获取正确的入场价格，导致图表无法绘制。")
                        # ------------------------------------------------------
                                
                                # =================================================
                                # 🎥 沉浸式 K 线回放 (Cinema Mode v3.3 - Init Fix)
                                # =================================================
                                st.markdown("---")
                                with st.expander("🎥 沉浸式时光机 (K-Line Replay)", expanded=True):
                                    # --- 0. 状态隔离核心 (Namespace) ---
                                    tid = trade['round_id']
                                    k_active = f"rp_active_{tid}"  # 播放状态
                                    k_idx = f"rp_idx_{tid}"        # 数据指针
                                    k_slider = f"rp_slider_{tid}"  # 控件状态
                                    k_speed = f"rp_speed_{tid}"    # 速度设置
                                    
                                    # 获取入场价格（用于计算盈亏）
                                    entry_price = float(trade_row['price'])
                                    
                                    # 1. 准备数据
                                    replay_full_df = chart_df.reset_index(drop=True)
                                    total_frames = len(replay_full_df)
                                    
                                    if total_frames > 0:
                                        # 2. 初始化与同步 (核心修复区域)
                                        # ----------------------------------------------------
                                        # A. 初始化播放状态
                                        if k_active not in st.session_state:
                                            st.session_state[k_active] = False
                                        
                                        # B. 初始化数据指针
                                        if k_idx not in st.session_state:
                                            # 智能定位：尝试定位到开仓前 20 根
                                            default_start = 0
                                            try:
                                                start_match = replay_full_df[replay_full_df['timestamp'] >= trade['open_time']].index
                                                if len(start_match) > 0:
                                                    default_start = max(0, start_match[0] - 20)
                                            except:
                                                pass
                                            st.session_state[k_idx] = default_start
                                        
                                        # C. [修复关键点] 独立初始化滑块 Key
                                        # 无论 k_idx 是否已存在，都要确保 k_slider 存在
                                        if k_slider not in st.session_state:
                                            st.session_state[k_slider] = st.session_state[k_idx]
                                        
                                        # D. 强制同步 (Fix: StreamlitAPIException)
                                        # 确保滑块位置与后台数据指针一致 (用于自动播放时的 UI 刷新)
                                        if st.session_state[k_slider] != st.session_state[k_idx]:
                                            st.session_state[k_slider] = st.session_state[k_idx]
                                        # ----------------------------------------------------
                                        
                                        # 3. 播放器控制台
                                        c_play, c_step, c_reset, c_speed, c_slider = st.columns([1, 1, 1, 1.5, 5])
                                        
                                        with c_play:
                                            # 播放/暂停
                                            if st.session_state[k_active]:
                                                if st.button("⏸️ 暂停", key=f"btn_pause_{tid}", use_container_width=True):
                                                    st.session_state[k_active] = False
                                                    st.rerun()
                                            else:
                                                if st.button("▶️ 播放", key=f"btn_play_{tid}", use_container_width=True, type="primary"):
                                                    st.session_state[k_active] = True
                                                    st.rerun()
                                        
                                        with c_step:
                                            # 单步
                                            if st.button("⏩ 单步", key=f"btn_step_{tid}", use_container_width=True):
                                                st.session_state[k_active] = False
                                                if st.session_state[k_idx] < total_frames - 1:
                                                    st.session_state[k_idx] += 1
                                                    st.session_state[k_slider] = st.session_state[k_idx] # 同步
                                                    st.rerun()
                                        
                                        with c_reset:
                                            if st.button("⏹️ 重置", key=f"btn_reset_{tid}", use_container_width=True):
                                                st.session_state[k_active] = False
                                                try:
                                                    start_match = replay_full_df[replay_full_df['timestamp'] >= trade['open_time']].index
                                                    reset_val = max(0, start_match[0] - 20) if len(start_match) > 0 else 0
                                                except:
                                                    reset_val = 0
                                                
                                                st.session_state[k_idx] = reset_val
                                                st.session_state[k_slider] = reset_val
                                                st.rerun()
                                                
                                        with c_speed:
                                            speed_map = {"0.5x": 0.5, "1.0x": 0.2, "2.0x": 0.1, "5.0x": 0.01}
                                            sel_speed = st.selectbox("倍速", options=list(speed_map.keys()), index=2, label_visibility="collapsed", key=k_speed)
                                            current_speed = speed_map[sel_speed]
                                        
                                        with c_slider:
                                            def on_slider_change():
                                                # 用户拖动 -> 更新 idx -> 暂停播放
                                                st.session_state[k_idx] = st.session_state[k_slider]
                                                st.session_state[k_active] = False
                                                
                                            st.slider(
                                                "Timeline", 
                                                min_value=0, max_value=total_frames - 1,
                                                key=k_slider, # 绑定状态
                                                on_change=on_slider_change,
                                                label_visibility="collapsed"
                                            )
                                        
                                        # 4. 渲染画面
                                        curr_frame = max(5, st.session_state[k_idx] + 1)
                                        current_view_df = replay_full_df.iloc[:curr_frame].copy()
                                        last_bar = current_view_df.iloc[-1]
                                        
                                        # 数据计算
                                        cur_price = last_bar['close']
                                        cur_time_str = last_bar['datetime'].strftime('%m-%d %H:%M')
                                        if "Long" in trade['direction']:
                                            pnl_pct = (cur_price - plot_entry_price) / plot_entry_price * 100
                                        else:
                                            pnl_pct = (plot_entry_price - cur_price) / plot_entry_price * 100
                                        
                                        # HUD
                                        pnl_color = "#4CAF50" if pnl_pct > 0 else "#FF5252"
                                        bg_color = "rgba(76, 175, 80, 0.1)" if pnl_pct > 0 else "rgba(255, 82, 82, 0.1)"
                                        
                                        h1, h2, h3 = st.columns([2, 2, 4])
                                        h1.metric("⏱️ 回放时间", cur_time_str)
                                        h2.metric("💲 现价", f"{cur_price:.4f}")
                                        h3.markdown(f"""
                                        <div style="background:{bg_color}; border:1px solid {pnl_color}; border-radius:8px; padding:2px 10px; text-align:center;">
                                            <span style="color:#888; font-size:12px;">实时 ROI</span><br>
                                            <span style="color:{pnl_color}; font-size:20px; font-weight:bold;">{pnl_pct:+.2f}%</span>
                                        </div>
                                        """, unsafe_allow_html=True)
                                        
                                        # 绘图
                                        import plotly.graph_objects as go
                                        fig_rep = go.Figure()
                                        fig_rep.add_trace(go.Candlestick(
                                            x=current_view_df['datetime'],
                                            open=current_view_df['open'], high=current_view_df['high'],
                                            low=current_view_df['low'], close=current_view_df['close'],
                                            name='Price'
                                        ))
                                        fig_rep.add_hline(y=entry_price, line_dash="dash", line_color="yellow")
                                        
                                        y_min = replay_full_df['low'].min()
                                        y_max = replay_full_df['high'].max()
                                        pad = (y_max - y_min) * 0.1
                                        
                                        fig_rep.update_layout(
                                            height=450, margin=dict(t=10, b=10, l=10, r=10),
                                            plot_bgcolor='#1E1E1E', paper_bgcolor='#1E1E1E',
                                            font=dict(color='#E0E0E0'), xaxis_rangeslider_visible=False,
                                            showlegend=False,
                                            yaxis=dict(range=[y_min - pad, y_max + pad], side='right', gridcolor='#333'),
                                            xaxis=dict(showgrid=False)
                                        )
                                        st.plotly_chart(fig_rep, use_container_width=True)
                                        
                                        # 5. 自动播放引擎
                                        if st.session_state[k_active]:
                                            if st.session_state[k_idx] < total_frames - 1:
                                                time.sleep(current_speed)
                                                st.session_state[k_idx] += 1
                                                # 注意：这里不再直接修改 widget key (k_slider)，
                                                # 而是依赖下一轮循环顶部的 "强制同步" 逻辑 (D部分) 来处理
                                                st.rerun()
                                            else:
                                                st.session_state[k_active] = False
                                        
                            # =================================================
                            
                            # =================================================
                            # 🔮 功能设想二：卖飞模拟器 (What-If Analysis)
                            # =================================================
                            st.markdown("---")
                            with st.expander("🔮 卖飞模拟器 (上帝视角验收)", expanded=False):
                                st.caption("如果不平仓，死拿到底会怎样？让数据告诉你真相。")
                                
                                # 获取必要的变量（确保在作用域内）
                                whatif_entry_price = float(trade_row['price'])
                                whatif_amount = float(trade_row.get('amount', 0) or trade.get('amount', 0) or 0)
                                
                                # 1. 选择"后悔时间窗口"
                                col_time, col_res = st.columns([1, 3])
                                with col_time:
                                    hold_hours = st.selectbox(
                                        "假设多拿多久？", 
                                        options=[1, 4, 12, 24, 48], 
                                        format_func=lambda x: f"+ {x} 小时",
                                        index=1 # 默认看 4 小时
                                    )
                                
                                # 2. 获取平仓后的数据 (未来数据)
                                # 注意：需要重新查询数据库，获取 close_time 之后的数据
                                if 'market_engine' not in st.session_state:
                                    st.session_state.market_engine = MarketDataEngine()
                                me = st.session_state.market_engine
                                
                                # 计算未来时间段
                                future_start = trade['close_time']
                                future_end = future_start + (hold_hours * 60 * 60 * 1000)
                                
                                # 清洗 Symbol (防止带 :USDT 后缀查不到)
                                raw_symbol = trade['symbol']
                                clean_symbol = raw_symbol.split(':')[0] 
                                if "USDT" in clean_symbol and "/" not in clean_symbol:
                                    clean_symbol = clean_symbol.replace("USDT", "/USDT")
                                
                                with st.spinner("🔮 正在推演平行宇宙..."):
                                    future_df = me.get_klines_df(clean_symbol, future_start, future_end)
                                    
                                    if future_df.empty:
                                        st.warning("⚠️ 本地仓库没有这段未来的数据。可能是这笔交易刚发生不久，或者你需要重新【一键同步 K 线】。")
                                    else:
                                        # 3. 计算"如果多拿"的结果
                                        # 获取实际平仓价（持仓期间最后一根 K 线的收盘价）
                                        if not chart_df.empty:
                                            exit_price = float(chart_df.iloc[-1]['close'])
                                        else:
                                            exit_price = float(trade_row.get('price', 0))
                                            if exit_price == 0: 
                                                exit_price = future_df.iloc[0]['open'] # 容错
                                        
                                        # 获取这段时间的最高/最低价
                                        future_high = future_df['high'].max()
                                        future_low = future_df['low'].min()
                                        future_close = future_df.iloc[-1]['close']
                                        
                                        # 计算潜在最大利润 (Perfect Play) 和 潜在最大回撤 (Worst Pain)
                                        if "Long" in trade['direction']:
                                            # 做多
                                            potential_best = future_high
                                            potential_worst = future_low
                                            actual_diff = exit_price - whatif_entry_price
                                            best_diff = potential_best - whatif_entry_price
                                            held_diff = future_close - whatif_entry_price
                                            
                                            # 卖飞了吗？(如果最高价 > 平仓价 1% 以上)
                                            is_sold_early = potential_best > (exit_price * 1.01)
                                            # 逃顶了吗？(如果后续收盘价 < 平仓价)
                                            is_good_exit = future_close < exit_price
                                            
                                        else:
                                            # 做空
                                            potential_best = future_low
                                            potential_worst = future_high
                                            actual_diff = whatif_entry_price - exit_price
                                            best_diff = whatif_entry_price - potential_best
                                            held_diff = whatif_entry_price - future_close
                                            
                                            is_sold_early = potential_best < (exit_price * 0.99)
                                            is_good_exit = future_close > exit_price
                                        
                                        # 4. 生成 AI 判词
                                        with col_res:
                                            if is_good_exit and not is_sold_early:
                                                st.success(f"🏆 **神级逃顶！**\n\n在你走后，价格向不利方向运行。如果你死拿 {hold_hours} 小时，你的利润将**缩水 ${(actual_diff - held_diff) * whatif_amount:.2f}**。这一跑，跑得漂亮！")
                                            elif is_sold_early:
                                                missed_money = (best_diff - actual_diff) * whatif_amount
                                                st.error(f"🍖 **严重卖飞！**\n\n在你走后，行情继续爆发。如果你能多拿一会儿，最高可以**多赚 ${missed_money:.2f}**！\n\n(最高价触及 {potential_best:.4f})")
                                            else:
                                                st.info(f"😐 **平平无奇**\n\n在你走后 {hold_hours} 小时内，价格仅仅是横盘震荡，没有太大的惊喜或惊吓。平仓没毛病。")
                                        
                                        # 5. 可视化对比图
                                        # 画出：你的持仓段 (实线) + 未来段 (虚线)
                                        import plotly.graph_objects as go
                                        
                                        # 合并数据用于画图 (为了连接，取持仓的最后几根 + 未来所有)
                                        tail_count = min(20, len(chart_df)) # 确保不超过实际数据量
                                        past_tail = chart_df.tail(tail_count) if tail_count > 0 else chart_df
                                        
                                        fig_whatif = go.Figure()
                                        
                                        # A. 过去 (实心蜡烛)
                                        fig_whatif.add_trace(go.Candlestick(
                                            x=past_tail['datetime'],
                                            open=past_tail['open'], high=past_tail['high'],
                                            low=past_tail['low'], close=past_tail['close'],
                                            name='实际持仓',
                                            increasing_line_color='#26A69A', decreasing_line_color='#EF5350'
                                        ))
                                        
                                        # B. 未来 (空心/透明蜡烛，表示"平行宇宙")
                                        fig_whatif.add_trace(go.Candlestick(
                                            x=future_df['datetime'],
                                            open=future_df['open'], high=future_df['high'],
                                            low=future_df['low'], close=future_df['close'],
                                            name=f'未来 {hold_hours}H',
                                            increasing_line_color='rgba(38, 166, 154, 0.5)', 
                                            decreasing_line_color='rgba(239, 83, 80, 0.5)'
                                        ))
                                        
                                        # 标记你的平仓点 (Fix: 直接使用整数时间戳，避开 Pandas 2.0 运算错误)
                                        fig_whatif.add_vline(
                                            x=trade['close_time'],  # 👈 直接使用整数时间戳
                                            line_dash="dash", 
                                            line_color="yellow", 
                                            annotation_text="你的平仓点"
                                        )
                                        
                                        # 标记未来最高点 (如果是卖飞)
                                        if is_sold_early:
                                            # 找到最高点的时间
                                            if "Long" in trade['direction']:
                                                peak_time = future_df.loc[future_df['high'].idxmax()]['datetime']
                                                peak_price = future_high
                                            else:
                                                peak_time = future_df.loc[future_df['low'].idxmin()]['datetime']
                                                peak_price = potential_best
                                                
                                            fig_whatif.add_annotation(
                                                x=peak_time, y=peak_price,
                                                text="错过的顶", showarrow=True, arrowhead=1, arrowcolor="#FF5252"
                                            )
                                        
                                        fig_whatif.update_layout(
                                            height=400,
                                            margin=dict(t=30, b=10, l=10, r=10),
                                            plot_bgcolor='#1E1E1E', paper_bgcolor='#1E1E1E',
                                            font=dict(color='#E0E0E0'),
                                            xaxis_rangeslider_visible=False,
                                            showlegend=True,
                                            title=f"如果多拿 {hold_hours} 小时会发生什么？",
                                            yaxis=dict(gridcolor='#333'),
                                            xaxis=dict(showgrid=False)
                                        )
                                        st.plotly_chart(fig_whatif, use_container_width=True)
                            
                            # =================================================
                            # 📉 功能设想三：上帝视角 (Trend Context - Vegas Style)
                            # =================================================
                            st.markdown("---")
                            with st.expander("📉 上帝视角 (Vegas 隧道趋势分析)", expanded=False):
                                st.caption("跳出 1分钟的噪音，利用 Vegas 隧道 (144/169/288/338) 识别大周期趋势。")
                                
                                # 1. 控制台
                                col_tf, col_ma = st.columns([1, 3])
                                with col_tf:
                                    # 选择要看的大周期 (Vegas 在 1H/4H 效果最佳)
                                    tf_map = {"1小时 (1H)": "1h", "4小时 (4H)": "4h", "日线 (1D)": "1d"}
                                    sel_tf = st.selectbox("选择格局周期", options=list(tf_map.keys()), index=1)
                                    resample_rule = tf_map[sel_tf]
                                    
                                with col_ma:
                                    # 均线辅助
                                    show_vegas = st.checkbox("显示 Vegas 隧道 (144/169 & 288/338)", value=True)

                                # 2. 获取更宽范围的数据
                                if 'market_engine' not in st.session_state:
                                    st.session_state.market_engine = MarketDataEngine()
                                me = st.session_state.market_engine
                                
                                # ============ 🔧 修复开始：动态计算回溯时间 ============
                                # Vegas 隧道最大周期是 338，我们需要确保有足够的 K 线数量
                                # 1H: 需要至少 338 小时 (约14天) -> 我们取 30 天
                                # 4H: 需要至少 338*4 小时 (约56天) -> 我们取 120 天
                                # 1D: 需要至少 338 天 -> 我们取 450 天
                                
                                lookback_map = {
                                    "1h": 30,
                                    "4h": 120, 
                                    "1d": 450
                                }
                                # 获取对应周期的回溯天数，默认 30 天
                                days_needed = lookback_map.get(resample_rule, 30)
                                
                                # 计算开始时间
                                context_start = trade['open_time'] - (days_needed * 24 * 60 * 60 * 1000)
                                context_end = trade['close_time'] + (5 * 24 * 60 * 60 * 1000)
                                # =====================================================
                                
                                # 清洗 Symbol
                                raw_symbol = trade['symbol']
                                clean_symbol = raw_symbol.split(':')[0] 
                                if "USDT" in clean_symbol and "/" not in clean_symbol:
                                    clean_symbol = clean_symbol.replace("USDT", "/USDT")
                                    
                                with st.spinner(f"正在构建 {sel_tf} Vegas 隧道 (回溯 {days_needed} 天数据)..."):
                                    raw_context_df = me.get_klines_df(clean_symbol, context_start, context_end)
                                    
                                    # 检查数据是否真的足够 (可能你的本地库只同步了 30 天)
                                    if raw_context_df.empty:
                                        st.warning("⚠️ 本地数据为空，请先同步。")
                                    else:
                                        # 3. 核心算法：重采样
                                        agg_dict = {
                                            'open': 'first', 'high': 'max',
                                            'low': 'min', 'close': 'last', 'volume': 'sum'
                                        }
                                        if 'datetime' in raw_context_df.columns:
                                            raw_context_df.set_index('datetime', inplace=True)
                                            
                                        htf_df = raw_context_df.resample(resample_rule).agg(agg_dict).dropna()
                                        
                                        # 4. 计算 Vegas 均线组
                                        if show_vegas and len(htf_df) > 338:
                                            import pandas_ta as ta
                                            # 短期隧道 (绿)
                                            htf_df['EMA144'] = ta.ema(htf_df['close'], length=144)
                                            htf_df['EMA169'] = ta.ema(htf_df['close'], length=169)
                                            # 长期隧道 (红)
                                            htf_df['EMA288'] = ta.ema(htf_df['close'], length=288)
                                            htf_df['EMA338'] = ta.ema(htf_df['close'], length=338)
                                        
                                        # 5. 绘图
                                        import plotly.graph_objects as go
                                        fig_trend = go.Figure()
                                        
                                        # A. K线
                                        fig_trend.add_trace(go.Candlestick(
                                            x=htf_df.index,
                                            open=htf_df['open'], high=htf_df['high'],
                                            low=htf_df['low'], close=htf_df['close'],
                                            name=f'{sel_tf} K线'
                                        ))
                                        
                                        # B. Vegas 隧道
                                        if show_vegas:
                                            # 定义颜色：短期用绿色系，长期用红色系
                                            vegas_colors = {
                                                'EMA144': '#00E676', 'EMA169': '#00E676', # 隧道1
                                                'EMA288': '#FF5252', 'EMA338': '#FF5252'  # 隧道2
                                            }
                                            
                                            for ma, color in vegas_colors.items():
                                                if ma in htf_df.columns:
                                                    # 这里的 line_width 设细一点，突出"通道"的感觉
                                                    fig_trend.add_trace(go.Scatter(
                                                        x=htf_df.index, y=htf_df[ma],
                                                        mode='lines', line=dict(color=color, width=1),
                                                        name=ma, hoverinfo='skip' # 鼠标悬停不显示太杂乱
                                                    ))
                                            
                                            # (可选) 在两条线之间填充颜色，形成真正的"隧道"视觉效果
                                            # Plotly 填充需要一点技巧，这里为了性能暂只画线，视觉上已经足够清晰

                                        # C. 标记交易
                                        my_open_time = pd.to_datetime(trade['open_time'], unit='ms')
                                        my_close_time = pd.to_datetime(trade['close_time'], unit='ms')
                                        
                                        # 在重采样后的数据中标记交易位置
                                        trade_mask_htf = (htf_df.index >= my_open_time) & (htf_df.index <= my_close_time)
                                        trade_snippet_htf = htf_df[trade_mask_htf]
                                        
                                        if not trade_snippet_htf.empty:
                                            box_top = trade_snippet_htf['high'].max()
                                            box_bottom = trade_snippet_htf['low'].min()
                                            h = box_top - box_bottom
                                            
                                            fig_trend.add_shape(
                                                type="rect",
                                                x0=my_open_time, y0=box_bottom - h*0.2,
                                                x1=my_close_time, y1=box_top + h*0.2,
                                                line=dict(color="yellow", width=2),
                                                fillcolor="rgba(255, 255, 0, 0.3)",
                                            )
                                            fig_trend.add_annotation(
                                                x=my_open_time, y=box_top + h*0.2,
                                                text="👈 你的操作", showarrow=True, arrowhead=1, ax=0, ay=-30,
                                                font=dict(color="yellow")
                                            )

                                        fig_trend.update_layout(
                                            height=500, margin=dict(t=30, b=10, l=10, r=10),
                                            plot_bgcolor='#1E1E1E', paper_bgcolor='#1E1E1E',
                                            font=dict(color='#E0E0E0'), title=f"{clean_symbol} - {sel_tf} Vegas 趋势图",
                                            xaxis_rangeslider_visible=False,
                                            yaxis=dict(gridcolor='#333'), xaxis=dict(showgrid=False)
                                        )
                                        st.plotly_chart(fig_trend, use_container_width=True)
                                        
                                        # 6. AI 趋势简评 (Vegas 逻辑)
                                        if show_vegas and 'EMA169' in htf_df.columns:
                                            try:
                                                # 获取开仓时刻的数据
                                                idx = htf_df.index.get_indexer([my_open_time], method='nearest')[0]
                                                bar = htf_df.iloc[idx]
                                                price = bar['close']
                                                tunnel1 = bar['EMA169'] # 短期隧道参考
                                                tunnel2 = bar['EMA288'] # 长期隧道参考
                                                
                                                # 简单的多空判断逻辑
                                                is_bull = price > tunnel1
                                                # 强趋势判断：如果在 288 之上，是强多头
                                                is_strong_bull = price > tunnel2
                                                
                                                trend_str = "🟢 多头趋势 (在 169 之上)" if is_bull else "🔴 空头趋势 (在 169 之下)"
                                                if is_strong_bull and is_bull: trend_str += " | 🔥 强趋势 (在 288 之上)"
                                                
                                                # 顺势/逆势
                                                my_dir = trade['direction']
                                                is_with_trend = (is_bull and "Long" in my_dir) or (not is_bull and "Short" in my_dir)
                                                action_emoji = "✅ 顺势" if is_with_trend else "⚠️ 逆势"
                                                
                                                st.info(f"**Vegas 诊断 ({sel_tf})**: 当时处于 {trend_str}。你的操作是 **{my_dir}** -> 判定为 **{action_emoji}**。")
                                            except:
                                                pass
                            
                            # =================================================
                    
                    st.markdown("---")
                    
                    # ==================================================================
                    # 2. 深度复盘工作台 (v3.0 Pro)
                    # ==================================================================
                    st.markdown("### 🧘 Deep Review (深度复盘)")
                    
                    # trade_row 已在价格行为分析部分定义，这里不需要重复定义
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
                                # === 🧠 V5.0 新增：写入 AI 记忆 ===
                                if new_note and len(new_note) > 5:
                                    # 准备数据
                                    # 从 trade_row 获取 MAE/MFE (注意：如果是刚计算的，trade_row可能还没更新，
                                    # 但为了简化，我们先读现有的，或者你可以把计算完的 pa_data 传进来)
                                    # 既然刚才 update_trade_extended 已经存了，我们这里简单处理即可
                                    
                                    # 为了稳健，我们再次确认一下数据
                                    curr_mae = trade_row.get('mae', 0.0)
                                    curr_mfe = trade_row.get('mfe', 0.0)
                                    # 如果刚才没计算价格行为，这里可能是 None
                                    if pd.isna(curr_mae): curr_mae = 0.0
                                    if pd.isna(curr_mfe): curr_mfe = 0.0
                                    
                                    # 调用记忆引擎
                                    mem_ok, mem_msg = memory_engine.add_trade_memory(
                                        trade_id=trade['round_id'],  # 使用 round_id 作为唯一索引
                                        note=new_note,
                                        symbol=trade['symbol'],
                                        strategy=new_strategy,
                                        mental_state=new_mental,
                                        pnl=trade['net_pnl'],
                                        mae=curr_mae,
                                        mfe=curr_mfe
                                    )
                                    if mem_ok:
                                        st.toast(mem_msg, icon="🧠")  # 使用 toast 提示，不打断流程
                                    else:
                                        print(f"记忆写入警告: {mem_msg}")
                                # ========================================
                                
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
                        
                    # 🔍 请求AI审计 (v8.7 Fix)
                    if st.button("🔍 请求 AI 审计这笔交易", key=f"btn_audit_{trade['round_id']}", use_container_width=True):
                        
                        # 1. Simple Data Check
                        if trade_row.get('mae') is None or str(trade_row.get('mae')) == 'nan':
                            st.toast("⚠️ 建议先点击【🚀 计算 v7.0 指标】，否则 AI 数据不全！")
                        
                        # 2. Status Box
                        status_box = st.status("🤖 AI 正在工作中...", expanded=True)
                        
                        try:
                            # A. Retrieve Memory
                            status_box.write("📚 正在回顾历史记忆...")
                            related_memories = ""
                            if 'memory_engine' in st.session_state:
                                mems = st.session_state.memory_engine.retrieve_memories(trade_row.get('notes', ''))
                                if mems:
                                    related_memories = "\n".join([f"- {m['note']}" for m in mems])
                            
                            # B. Initialize AI
                            if 'ai_assistant' not in st.session_state:
                                from ai_assistant import AIAssistant
                                st.session_state.ai_assistant = AIAssistant()
                            
                            # C. Call AI
                            status_box.write("🧠 正在分析 K 线结构与形态...")
                            
                            # Get model name from sidebar selection, default to deepseek-chat
                            model_used = st.session_state.get('user_ai_model', 'deepseek-chat')
                            
                            analysis_result = st.session_state.ai_assistant.audit_single_trade(
                                trade_row, 
                                related_memories, 
                                model_name=model_used
                            )
                            
                            # D. Save & Refresh
                            if analysis_result and "审计失败" not in analysis_result:
                                status_box.write("💾 正在保存报告...")
                                success, msg = engine.update_trade(
                                    trade['round_id'].replace('_OPEN', '').replace('_CLOSE', ''),
                                    'ai_analysis',
                                    analysis_result
                                )
                                
                                if success:
                                    status_box.update(label="✅ 审计完成！", state="complete", expanded=False)
                                    st.success("报告已生成并保存。")
                                    
                                    # Force Refresh
                                    if 'trades_df' in st.session_state:
                                        del st.session_state['trades_df']
                                    time.sleep(0.5)
                                    st.rerun() 
                                else:
                                    status_box.update(label="❌ 保存失败", state="error")
                                    st.error(f"保存错误: {msg}")
                            else:
                                status_box.update(label="⚠️ AI 返回异常", state="error")
                                st.error(f"AI 响应内容: {analysis_result}")
                                
                        except Exception as e:
                            # This except block closes the try block above
                            status_box.update(label="❌ 发生程序错误", state="error")
                            st.error(f"Error: {str(e)}")
                            import traceback
                            st.code(traceback.format_exc())

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
                    
                    # v6.0 补全价格行为字段（如果 rounds_df 中没有）
                    if 'mae' not in analysis_df.columns:
                        analysis_df['mae'] = analysis_df['round_id'].apply(lambda x: get_meta_field(x, 'mae', None))
                    if 'mfe' not in analysis_df.columns:
                        analysis_df['mfe'] = analysis_df['round_id'].apply(lambda x: get_meta_field(x, 'mfe', None))
                    if 'etd' not in analysis_df.columns:
                        analysis_df['etd'] = analysis_df['round_id'].apply(lambda x: get_meta_field(x, 'etd', None))
                    
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
                    # B. MAE vs PnL 散点图 (v6.0 核心洞察)
                    # ==========================================================
                    st.markdown("### 🎯 交易质量四象限 (MAE vs PnL)")
                    st.caption("此图用于识别【运气单】和【死扛单】。理想交易应位于左上角（低浮亏，高盈利）。")
                    
                    # 初始化散点图筛选变量
                    scatter_mask = None
                    scatter_filter_reason = None
                    
                    if 'mae' in analysis_df.columns and 'net_pnl' in analysis_df.columns:
                        # 准备数据：过滤掉异常值
                        scatter_df = analysis_df[analysis_df['mae'] < 0].copy()  # MAE 必须是负的
                        # 进一步过滤 NaN 值
                        scatter_df = scatter_df[scatter_df['mae'].notna() & scatter_df['net_pnl'].notna()]
                        
                        if not scatter_df.empty:
                            # 构造悬停提示数据
                            scatter_df['desc'] = scatter_df.apply(
                                lambda x: f"{x.get('symbol', 'N/A')} ({x.get('close_date_str', 'N/A')})<br>策略: {x.get('strategy', '-')}<br>心态: {x.get('mental_state', '-')}", axis=1
                            )
                            
                            # 绘制散点图
                            fig_scatter = px.scatter(
                                scatter_df, 
                                x='mae', 
                                y='net_pnl',
                                color='mental_state',  # 按心态上色，看看是不是 FOMO 的单子 MAE 很大？
                                size=scatter_df['net_pnl'].abs().clip(lower=10),  # 气泡大小代表金额大小
                                hover_name='desc',
                                title="痛苦(MAE) vs 收益(PnL) 分布图",
                                labels={'mae': '最大浮亏 (MAE)', 'net_pnl': '最终盈亏 (PnL)'}
                            )
                            
                            # 加上象限参考线
                            fig_scatter.add_hline(y=0, line_dash="dash", line_color="gray")
                            # 假设你的平均止损 R 大概是 -1R (或者你可以取 MAE 的中位数)
                            avg_risk_line = scatter_df['mae'].median()
                            if not pd.isna(avg_risk_line):
                                fig_scatter.add_vline(x=avg_risk_line, line_dash="dash", line_color="gray", annotation_text="平均浮亏线")
                            
                            # 样式美化
                            fig_scatter.update_layout(
                                plot_bgcolor='#1E1E1E', 
                                paper_bgcolor='#1E1E1E', 
                                font=dict(color='#E0E0E0'),
                                xaxis=dict(autorange="reversed"),  # X轴反转，让负数(亏损)越往左越小，越往右越大(接近0)
                                height=500
                            )
                            
                            # 启用点击交互
                            sel_scatter = st.plotly_chart(fig_scatter, use_container_width=True, on_select="rerun", selection_mode="points")
                            
                            # 处理交互筛选
                            if sel_scatter and len(sel_scatter.selection["points"]) > 0:
                                point_idx = sel_scatter.selection["points"][0]["point_index"]
                                # 找到对应的数据行
                                selected_row = scatter_df.iloc[point_idx]
                                scatter_mask = analysis_df['round_id'] == selected_row['round_id']
                                scatter_filter_reason = f"🎯 选中散点: {selected_row.get('symbol', 'N/A')} (MAE: {selected_row['mae']:.2f})"
                                # 保存到 session_state
                                st.session_state['scatter_mask'] = scatter_mask
                                st.session_state['scatter_filter_reason'] = scatter_filter_reason
                            elif 'scatter_mask' in st.session_state:
                                # 使用之前保存的筛选
                                scatter_mask = st.session_state.get('scatter_mask')
                                scatter_filter_reason = st.session_state.get('scatter_filter_reason')
                        else:
                            st.info("暂无有效的 MAE 数据用于绘图 (需先进行'还原持仓过程')")
                    else:
                        st.warning("数据库中缺少 MAE/MFE 字段，请先运行 update_db_v4.py")
                        
                    st.markdown("---")
                    
                    # ==========================================================
                    # C. 交互式归因图表 (Interactive Charts)
                    # ==========================================================
                    
                    # 初始化筛选掩码 (默认全选)
                    mask = pd.Series([True] * len(analysis_df))
                    filter_reason = "全部数据"
                    
                    # 处理散点图筛选（优先级高于日历筛选）
                    if scatter_mask is not None:
                        mask = scatter_mask
                        filter_reason = scatter_filter_reason
                    # 处理日历筛选
                    elif selected_date_event and len(selected_date_event.selection["points"]) > 0:
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
                # =========================================================
                # 📅 功能模块：周期性复盘报告 (v7.2 - 固定笔数/时间双模式)
                # =========================================================
                st.markdown("---")
                st.header("📅 周期性深度复盘 (System Check)")
                st.caption("定期体检：检验你的交易系统是否稳定，执行是否合规。")
                
                with st.expander("📊 生成深度复盘报告", expanded=False):
                    # 1. 复盘模式选择 (时间 vs 笔数)
                    col_mode, col_val, col_bench = st.columns([1, 1, 1])
                    
                    with col_mode:
                        review_mode = st.radio("复盘模式", ["按时间周期", "按交易笔数"], horizontal=True)
                        
                    with col_val:
                        if review_mode == "按时间周期":
                            # 选项：最近 7/30/90 天
                            review_val = st.selectbox("选择周期", [7, 30, 90, 365], format_func=lambda x: f"最近 {x} 天")
                        else:
                            # 选项：最近 20/30/50/100 笔
                            review_val = st.number_input("复盘笔数 (最新 N 笔)", min_value=10, max_value=500, value=30, step=10)
                    with col_bench:
                        benchmark_symbol = st.text_input("对标指数", value="BTC/USDT")
                    
                    btn_gen = st.button("🚀 生成体检报告", type="primary", use_container_width=True)
                    if btn_gen:
                        # 检查 AI 配置
                        if 'ai_key' not in st.session_state or not st.session_state.get('ai_key'):
                            st.error("请先在左侧侧边栏配置 AI API Key！")
                        else:
                            # === A. 获取并处理数据 (核心修复) ===
                            conn = sqlite3.connect(engine.db_path)
                            
                            # 1. 既然要合成回合，我们需要读取足够多的历史原始数据
                            # 简单起见，读取全部交易，然后在内存中处理 (SQLite处理几万条数据很快)
                            # 🟢 修复：使用 timestamp 字段，而不是 open_time
                            query = "SELECT * FROM trades ORDER BY timestamp ASC"
                            try:
                                df_raw = pd.read_sql_query(query, conn)
                                conn.close()
                            except Exception as e:
                                st.error(f"数据库读取失败: {e}")
                                st.stop()
                            
                            if df_raw.empty:
                                st.warning("⚠️ 数据库为空，没有交易记录。")
                            else:
                                # 2. 调用核心算法：合成回合 (Round)
                                # 只有合成后，我们才有 'open_time', 'net_pnl', 'strategy' 这些字段
                                df_rounds = process_trades_to_rounds(df_raw)
                                
                                if df_rounds.empty:
                                    st.warning("⚠️ 无法合成有效交易回合（可能全是未平仓的单子）。")
                                else:
                                    # 3. 根据模式筛选数据 (Filter)
                                    if review_mode == "按时间周期":
                                        # 筛选最近 N 天
                                        start_date_ts = int((datetime.now() - pd.Timedelta(days=review_val)).timestamp() * 1000)
                                        df_target = df_rounds[df_rounds['close_time'] >= start_date_ts].copy()
                                        report_title = f"最近 {review_val} 天"
                                    else:
                                        # 筛选最近 N 笔 (取最后 N 行)
                                        df_target = df_rounds.tail(review_val).copy()
                                        report_title = f"最近 {review_val} 笔交易"
                                    
                                    if df_target.empty:
                                        st.warning(f"⚠️ {report_title} 没有找到已平仓的交易记录。")
                                    else:
                                        # === B. 准备大盘数据 (Alpha Check) ===
                                        if 'market_engine' not in st.session_state:
                                            st.session_state.market_engine = MarketDataEngine()
                                        me = st.session_state.market_engine
                                        
                                        # 获取时间范围
                                        first_ts = df_target['open_time'].min()
                                        last_ts = max(df_target['close_time'].max(), int(datetime.now().timestamp()*1000))
                                        
                                        # 拉取 Benchmark 数据
                                        with st.spinner(f"正在分析 {report_title} 的表现 vs {benchmark_symbol}..."):
                                            btc_df = me.get_klines_df(benchmark_symbol, first_ts, last_ts)
                                        
                                        market_context_str = ""
                                        btc_return = 0.0
                                        
                                        # === C. 绘制资金曲线 vs 大盘 ===
                                        if not btc_df.empty:
                                            base_price = btc_df.iloc[0]['close']
                                            btc_df['pct_change'] = (btc_df['close'] - base_price) / base_price * 100
                                            btc_return = btc_df.iloc[-1]['pct_change']
                                        
                                        # 计算用户累计盈亏
                                        df_target = df_target.sort_values('close_time') # 确保按时间排序
                                        df_target['cum_pnl'] = df_target['net_pnl'].cumsum()
                                        
                                        # 统计数据
                                        total_pnl = df_target['net_pnl'].sum()
                                        win_rate = len(df_target[df_target['net_pnl'] > 0]) / len(df_target) * 100
                                        avg_rr = df_target[df_target['net_pnl'] > 0]['net_pnl'].mean() / abs(df_target[df_target['net_pnl'] < 0]['net_pnl'].mean()) if not df_target[df_target['net_pnl'] < 0].empty else 0
                                        
                                        # 绘图
                                        from plotly.subplots import make_subplots
                                        import plotly.graph_objects as go
                                        
                                        fig_alpha = make_subplots(specs=[[{"secondary_y": True}]])
                                        
                                        # 资金曲线
                                        fig_alpha.add_trace(go.Scatter(
                                            x=pd.to_datetime(df_target['close_time'], unit='ms'), y=df_target['cum_pnl'],
                                            name="累计盈亏 ($)", mode='lines+markers', line=dict(color='#00E676', width=3)
                                        ), secondary_y=False)
                                        
                                        # 大盘曲线
                                        if not btc_df.empty:
                                            # 确保 datetime 列存在
                                            if 'datetime' in btc_df.columns:
                                                btc_x = btc_df['datetime']
                                            elif btc_df.index.name == 'datetime':
                                                btc_x = btc_df.index
                                            else:
                                                btc_x = pd.to_datetime(btc_df['timestamp'], unit='ms')
                                            
                                            fig_alpha.add_trace(go.Scatter(
                                                x=btc_x, y=btc_df['pct_change'],
                                                name=f"{benchmark_symbol} (%)", mode='lines', line=dict(color='gray', width=1, dash='dot')
                                            ), secondary_y=True)
                                        
                                        fig_alpha.update_layout(
                                            title=f"📈 资金曲线: {report_title}", 
                                            height=400, 
                                            plot_bgcolor='#1E1E1E', 
                                            paper_bgcolor='#1E1E1E', 
                                            font=dict(color='#E0E0E0'),
                                            hovermode='x unified',
                                            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                                        )
                                        fig_alpha.update_yaxes(title_text="累计盈亏 ($)", secondary_y=False, showgrid=True, gridcolor='#333')
                                        fig_alpha.update_yaxes(title_text="大盘涨跌 (%)", secondary_y=True, showgrid=False)
                                        
                                        st.plotly_chart(fig_alpha, use_container_width=True)
                                        
                                        # === D. 生成 AI 深度报告 ===
                                        market_context_str = f"""
                                        【周期环境】
                                        - 复盘范围: {report_title}
                                        - 大盘表现 ({benchmark_symbol}): {btc_return:.2f}%
                                        - 账户表现: 总盈亏 ${total_pnl:.2f} | 胜率 {win_rate:.1f}% | 盈亏比 {avg_rr:.2f}
                                        """
                                        
                                        st.markdown("### 🤖 AI 系统体检报告")
                                        with st.spinner("AI 正在逐笔核对你的交易系统执行情况..."):
                                            # 准备交易摘要 (加入策略和心态)
                                            trades_summary = []
                                            for _, t in df_target.iterrows():
                                                # 尝试获取 v7.0 指标
                                                extra_info = ""
                                                if 'mad' in t and pd.notna(t['mad']): 
                                                    extra_info += f" | MAD:{t['mad']}m"
                                                if 'efficiency' in t and pd.notna(t['efficiency']): 
                                                    extra_info += f" | Eff:{t['efficiency']:.2f}"
                                                
                                                trades_summary.append(
                                                    f"- {t.get('close_date_str', 'N/A')} {t.get('symbol', 'N/A')} ({t.get('direction', 'N/A')}): ${t.get('net_pnl', 0):.2f} | 策略:{t.get('strategy', '无')} | 心态:{t.get('mental_state', '无')}{extra_info}"
                                                )
                                            
                                            summary_text = "\n".join(trades_summary)
                                            
                                            # 增强版 Prompt
                                            prompt = f"""
                                            你是一名严格的【交易系统审计师】。请根据以下数据为学员生成一份【阶段性系统体检报告】。
                                            
                                            {market_context_str}
                                            
                                            【交易流水 ({report_title})】
                                            {summary_text}
                                            
                                            请重点审计以下 3 点：
                                            1. **系统一致性 (System Consistency)**：
                                               - 检查他的盈利单是否都来自同一个策略？还是东一榔头西一棒槌？
                                               - 亏损单是否因为违反了策略（看心态和备注）？
                                            2. **盈亏同源性 (Alpha Check)**：
                                               - 结合大盘表现，他是靠实力（跑赢大盘）还是靠运气（大盘涨他也涨）？
                                               - 如果大盘跌他没亏，请给予高度评价。
                                            3. **执行力打分**：
                                               - 结合 MAD (痛苦时长) 和 Efficiency (卖飞指数)，评价他的持仓耐心和离场果断度。
                                            
                                            输出风格：专业、严厉、数据驱动。最后给出一个【系统评分 (0-100)】和一条【整改建议】。
                                            """
                                            
                                            try:
                                                # 调用 OpenAI
                                                from ai_assistant import get_client
                                ai_key = st.session_state.get('ai_key', '')
                                ai_base_url = st.session_state.get('ai_base_url', 'https://api.deepseek.com')
                                                curr_model = st.session_state.get('ai_model', 'gpt-4o')
                                                
                                                client = get_client(ai_key, ai_base_url)
                                                
                                                report_content = client.chat.completions.create(
                                                    model=curr_model,
                                                    messages=[
                                                        {"role": "system", "content": "你是专业的量化交易审计师。"},
                                                        {"role": "user", "content": prompt}
                                                    ],
                                                    temperature=0.7
                                                ).choices[0].message.content
                                                
                                                st.write(report_content)
                                                
                                                # 保存报告
                                                if selected_key:
                                                    t_count = len(df_target)
                                                    t_pnl = df_target['net_pnl'].sum()
                                                    t_win_count = len(df_target[df_target['net_pnl'] > 0])
                                    t_win = (t_win_count / t_count * 100) if t_count > 0 else 0
                                    
                                                    start_date = str(df_target.iloc[0].get('open_date_str', '')) if not df_target.empty else ""
                                                    end_date = str(df_target.iloc[-1].get('close_date_str', '')) if not df_target.empty else ""
                                    
                                    engine.save_ai_report(
                                                        report_title, 
                                        start_date,
                                        end_date,
                                        t_count, t_pnl, t_win, report_content, selected_key
                                    )
                                                    st.success("报告已归档！")
                                                
                                            except Exception as e:
                                                st.error(f"AI 生成报告失败: {str(e)}")
            
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