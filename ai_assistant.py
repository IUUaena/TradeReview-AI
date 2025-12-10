from openai import OpenAI
import pandas as pd
import json
import base64
import mimetypes
import os
import pandas_ta as ta
from datetime import datetime
from market_engine import MarketDataEngine

def get_client(api_key, base_url):
    """
    获取 OpenAI 客户端，并针对 Google Gemini 做特殊兼容处理
    """
    # 针对 Google Gemini 的防御性 URL 修正
    if "generativelanguage" in base_url:
        # 移除末尾斜杠，防止双重斜杠
        clean_url = base_url.rstrip('/')
        # 如果用户只填了 .../v1beta，自动补全 /openai/
        if "openai" not in clean_url:
            clean_url += "/openai/"
        # 如果用户填了 .../openai，确保后面有斜杠 (Python openai 库的特性)
        if clean_url.endswith("openai"):
            clean_url += "/"
        base_url = clean_url
    return OpenAI(api_key=api_key, base_url=base_url)

# 新增：图片转 Base64 辅助函数
def encode_image(image_path):
    """将图片文件编码为 Base64 字符串"""
    if not image_path or not os.path.exists(image_path):
        return None
    try:
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    except:
        return None

def call_api_with_retry(client, api_params, max_retries=2):
    """带重试的 API 调用"""
    for attempt in range(max_retries + 1):
        try:
            return client.chat.completions.create(**api_params)
        except Exception as e:
            if attempt < max_retries:
                print(f"⚠️ API 调用失败，重试中 ({attempt + 1}/{max_retries})...")
                import time
                time.sleep(1)
            else:
                raise e

# ======================================================
# 🧠 AI 独立分析插件 (V7.0 Core)
# ======================================================
class AIAssistant:
    def __init__(self, api_key=None, base_url=None):
        """
        初始化 AI 助手
        api_key: OpenAI API Key (如果为 None，尝试从环境变量获取)
        base_url: API Base URL (如果为 None，使用默认值)
        """
        # 尝试从环境变量或参数获取 Key
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or "https://api.deepseek.com"
        self.client = None
        if self.api_key:
            self.client = get_client(self.api_key, self.base_url)
            
        # 初始化数据引擎 (用于后台静默分析)
        self.market_engine = MarketDataEngine()

    def check_key(self):
        return self.api_key is not None

    def set_key(self, key, base_url=None):
        self.api_key = key
        self.base_url = base_url or self.base_url
        self.client = get_client(self.api_key, self.base_url)

    def _analyze_vegas_trend(self, symbol, open_time):
        """后台自动计算 Vegas 趋势"""
        # 增加安全检查：防止参数为空导致崩溃
        if not symbol or not open_time:
            return "数据不足，跳过趋势分析"
        try:
            clean_symbol = symbol.split(':')[0].replace('USDT', '/USDT') if 'USDT' in symbol and '/' not in symbol else symbol
            
            # 获取 4H 数据 (回溯 150 天)
            lookback = 150 * 24 * 60 * 60 * 1000
            start_ts = int(open_time) - lookback # 确保是 int
            df = self.market_engine.get_klines_df(clean_symbol, start_ts, int(open_time) + 60000)
            
            if df.empty or len(df) < 1000:
                return "数据不足 (请同步至少150天K线)"
            df.set_index('datetime', inplace=True)
            df_4h = df.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()
            
            if len(df_4h) < 170:
                return "历史数据不足计算 Vegas"
            ema144 = df_4h.ta.ema(length=144).iloc[-1]
            ema169 = df_4h.ta.ema(length=169).iloc[-1]
            price = df_4h.iloc[-1]['close']
            
            if price > ema144 and price > ema169:
                return "🟢 4H级别多头趋势 (价格 > Vegas隧道)"
            elif price < ema144 and price < ema169:
                return "🔴 4H级别空头趋势 (价格 < Vegas隧道)"
            else:
                return "🟡 4H级别震荡/穿越中"
        except Exception as e:
            return f"趋势分析失败: {str(e)}"

    def _analyze_missed_profit(self, symbol, direction, close_time, exit_price):
        """后台自动计算是否卖飞"""
        # === 🚨 关键修复：防止 exit_price 为 None 导致 float() 崩溃 ===
        if exit_price is None or exit_price == "":
            return "价格数据缺失，跳过离场分析"
        if not close_time:
            return "时间数据缺失，跳过离场分析"
        try:
            clean_symbol = symbol.split(':')[0].replace('USDT', '/USDT') if 'USDT' in symbol and '/' not in symbol else symbol
            future_end = int(close_time) + (24 * 60 * 60 * 1000) # 确保是 int
            df = self.market_engine.get_klines_df(clean_symbol, int(close_time), future_end)
            
            if df.empty:
                return "无未来数据 (可能刚平仓)"
            
            potential_high = df['high'].max()
            potential_low = df['low'].min()
            
            # 安全转换
            exit_price_val = float(exit_price)
            if exit_price_val == 0: return "价格无效"

            if "Long" in str(direction):
                missed_pct = (potential_high - exit_price_val) / exit_price_val * 100
                if missed_pct > 2.0: return f"🍖 严重卖飞！离场后涨了 {missed_pct:.2f}%"
                elif missed_pct < -1.0: return "🏆 成功逃顶"
                else: return "✅ 正常离场"
            else:
                missed_pct = (exit_price_val - potential_low) / exit_price_val * 100
                if missed_pct > 2.0: return f"🍖 严重卖飞！离场后跌了 {missed_pct:.2f}%"
                elif missed_pct < -1.0: return "🏆 成功逃顶"
                else: return "✅ 正常离场"
        except Exception as e:
            return f"离场分析不可用: {str(e)}"

