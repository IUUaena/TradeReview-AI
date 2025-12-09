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
    v7.0 自动分析版：AI 自动分析 Vegas 趋势和卖飞情况，无需前端手动传递
    增强版：修复 float(None) 崩溃问题
    """
    try:
        # === 1. 数据清洗 (关键步骤) ===
        # 定义一个内部函数，安全地从字典获取数据，如果是 None 则返回默认值
        def safe_get(key, default):
            val = trade_data.get(key)
            return val if val is not None else default
        
        # 获取关键字段，防止 None 传给后续函数
        symbol = safe_get('symbol', 'Unknown')
        direction = safe_get('direction', 'Long')
        price = safe_get('price', 0)
        
        # 时间戳处理：防止 None 导致 int() 报错
        open_ts = safe_get('open_time', None)
        close_ts = safe_get('close_time', None)
        if not open_ts: 
            open_ts = int(datetime.now().timestamp() * 1000)
        if not close_ts: 
            close_ts = open_ts
        
        # 直接使用传入的 base_url，不乱改
        client = get_client(api_key, base_url)
        
        # ============ 🧠 v7.0 新增：AI 自动分析 ============
        # 创建 AI 助手实例，让它自动分析趋势和卖飞情况
        ai_helper = AIAssistant(api_key=api_key, base_url=base_url)
        
        # 1. 运行分析 (传入清洗后的数据)
        trend_context = ai_helper._analyze_vegas_trend(symbol, open_ts)
        what_if_result = ai_helper._analyze_missed_profit(symbol, direction, close_ts, price)
        # ====================================================
        
        # 2. 准备数据 (防空护盾)
        t = trade_data
        net_pnl = safe_get('net_pnl', 0)
        try: 
            net_pnl = float(net_pnl) 
        except: 
            net_pnl = 0.0
        
        pnl_emoji = "✅" if net_pnl > 0 else "❌"
        
        def safe_num(val, decimals=2):
            if val is None or str(val).lower() in ['nan', 'none', '', 'null']: return "N/A"
            try: 
                return f"{float(val):.{decimals}f}"
            except: 
                return "N/A"
        
        def safe_str(val, default="无"):
            if val is None or str(val).lower() in ['nan', 'none', '', 'null']: return default
            return str(val).strip() or default
        
        mae = t.get('mae')
        mfe = t.get('mfe')
        metrics_text = "【微观数据】: 暂无详细指标 (请点击'🚀 计算指标')"
        
        if mae is not None and str(mae) != 'nan':
            metrics_text = f"""
        【微观数据】
        - R倍数: MAE -{safe_num(mae)}R | MFE +{safe_num(mfe)}R
        - 心理压力: 痛苦时长 {safe_num(t.get('mad'), 0)}min | 抗单 {safe_num(t.get('mae_atr'), 1)}x ATR
        - 量价结构: RVOL {safe_num(t.get('rvol'))} | 结构 {safe_str(t.get('structure_info'), "未检测")}
        - 入场信号: {safe_str(t.get('pattern_signal'), "无显著形态")}
        - 交易质量: 效率 {safe_num(t.get('efficiency'))}
        """
        
        context_text = f"""
        【交易档案】
        - 标的: {safe_str(t.get('symbol'))} ({safe_str(t.get('direction'))})
        - 结果: {pnl_emoji} ${safe_num(net_pnl)}
        - 时间: {safe_str(t.get('open_date_str'))}
        
        {metrics_text}
        
        【上帝视角】
        - 宏观趋势: {trend_context}
        - 离场评价: {what_if_result}
        
        【交易者笔记】
        策略: {safe_str(t.get('strategy'))}
        心态: {safe_str(t.get('mental_state'))}
        复盘: {safe_str(t.get('notes'))}
        """
        
        # === 构建 RAG 记忆上下文 ===
        memory_text = ""
        if related_memories:
            memory_list = []
            for m in related_memories:
                meta = m['meta']
                # 格式化一条历史记忆
                memory_list.append(
                    f"- 历史教训 ({meta['date']}): 做了 {meta['symbol']}，结果 {meta['pnl']}U。\n"
                    f"  当时笔记: \"{m['note']}\"\n"
                    f"  心态: {meta['mental_state']} | 策略: {meta['strategy']}"
                )
            memory_block = "\n".join(memory_list)
            memory_text = f"""

