from openai import OpenAI
import pandas as pd

def get_ai_analysis(api_key, base_url, trade_data, user_notes=""):
    """
    调用 AI 对交易进行点评。
    """
    try:
        # 1. 初始化 AI 客户端
        # 如果是 DeepSeek，base_url 通常是 https://api.deepseek.com
        client = OpenAI(api_key=api_key, base_url=base_url)

        # 2. 准备喂给 AI 的数据
        # 把复杂的交易数据变成一段通俗的文字描述
        prompt_data = f"""
        【交易信息】

        - 标的: {trade_data['symbol']}
        - 方向: {trade_data['direction']} (Long=做多, Short=做空)
        - 开仓时间: {trade_data['open_date']}
        - 持仓时间: {trade_data['duration_min']} 分钟
        - 净盈亏: {trade_data['net_pnl']} U
        - 手续费磨损: {trade_data['total_fee']} U
        - 交易员的复盘笔记: "{user_notes}"
        """

        # 3. 设定 AI 的人设 (Prompt Engineering)
        # 你要求的是：严厉、一针见血、导师身份
        system_prompt = """
        你是一位拥有20年经验的华尔街顶级交易员导师。你的风格是：

        1. **极度严厉**：不要客套，不要鼓励，直接指出愚蠢之处。

        2. **一针见血**：关注盈亏比、持仓时间与收益的效率、以及手续费磨损。

        3. **关注心理**：如果交易员写了笔记，分析他的心理状态是否失控（如FOMO、扛单）。

        4. **简短有力**：控制在 200 字以内，用列表形式输出 3 个关键改进点。

        

        如果这笔交易亏损了，请严厉批评他的入场或风控。

        如果这笔交易盈利了但逻辑不对，也要敲打他不要靠运气赚钱。
        """

        # 4. 发送请求
        response = client.chat.completions.create(
            model="deepseek-chat", # 或者 gpt-3.5-turbo, 取决于你用的平台
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"请点评这笔交易：\n{prompt_data}"}
            ],
            temperature=0.7, # 创造性稍微高一点，骂得花一点
            timeout=30
        )

        return response.choices[0].message.content

    except Exception as e:
        return f"AI 大脑短路了：{str(e)}"