def audit_single_trade(api_key, base_url, trade_data, system_manifesto="", strategy_rules="", image_path=None, model_name="deepseek-chat", related_memories=[]):
    """
    v7.2 单笔审计：刚性趋势 + 柔性价格行为 (Rigid Trend + Fluid PA)
    """
    try:
        # === 1. 数据清洗 ===
        def safe_get(key, default):
            val = trade_data.get(key)
            return val if val is not None else default
        
        symbol = safe_get('symbol', 'Unknown')
        direction = safe_get('direction', 'Long')
        price = safe_get('price', 0)
        open_ts = safe_get('open_time', int(datetime.now().timestamp() * 1000))
        close_ts = safe_get('close_time', open_ts)
        
        # 初始化 AI
        client = get_client(api_key, base_url)
        ai_helper = AIAssistant(api_key=api_key, base_url=base_url)
        
        # 自动分析上帝视角 (Vegas Trend)
        trend_context = ai_helper._analyze_vegas_trend(symbol, open_ts)
        what_if_result = ai_helper._analyze_missed_profit(symbol, direction, close_ts, price)
        
        # 准备上下文数据
        t = trade_data
        net_pnl = float(t.get('net_pnl', 0))
        pnl_emoji = "✅" if net_pnl > 0 else "❌"
        
        def safe_num(val): return f"{float(val):.2f}" if val is not None else "N/A"
        
        metrics_text = "【微观数据】: 暂无"
        if t.get('mae') is not None:
            metrics_text = f"""
        【微观数据】
        - R倍数: MAE -{safe_num(t.get('mae'))}R | MFE +{safe_num(t.get('mfe'))}R
        - 心理压力: 痛苦时长 {safe_num(t.get('mad'))}min
        - 量价结构: RVOL {safe_num(t.get('rvol'))}
        """
        
        context_text = f"""
        【交易档案】
        - 标的: {t.get('symbol')} ({t.get('direction')})
        - 结果: {pnl_emoji} ${safe_num(net_pnl)}
        
        {metrics_text}
        
        【上帝视角 (AI Auto-Analysis)】
        - 宏观趋势: {trend_context}
        - 离场评价: {what_if_result}
        
        【交易员主观记录】
        - 策略标签: {t.get('strategy', '无')}
        - 心态标签: {t.get('mental_state', '无')}
        - 执行标签: {t.get('process_tag', '无')}
        - 详细笔记: "{t.get('notes', '无')}"
        """
        
        # === RAG 记忆增强 ===
        memory_text = ""
        if related_memories:
            mem_list = [f"- {m['meta']['date']} {m['meta']['symbol']}: {m['note']}" for m in related_memories]
            memory_block = "\n".join(mem_list[:3])
            memory_text = f"【历史相关记忆】:\n{memory_block}"
        
        # === 核心 Prompt：刚柔并济版 ===
        manifesto_part = f"【用户个人宪法 (最高优先级)】: {system_manifesto}" if system_manifesto else ""
        strategy_part = f"【策略定义】: {strategy_rules}" if strategy_rules else ""
        system_prompt = f"""
        # ROLE DEFINITION
        You are the **Vegas-Brooks Chief Dealer**, a highly experienced discretionary trader. 
        Your job is to audit trades by combining the **Rigid Structure of Vegas Tunnels** with the **Fluid Logic of Price Action**.
        
        # 1. THE RIGID LAWS (The Constitution)
        - **Trend Context:** We ONLY trade in the direction of the Major Trend (EMA 288/338).
        - **Value Zone:** We look for setups near the Vegas Tunnel (144/169).
        - **Risk Control:** R:R must be reasonable (>= 1.5 preferred).
        
        # 2. THE FLUID LOGIC (Price Action & Market Dynamics)
        **Do NOT just look for textbook "High 2" patterns.** Markets are messy. 
        Instead, use your deep knowledge of Price Action (Al Brooks / Wyckoff) to analyze the **Battle between Bulls and Bears**:
        - **Pullback Quality (调整结构):** - Is the pullback "orderly" (weak volume, small candles)? Or is it a "crash" (panic selling)?
          - Look for: Bull Flags, Wedges, Micro Double Bottoms, or simple drying up of selling pressure.
          
        - **Entry Signal (入场信号):**
          - Does the entry bar show **Conviction**? (Strong Close, Big Body).
          - Is there a "Shift in Momentum"? (e.g., a strong Green bar engulfing previous weak Red bars).
          - Even if it's not a standard H2, does the context justify the entry? (e.g., strong trend resumption).
        
        # 3. PSYCHOLOGY & EXECUTION CHECK
        - Analyze the user's **Notes** and **Tags**.
        - Did they enter because they saw a valid reversal, or just because they were scared of missing out (FOMO)?
        - Check for **Consistency**: Did they tag it "Good Process" but entered against the trend? Call them out.
        
        # NEGATIVE CONSTRAINTS
        - IGNORE Indicators like RSI, MACD. Focus on Price, Volume, and EMAs.
        - Don't be a robot. If a trade makes sense logically but misses a specific rule slightly, acknowledge the nuance.
        
        # DYNAMIC INPUTS
        {manifesto_part}
        {strategy_part}
        {memory_text}
        
        # OUTPUT FORMAT (Markdown in Simplified Chinese)
        **IMPORTANT: Output in Simplified Chinese.**
        
        Structure:
        - **⚖️ 审计结论**: [优 / 良 / 差 / 严重违规] (给出一个定性的评价)
        - **🧠 价格行为深度解析**: (Use your full PA knowledge. Describe the buying/selling pressure. Why did this setup work or fail?)
        - **📉 结构与趋势**: (Was it with the Vegas trend? Was the pullback healthy?)
        - **🧘 知行合一检查**: (Compare Notes vs. Reality)
        - **💡 改进建议**: (How to optimize the entry timing or location?)
        """
        
        messages = [{"role": "system", "content": system_prompt}]
        
        # 处理图片 (视觉模型)
        support_vision_models = ["gpt-4o", "gemini", "claude", "vision"]
        can_see_image = any(m in model_name.lower() for m in support_vision_models)
        if "deepseek" in model_name.lower(): can_see_image = False
        
        base64_image = encode_image(image_path)
        
        if base64_image and can_see_image:
            user_content = [
                {"type": "text", "text": f"这是这笔交易的详细记录和K线截图，请审计：\n{context_text}"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
            ]
        else:
            user_content = f"请审计这笔交易 (无图模式)：\n{context_text}"
        
        messages.append({"role": "user", "content": user_content})
        
        api_params = {
            "model": model_name,
            "messages": messages,
            "timeout": 90
        }
        if "reasoner" not in model_name.lower():
            api_params["temperature"] = 0.7
            
        response = call_api_with_retry(client, api_params)
        return response.choices[0].message.content
    
    except Exception as e:
        return f"审计失败: {str(e)}"

def generate_batch_review_v3(api_key, base_url, trades_df, system_manifesto="", report_type="最近30笔", model_name="deepseek-chat", related_memories=[]):
    """
    v7.2 周期性审计：Vegas 刚柔并济版 (Rigid Trend + Fluid PA)
    """
    try:
        if trades_df.empty:
            return "数据不足"
        
        client = get_client(api_key, base_url)
        
        # === 1. 保留核心心理统计 (Do Not Delete) ===
        total_trades = len(trades_df)
        # 知行合一率 (基于 Process 标签)
        good_process_count = len(trades_df[trades_df['process_tag'].str.contains("Good", na=False)])
        process_adherence = (good_process_count / total_trades) * 100 if total_trades > 0 else 0
        # 情绪化交易 (基于 Mental State 标签)
        fomo_count = len(trades_df[trades_df['mental_state'].str.contains("FOMO|Tilt|Revenge", na=False, case=False)])
        
        # 基础盈亏
        total_pnl = trades_df['net_pnl'].sum()
        win_count = len(trades_df[trades_df['net_pnl'] > 0])
        win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0
        
        # === 2. 构建交易流水 (增强版) ===
        trades_summary = []
        for _, t in trades_df.iterrows():
            date_str = str(t.get('close_date_str', 'N/A'))
            short_time = date_str[5:] if len(date_str) > 10 else date_str
            pnl_str = f"{t.get('net_pnl', 0):+.0f}"
            
            # 提取关键信息供 AI 分析
            line = (
                f"| {short_time} | {t.get('symbol')} | {t.get('direction')} | {pnl_str}U | "
                f"策略:{t.get('strategy', '-')} | "
                f"心态:{t.get('mental_state', '-')} | "
                f"执行:{t.get('process_tag', '-')} | "
                f"笔记:{str(t.get('notes', ''))[:30]}..."
            )
            trades_summary.append(line)
        
        trades_text = "\n".join(trades_summary)
        
        # === 3. 记忆回溯 (RAG) ===
        memory_text = ""
        if related_memories:
            mem_list = [f"- {m['note']}" for m in related_memories]
            memory_block = "\n".join(mem_list[:3])
            memory_text = f"【历史顽疾档案】:\n{memory_block}"
        
        # === 4. Prompt 升级：刚性趋势 + 柔性博弈 ===
        system_prompt = f"""
        # ROLE
        You are the **Vegas-Brooks Portfolio Manager**. You are auditing the trader's recent performance.
        
        # 1. THE RIGID LAWS (Trend & Risk)
        - **Major Trend:** We ONLY trade WITH the 288/338 EMA. (No fighting the river).
        - **Value Zone:** We wait for setups near the 144/169 Tunnel.
        - **Risk Control:** Stop losses must be respected.
        
        # 2. THE FLUID LOGIC (Structure Quality)
        **Do NOT just count 'High 2' patterns.** Use your Price Action knowledge to evaluate the **Quality of Execution**:
        - **Sniper vs. Machine Gun:** Did the trader wait for high-quality structures (e.g., Wedges, Tight Flags, Momentum Shifts) at the tunnel? Or did they enter randomly (Machine Gun mode)?
        - **Patience:** Look at the "Notes". Did they mention "Waiting", "Confirmation"?
        - **Adaptability:** Did they adapt to market context, or force a setup where there was none?
        
        # USER'S MANIFESTO
        "{system_manifesto}"
        
        {memory_text}
        
        # EXECUTION DATA (Psych Stats)
        - **Self-Rated Process Adherence**: {process_adherence:.1f}% 
        - **Emotional Trades (FOMO)**: {fomo_count} times
        - **Win Rate**: {win_rate:.1f}% | PnL: ${total_pnl:.2f}
        
        # YOUR AUDIT TASKS
        Review the "Trade Log" and "Execution Data". Generate a report in **Simplified Chinese**.
        
        **1. Trend Loyalty (趋势忠诚度 - Rigid):**
        - Is the trader swimming with the current or fighting it?
        
        **2. Structure Quality (结构质量 - Fluid):**
        - Analyze the logic behind the trades. Are they entering on **Logic (Price Action)** or **Impulse (FOMO)**?
        - Comment on their ability to identify "Supply/Demand imbalances" vs just "hoping".
        
        **3. Psychology & Consistency:**
        - Cross-check: The user claims {process_adherence:.1f}% compliance. Does the PnL and trade frequency support this?
        - Are losses caused by "System Cost" (Good trades that failed) or "Discipline Collapse" (Bad trades)?
        
        # OUTPUT FORMAT (Markdown in Chinese)
        ## 🏥 Vegas 周期体检报告 ({report_type})
        
        **📊 核心看板**:
        - 盈亏: ${total_pnl:.2f} (胜率 {win_rate:.1f}%)
        - **狙击手指数**: [0-10分] (评价等待优质结构的耐心)
        - **心理稳定性**: [0-10分] (基于 FOMO 次数和知行合一率)
        
        **🔍 深度洞察**:
        1. **趋势大局观**: ...
        2. **结构与择时**: (重点分析是凭逻辑做单还是凭感觉做单)
        3. **主要失血点**: (区分是系统内亏损还是胡乱亏损)
        
        **💊 处方**:
        (给出 2 条建议：一条关于技术精进，一条关于心态控制)
        """
        
        # 5. 调用 AI
        api_params = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Trade Log:\n{trades_text}"}
            ],
            "timeout": 120
        }
        
        if "reasoner" not in model_name.lower():
            api_params["temperature"] = 0.5  # 保持一定的灵活性
            
        response = client.chat.completions.create(**api_params)
        return response.choices[0].message.content
    except Exception as e:
        return f"周期审计失败: {str(e)}"