【你的长期记忆 (RAG)】
我检索到了你过去处理类似情况的记录，请参考这些"前车之鉴"来点评当前交易：

{memory_block}

"""
        else:
            memory_text = "【长期记忆】: 暂无相关历史记录。"
        
        # 2. 构建 System Prompt
        manifesto_part = f"【系统宪法】: {system_manifesto}" if system_manifesto else ""
        strategy_part = f"【策略定义】: {strategy_rules}" if strategy_rules else ""
        
        system_prompt = f"""
        你是一名华尔街顶级交易员教练。请根据以下数据进行审计。
        
        {manifesto_part}
        {strategy_part}
        {memory_text}
        
        审计逻辑：
        1. **宏观与择时**：参考【上帝视角】的 Vegas 趋势。
        2. **结构与位置**：如果结构显示"逼近阻力位"却做多，严厉批评。
        3. **入场依据**：检查入场信号。如果是"无显著形态"，批评其随机交易。
        4. **执行质量**：结合 MAD(痛苦时长) 和 卖飞情况进行点评。
        """
        
        messages = [{"role": "system", "content": system_prompt}]
        
        # --- 3. 智能判断：该模型是否支持看图？ ---
        # 只有这些模型才发送图片数据
        support_vision_models = ["gpt-4o", "gemini", "claude", "vision"]
        can_see_image = any(m in model_name.lower() for m in support_vision_models)
        
        # 特殊排除：DeepSeek 即使名字里没写 text，目前也不支持图片
        if "deepseek" in model_name.lower():
            can_see_image = False
        
        base64_image = encode_image(image_path)
        
        if base64_image and can_see_image:
            # === 视觉模式 (Vision Mode) ===
            image_ext = os.path.splitext(image_path)[1].lower() if image_path else '.jpeg'
            mime_type = mimetypes.guess_type(image_path)[0] if image_path else 'image/jpeg'
            if not mime_type:
                # 根据扩展名判断
                if image_ext in ['.png']:
                    mime_type = 'image/png'
                elif image_ext in ['.jpg', '.jpeg']:
                    mime_type = 'image/jpeg'
                elif image_ext in ['.gif']:
                    mime_type = 'image/gif'
                else:
                    mime_type = 'image/jpeg'  # 默认
            
            user_content = [
                {"type": "text", "text": f"这是这笔交易的详细记录和K线截图，请审计：\n{context_text}"},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{base64_image}",
                        "detail": "high"
                    }
                }
            ]
            print(f"👁️ 正在发送视觉请求 (Model: {model_name})...")
        else:
            # === 纯文本模式 (Text Mode) ===
            # DeepSeek 或无图时走这里
            user_content = f"请审计这笔交易 (截图不可用或模型不支持)：\n{context_text}"
            print(f"📝 正在发送纯文本请求 (Model: {model_name})...")
        
        messages.append({"role": "user", "content": user_content})
        
        # 🟢 关键：使用传入的 model_name
        print(f"DEBUG: Calling model -> {model_name}")
        
        # 4. 发送请求 (带重试)
        api_params = {
            "model": model_name,
            "messages": messages,
            "timeout": 90
        }
        
        # DeepSeek Reasoner 不加 temperature
        if "reasoner" not in model_name.lower():
            api_params["temperature"] = 0.7
        
        response = call_api_with_retry(client, api_params)
        return response.choices[0].message.content
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return f"审计失败: {str(e)} (建议检查数据完整性或API连接)"

def generate_batch_review_v3(api_key, base_url, trades_df, system_manifesto="", report_type="最近30笔", model_name="deepseek-chat", related_memories=[]):
    """
    v5.0 批量诊断：结合历史记忆生成报告
    """
    try:
        if trades_df.empty:
            return "数据不足"
        
        client = get_client(api_key, base_url)
        
        # 1. 高级统计 (统计 v3.0 新字段)
        total_trades = len(trades_df)
        good_process_count = len(trades_df[trades_df['process_tag'].str.contains("Good", na=False)])
        fomo_count = len(trades_df[trades_df['mental_state'].str.contains("FOMO|Tilt|Revenge", na=False, case=False)])
        process_adherence = (good_process_count / total_trades) * 100 if total_trades > 0 else 0
        
        # 2. 构建精简摘要 (新增 MAE/MFE)
        trades_summary = []
        for _, t in trades_df.iterrows():
            close_date_str = str(t.get('close_date_str', ''))
            if close_date_str and len(close_date_str) > 10:
                short_time = close_date_str[5:]
            else:
                short_time = close_date_str
            
            pnl_sign = "+" if t.get('net_pnl', 0) > 0 else ""
            
            # 格式化 MAE/MFE
            mae_val = t.get('mae')
            mfe_val = t.get('mfe')
            pa_str = ""
            if mae_val is not None and str(mae_val) != 'nan':
                pa_str = f"| MAE:{float(mae_val):.1f}% MFE:{float(mfe_val):.1f}%"
            
            # 格式: [时间] 盈亏 | 心态 | 执行 | MAE/MFE
            line = (f"[{short_time}] {pnl_sign}{t.get('net_pnl', 0):.0f}U | "
                    f"心态:{t.get('mental_state', '-')} | "
                    f"执行:{t.get('process_tag', '-')} "
                    f"{pa_str}")
            trades_summary.append(line)
        
        trades_text = "\n".join(trades_summary)
        
        # === 🧠 构建记忆上下文 ===
        memory_text = ""
        if related_memories:
            # 这里的记忆可能是"一般性的长期错误模式"
            mem_list = [f"- {m['note']}" for m in related_memories]
            memory_block = "\n".join(mem_list[:5])  # 只取前5条避免太长
            memory_text = f"""

