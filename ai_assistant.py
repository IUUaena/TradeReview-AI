from openai import OpenAI
import pandas as pd
import json

def get_client(api_key, base_url):
    return OpenAI(api_key=api_key, base_url=base_url)

def audit_single_trade(api_key, base_url, trade_data, system_manifesto=""):
    """
    v3.0 单笔交易审计：结合心理、评分、执行质量进行深度点评
    """
    try:
        client = get_client(api_key, base_url)
        
        # 1. 构建数据快照
        t = trade_data
        pnl_emoji = "💰 盈利" if t.get('net_pnl', 0) > 0 else "💸 亏损"
        
        # 核心：构建一个"诚实的数据包"
        context = f"""
        【交易档案】
        - 标的/方向: {t.get('symbol', 'N/A')} ({t.get('direction', 'N/A')})
        - 结果: {pnl_emoji} ${t.get('net_pnl', 0):.2f}
        - 持仓时间: {t.get('duration_str', 'N/A')}
        
        【自我评估 (交易员自述)】
        - 心理状态: {t.get('mental_state', '未记录')}
        - 机会评分: {t.get('setup_rating', 'N/A')}/10
        - 执行定性: {t.get('process_tag', '未记录')}
        - 犯错标签: {t.get('mistake_tags', '无')}
        - 预期盈亏比: {t.get('rr_ratio', 0)}
        - 策略依据: {t.get('strategy', '未填写')}
        - 复盘笔记: "{t.get('notes', '未填写')}"
        """
        
        # 2. 系统宪法 (如果有)
        manifesto_prompt = ""
        if system_manifesto:
            manifesto_prompt = f"""
            【交易员的系统宪法 (Rulebook)】
            这是该交易员誓死遵守的规则，请据此审查他是否违规：
            "{system_manifesto}"
            """
        
        # 3. 审计师人设 (Auditor Persona)
        system_prompt = f"""
        你是一名铁面无私的【交易审计师】。你的任务不是预测市场，而是审计"执行一致性"。
        
        {manifesto_prompt}
        请根据交易员的【自我评估】和【交易结果】，进行逻辑审计。
        
        ### 审计逻辑：
        1. **过程 vs 结果**：
           - 如果他标记 "Bad Process" 但赚钱了，请严厉警告这是"有毒的利润"。
           - 如果他标记 "Good Process" 但亏钱了，请给予肯定和鼓励，这是系统的成本。
           - 如果心理状态是 "FOMO/Tilt" 且亏损，请无情地指出这是情绪的代价。
        
        2. **知行合一检查**：
           - 检查他的复盘笔记和策略是否矛盾。
           - 检查他的预期盈亏比是否合理。
           
        ### 输出格式：
        **👮 审计结论**： (一句话定性，如"标准的纪律性亏损"或"危险的运气单")
        
        **📉 关键漏洞**： (指出1-2个具体问题)
        
        **💡 改进建议**： (结合他的系统宪法给出建议)
        """
        
        # 4. 发送请求
        response = client.chat.completions.create(
            model="deepseek-chat", # 推荐 DeepSeek-V3
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"请审计这笔交易：\n{context}"}
            ],
            temperature=0.3, # 审计需要严谨，低随机性
            timeout=45
        )
        
        return response.choices[0].message.content
    
    except Exception as e:
        return f"审计失败: {str(e)}"

def generate_batch_review_v3(api_key, base_url, trades_df, system_manifesto="", report_type="最近30笔"):
    """
    v3.0 批量诊断：统计"知行合一率"，寻找亏损模式
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
        
        # 2. 构建精简摘要 (只发 AI 需要的模式识别数据)
        trades_summary = []
        for _, t in trades_df.iterrows():
            close_date_str = str(t.get('close_date_str', ''))
            if close_date_str and len(close_date_str) > 10:
                short_time = close_date_str[5:]
            else:
                short_time = close_date_str
            
            pnl_sign = "+" if t.get('net_pnl', 0) > 0 else ""
            
            # 格式: [时间] 盈亏 | 心态 | 执行 | 错误
            line = (f"[{short_time}] {pnl_sign}{t.get('net_pnl', 0):.0f}U | "
                    f"心态:{t.get('mental_state', '-')} | "
                    f"执行:{t.get('process_tag', '-')} | "
                    f"错:{t.get('mistake_tags', '')}")
            trades_summary.append(line)
        
        trades_text = "\n".join(trades_summary)
        
        # 3. 导师人设
        system_prompt = f"""
        你是一名行为金融学专家和交易教练。请阅读以下【{total_trades}笔交易流水】。
        
        【系统宪法】: {system_manifesto if system_manifesto else "未提供"}
        
        【执行数据】
        - 知行合一率 (Good Process): {process_adherence:.1f}% (低于80%是不合格的)
        - 情绪化交易次数 (FOMO/上头): {fomo_count} 次
        
        请生成一份《深度行为诊断报告》，重点分析：
        1. **亏损归因**：他的亏损主要是因为"乱做(Bad Process)"还是"系统成本"？
        2. **情绪与盈亏**：当他处于 FOMO 或上头状态时，结局通常如何？
        3. **系统宪法执行度**：他是否在知行合一？
        
        请用严厉、专业、一针见血的语气。
        """
        
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"交易流水：\n{trades_text}"}
            ],
            temperature=0.5,
            timeout=60
        )
        
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
        return f"AI 分析生成失败: {str(e)}"