# 保留旧版本函数以保持兼容性
def get_ai_analysis(api_key, base_url, trade_data, user_notes=""):
    """
    调用 AI 对交易进行点评（单笔交易，旧版本兼容）。
    """
    try:
        client = get_client(api_key, base_url)
        
        prompt_data = f"""
        【交易信息】
        - 标的: {trade_data.get('symbol', 'N/A')}
        - 方向: {trade_data.get('direction', 'N/A')} (Long=做多, Short=做空)
        - 开仓时间: {trade_data.get('open_date', 'N/A')}
        - 持仓时间: {trade_data.get('duration_min', 'N/A')} 分钟
        - 净盈亏: {trade_data.get('net_pnl', 0)} U
        - 手续费磨损: {trade_data.get('total_fee', 0)} U
        - 交易员的复盘笔记: "{user_notes}"
        """
        
        system_prompt = """
        你是一位拥有20年经验的华尔街顶级交易员导师。你的风格是：
        1. **极度严厉**：不要客套，不要鼓励，直接指出愚蠢之处。
        2. **一针见血**：关注盈亏比、持仓时间与收益的效率、以及手续费磨损。
        3. **关注心理**：如果交易员写了笔记，分析他的心理状态是否失控（如FOMO、扛单）。
        4. **简短有力**：控制在 200 字以内，用列表形式输出 3 个关键改进点。
        
        如果这笔交易亏损了，请严厉批评他的入场或风控。
        如果这笔交易盈利了但逻辑不对，也要敲打他不要靠运气赚钱。
        """
        
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"请点评这笔交易：\n{prompt_data}"}
            ],
            temperature=0.7,
            timeout=30
        )
        
        return response.choices[0].message.content
    
    except Exception as e:
        return f"AI 大脑短路了：{str(e)}"