【长期顽疾档案 (RAG)】
我们在数据库中检索到了你长期以来的典型错误模式，请对比本次报告进行验证：

{memory_block}

"""
        
        # 3. 导师人设
        system_prompt = f"""
        你是一名交易教练。请根据【本期交易流水】和【长期顽疾档案】生成诊断报告。
        
        【系统宪法】: {system_manifesto if system_manifesto else "未提供"}
        
        {memory_text}
        
        【执行数据】
        - 知行合一率 (Good Process): {process_adherence:.1f}% (低于80%是不合格的)
        - 情绪化交易次数 (FOMO/上头): {fomo_count} 次
        
        请生成一份《深度行为诊断报告》，重点分析：
        1. **旧病复发检测**：他在本期交易中，是否又犯了档案里记录的那些老毛病？
        2. **进步确认**：如果本期没有犯老毛病，请给予肯定。
        3. **亏损归因**：他的亏损主要是因为"乱做(Bad Process)"还是"系统成本"？
        4. **情绪与盈亏**：当他处于 FOMO 或上头状态时，结局通常如何？
        5. **深度归因**：结合 RAG 记忆，分析亏损的根源是技术问题还是心理顽疾。
        6. **系统宪法执行度**：他是否在知行合一？
        
        请用严厉、专业、一针见血的语气。
        """
        
        # v3.5: 支持 reasoner 模型
        api_params = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"交易流水：\n{trades_text}"}
            ],
            "timeout": 120  # 推理模型可能较慢，增加超时时间
        }
        
        # ⚠️ 针对 deepseek-reasoner 的特殊处理：不支持 temperature 参数
        if "reasoner" not in model_name.lower():
            api_params["temperature"] = 0.5
        
        response = client.chat.completions.create(**api_params)
        
        return response.choices[0].message.content
    
    except Exception as e:
        return f"批量分析失败: {str(e)}"

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
    v5.0 事前风控：审查潜在交易计划（支持 RAG 记忆）
    """
    try:
        client = get_client(api_key, base_url)
        
        # 1. 计算盈亏比和风险
        entry = float(plan_data['entry'])
        sl = float(plan_data['sl'])
        tp = float(plan_data['tp'])
        risk_money = float(plan_data['risk_money'])
        
        # 自动识别方向
        direction = "做多 (Long)" if entry > sl else "做空 (Short)"
        
        # 计算潜在亏损幅度和盈亏比
        risk_per_share = abs(entry - sl)
        reward_per_share = abs(tp - entry)
        
        if risk_per_share == 0: 
            return "❌ 止损价不能等于开仓价"
        
        rr_ratio = reward_per_share / risk_per_share
        
        # 建议仓位 (以损定仓公式)
        # 数量 = 风险金额 / 单股止损差价
        qty = risk_money / risk_per_share
        position_value = qty * entry
        
        # 计算止损距离百分比
        if entry > 0:
            stop_distance_pct = abs(entry - sl) / entry * 100
        else:
            stop_distance_pct = 0
        
        # === 🧠 构建记忆上下文 ===
        memory_text = ""
        if related_memories:
            mem_list = [f"- {m['meta']['date']} {m['meta']['symbol']}: {m['note']}" for m in related_memories]
            memory_block = "\n".join(mem_list)
            memory_text = f"""

【⚠️ 历史警示 (RAG)】
在你过去的操作中，我发现了以下相关教训，请务必对照检查本次计划是否重犯：

{memory_block}

"""
        else:
            memory_text = "【历史记忆】: 暂无特定风险记录。"
        
        # 2. 构建审查 prompt
        context = f"""
        【拟定交易计划】
        - 方向: {direction}
        - 标的: {plan_data['symbol']}
        - 入场价: {entry}
        - 止损价: {sl} (距离 {stop_distance_pct:.2f}%)
        - 止盈价: {tp}
        - 计划风险金额: ${risk_money} (以损定仓)
        - 盈亏比 (R:R): {rr_ratio:.2f}
        - 建议开仓数量: {qty:.4f} 个
        - 建议持仓价值: ${position_value:.2f}
        """
        
        system_prompt = f"""
        你是一名严格的【交易风控官】。请审查以下"拟定交易计划"。
        
        【系统宪法 (必须遵守的铁律)】:
        "{system_manifesto}"
        
        {memory_text}
        
        请进行事前拦截检查：
        1. **历史一致性**：如果历史记忆显示他经常在类似位置/币种上亏损，请大声喝止。
        2. **盈亏比检查**：R:R 是否符合宪法要求？（通常要求 > 2.0 或 3.0）
        3. **止损合理性**：止损幅度是否过窄（容易被打）或过宽？
        4. **风险一致性**：这笔交易是否符合顺势/逆势的逻辑（如果宪法里提到了）？
        
        ### 输出格式：
        **🛑 审查结果**：(通过 / 拒绝 / 需谨慎)
        
        **⚖️ 盈亏比评价**：(如 "R:R 1.5 太低，建议放弃")
        
        **🧠 记忆回溯点评**：(如果有关联记忆，对比历史教训进行点评)
        
        **🛡️ 仓位建议**：(确认计算出的仓位是否合理)
        
        **💡 导师建议**：(一句话点评)
        """
        
        # v3.5: 支持 reasoner 模型
        api_params = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"请审查这笔计划：\n{context}"}
            ],
            "timeout": 60  # 推理模型可能较慢，增加超时时间
        }
        
        # ⚠️ 针对 deepseek-reasoner 的特殊处理：不支持 temperature 参数
        if "reasoner" not in model_name.lower():
            api_params["temperature"] = 0.3
        
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