def generate_batch_review(api_key, base_url, trades_df, report_type="最近30笔交易"):
    """
    批量分析交易，寻找行为模式（旧版本兼容）。
    """
    try:
        if trades_df.empty:
            return "❌ 没有足够的交易数据进行分析。"
        
        client = get_client(api_key, base_url)
        
        trades_summary = []
        for _, t in trades_df.iterrows():
            close_date_str = str(t.get('close_date_str', ''))
            if close_date_str and len(close_date_str) > 10:
                short_time = close_date_str[5:]
            else:
                short_time = close_date_str
            
            pnl_emoji = "✅" if t.get('net_pnl', 0) > 0 else "❌"
            
            notes = str(t.get('notes', ''))[:50]
            if notes and notes != 'nan':
                notes_display = f"笔记:{notes}"
            else:
                notes_display = "无笔记"
            
            trade_str = (
                f"[{short_time}] {t.get('symbol', 'N/A')} {t.get('direction', 'N/A')} | "
                f"持仓:{t.get('duration_str', 'N/A')} | {pnl_emoji} ${t.get('net_pnl', 0):.1f} | "
                f"{notes_display}"
            )
            trades_summary.append(trade_str)
        
        trades_context = "\n".join(trades_summary)
        
        total_pnl = trades_df['net_pnl'].sum()
        win_count = len(trades_df[trades_df['net_pnl'] > 0])
        win_rate = (win_count / len(trades_df)) * 100 if len(trades_df) > 0 else 0
        max_loss = trades_df['net_pnl'].min()
        
        stats_context = f"""
        【本期数据概览】
        - 总盈亏: ${total_pnl:.2f}
        - 胜率: {win_rate:.1f}%
        - 单笔最大亏损: ${max_loss:.2f}
        - 交易笔数: {len(trades_df)}
        """
        
        system_prompt = """
        你是一名华尔街顶级对冲基金的风控总监，性格冷酷、毒舌，但极其专业。你的职责是审查交易员的近期表现，找出他们的人性弱点。
        
        请阅读提供的【交易流水】和【统计数据】，完成一份《交易行为诊断报告》。
        
        ### 分析维度要求：
        1. **寻找"上头"迹象**：检查是否有短时间内连续亏损且频繁开仓的行为（急于回本）。
        2. **盈亏同源分析**：如果他赚钱了，是靠运气（扛单、重仓）还是靠逻辑？如果是运气，请狠狠批评。
        3. **持仓一致性**：检查赚钱的单子是不是拿不住，亏钱的单子是不是死扛。
        4. **笔记审查**：如果交易员写了笔记，分析他的心态是否客观。
        
        ### 输出格式（Markdown）：
        ## 🩸 核心诊断
        （用一句话概括他这段时间的表现，比如"典型的赌徒心态"或"纪律执行不错"）
        
        ## 🔍 行为模式发现
        1. **...**
        2. **...**
        3. **...**
        
        ## 💊 改进处方
        （给出2条具体建议，不要熬鸡汤，要给具体指令，比如"停止在该时间段交易"或"缩减手数"）
        
        ## ⚠️ 导师评级
        （从 S/A/B/C/D 中给出一个评级，D代表无可救药）
        """
        
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"请分析以下数据：\n\n{stats_context}\n\n【交易流水明细】\n{trades_context}"}
            ],
            temperature=0.5,
            timeout=60
        )
        
        return response.choices[0].message.content
    except Exception as e:
        return f"批量分析失败: {str(e)}"

def review_potential_trade(api_key, base_url, plan_data, system_manifesto, model_name="deepseek-chat", related_memories=[]):
    """
    v7.2 事前风控：刚性规则 + 柔性逻辑 (Rigid Rules + Fluid Logic)
    """
    try:
        client = get_client(api_key, base_url)
        
        # 1. 基础数学计算
        entry = float(plan_data['entry'])
        sl = float(plan_data['sl'])
        tp = float(plan_data['tp'])
        risk_money = float(plan_data['risk_money'])
        
        direction = "Long" if entry > sl else "Short"
        risk_per_share = abs(entry - sl)
        if risk_per_share == 0: return "❌ 止损价无效"
        
        qty = risk_money / risk_per_share
        position_value = qty * entry
        rr_ratio = abs(tp - entry) / risk_per_share
        
        # 2. 记忆上下文
        memory_text = ""
        if related_memories:
            mem_list = [f"- {m['meta']['date']}: {m['note']}" for m in related_memories]
            memory_block = "\n".join(mem_list[:3])
            memory_text = f"【历史相关教训】:\n{memory_block}"
        
        # 3. 交易计划上下文
        context = f"""
        【拟定交易计划】
        - 方向: {direction} | 标的: {plan_data['symbol']}
        - 价格: 入场 {entry} | 止损 {sl} | 止盈 {tp}
        - 资金: 风险 ${risk_money} | 仓位价值 ${position_value:.2f}
        - 盈亏比: {rr_ratio:.2f}R
        """
        
        # 4. Prompt 升级：刚性防线 + 柔性审核
        system_prompt = f"""
        You are the **Vegas-Brooks Risk Gatekeeper**. You are evaluating a live trade plan.
        
        # YOUR PHILOSOPHY
        - **Trend is King:** Respect the Vegas Tunnel (144/169/288/338).
        - **Price Action is Queen:** We need a reason to enter, but it doesn't have to be a perfect textbook pattern.
        
        # EVALUATION CRITERIA (The Checkpoint)
        1. **Context (Location - Rigid):** - Is the price at a "Value Area" (Vegas Tunnel)? 
           - Or are we chasing in the middle of nowhere (Extended)?
           
        2. **Story of Price (Structure - Fluid):** - **Exhaustion:** Is the selling pressure drying up? (Small candles, tails).
           - **Structure:** Is there a recognizable pattern? (Wedge, Flag, Micro Double Bottom, VCP).
           - **Logic Check:** Does this trade imply "Buying Low in an Uptrend" (Good) or "Catching a Knife" (Bad)?
           - Use your autonomous judgment: Does the Supply/Demand balance favor this trade?
           
        3. **Risk Logic (Rigid):** R:R must be >= 1.5.
        
        # USER'S MANIFESTO (Personal Laws)
        The user has sworn to follow these rules. Enforce them:
        "{system_manifesto}"
        {memory_text}
        
        # OUTPUT FORMAT (Markdown in Simplified Chinese)
        **IMPORTANT: Output in Simplified Chinese.**
        
        **🛑 最终裁决**: [批准 / 需谨慎 / 拒绝]
        **🧠 逻辑推演**: (Explain the Price Action story. Why is this a good/bad spot? Describe the "Force" of the market.)
        **⚖️ 盈亏比检查**: (Value)
        **💡 交易员建议**: (Short, punchy advice based on live PA, e.g. "Wait for the 5m candle close")
        """
        
        # 调用 AI
        api_params = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"请审查这笔计划：\n{context}"}
            ],
            "timeout": 60
        }
        if "reasoner" not in model_name.lower():
            api_params["temperature"] = 0.3 # 风控稍微严谨一点
            
        response = client.chat.completions.create(**api_params)
        return response.choices[0].message.content
    except Exception as e:
        return f"风控审查失败: {str(e)}"

def analyze_live_positions(api_key, base_url, positions_data, system_manifesto, model_name="deepseek-chat", related_memories=[]):
    """
    v6.0 事中风控：实时持仓分析（支持 RAG 记忆）
    """
    try:
        # 防御性 URL 修正 (针对 Google Gemini)
        if "generativelanguage" in base_url and "openai" not in base_url:
            if base_url.endswith("/"): 
                base_url += "openai/"
            else:
                base_url += "/openai/"
        
        client = get_client(api_key, base_url)
        
        equity = positions_data['equity']
        positions = positions_data['positions']
        
        if not positions:
            return "✅ 当前空仓，心态平和，静待机会。"
            
        # 1. 构建持仓摘要
        pos_str_list = []
        total_unrealized_pnl = 0
        
        for p in positions:
            total_unrealized_pnl += p['pnl']
            roi_emoji = "🔥" if p['roi'] < -20 else ("🟢" if p['roi'] > 0 else "🔴")
            pos_str_list.append(
                f"- {p['symbol']} ({p['side']} x{p['leverage']}): "
                f"浮盈亏 ${p['pnl']:.2f} ({p['roi']:.2f}%) {roi_emoji} | "
                f"开仓 {p['entry_price']} -> 现价 {p['mark_price']}"
            )
            
        pos_context = "\n".join(pos_str_list)
        risk_exposure = (total_unrealized_pnl / equity) * 100
        
        # === 🧠 构建记忆上下文 ===
        memory_text = ""
        if related_memories:
            mem_list = [f"- {m['note']} (PnL: {m['meta']['pnl']}U, MAE: {m['meta']['mae']:.2f}R)" for m in related_memories]
            memory_block = "\n".join(mem_list)
            memory_text = f"""

【⚠️ 既视感警报 (RAG)】
目前的持仓状态让我想起了你过去的这些经历：

{memory_block}

"""
        
        context = f"""
        【当前账户实时快照】
        - 账户净值: ${equity:.2f}
        - 当前浮动盈亏: ${total_unrealized_pnl:.2f} (风险敞口: {risk_exposure:.2f}%)
        
        【持仓明细】
        {pos_context}
        """
        
        # 2. 系统提示词
        system_prompt = f"""
        你是一名【实时交易战术顾问】。交易员正在持仓，可能正处于情绪波动中。
        
        【系统宪法 (他的铁律)】:
        "{system_manifesto}"
        
        {memory_text}
        
        请根据当前持仓和**历史教训**进行**紧急战术指导**：
        1. **风险对比**：现在的浮亏/浮盈是否像极了历史上亏大钱/卖飞的那一次？如果是，请给出明确指令（平仓/减仓/推止损）。
        2. **风险警报**：如果浮亏过大（尤其是接近宪法止损线），请大声喝止他，让他立刻行动。
        3. **浮盈管理**：如果浮盈很大，提醒他注意移动止损或分批止盈，不要贪婪（参考宪法）。
        4. **情绪管理**：如果历史显示他在这种浮亏下容易上头，请警告他冷静。
        5. **杠杆/重仓**：检查他是否违背了仓位管理原则。
        请用简短、有力、命令式的语气。不要废话。
        """
        
        # 3. 调用 API
        api_params = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"请分析我的实时持仓：\n{context}"}
            ],
            "timeout": 30
        }
        
        if "reasoner" not in model_name:
            api_params["temperature"] = 0.3
        
        response = call_api_with_retry(client, api_params)
        return response.choices[0].message.content
    except Exception as e:
        return f"实时分析失败: {str(e)}"
