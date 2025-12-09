import openai
import os
import json
import pandas as pd
import pandas_ta as ta
from datetime import datetime
# 引入本地数据引擎，让 AI 能自己查数据
from market_engine import MarketDataEngine


class AIAssistant:

    def __init__(self):
        # 尝试从环境变量或 secrets 获取 Key
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.client = None
        if self.api_key:
            self.client = openai.OpenAI(api_key=self.api_key, base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"))
            
        # 初始化数据引擎 (用于后台静默分析)
        self.market_engine = MarketDataEngine()


    def check_key(self):
        return self.api_key is not None


    def set_key(self, key, base_url=None):
        self.api_key = key
        # 支持自定义 Base URL (对于 DeepSeek 等中转服务很重要)
        if base_url is None:
            base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.client = openai.OpenAI(api_key=self.api_key, base_url=base_url)


    # ======================================================
    # 🧠 AI 独立分析插件
    # ======================================================
    
    def _analyze_vegas_trend(self, symbol, open_time):
        """后台自动计算 Vegas 趋势"""
        try:
            clean_symbol = symbol.split(':')[0].replace('USDT', '/USDT') if 'USDT' in symbol and '/' not in symbol else symbol
            
            # 获取 4H 数据 (回溯 150 天)
            lookback = 150 * 24 * 60 * 60 * 1000
            start_ts = open_time - lookback
            df = self.market_engine.get_klines_df(clean_symbol, start_ts, open_time + 60000)
            
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
        try:
            clean_symbol = symbol.split(':')[0].replace('USDT', '/USDT') if 'USDT' in symbol and '/' not in symbol else symbol
            future_end = close_time + (24 * 60 * 60 * 1000)
            df = self.market_engine.get_klines_df(clean_symbol, close_time, future_end)
            
            if df.empty:
                return "无未来数据 (可能刚平仓)"
            
            potential_high = df['high'].max()
            potential_low = df['low'].min()
            exit_price = float(exit_price)
            
            if "Long" in direction:
                missed_pct = (potential_high - exit_price) / exit_price * 100
                if missed_pct > 2.0: return f"🍖 严重卖飞！离场后涨了 {missed_pct:.2f}%"
                elif missed_pct < -1.0: return "🏆 成功逃顶"
                else: return "✅ 正常离场"
            else:
                missed_pct = (exit_price - potential_low) / exit_price * 100
                if missed_pct > 2.0: return f"🍖 严重卖飞！离场后跌了 {missed_pct:.2f}%"
                elif missed_pct < -1.0: return "🏆 成功逃顶"
                else: return "✅ 正常离场"
        except:
            return "离场分析不可用"


    # ======================================================


    def audit_single_trade(self, t, memory_context="", model_name="deepseek-chat"):
        """
        审计单笔交易
        :param model_name: 接收前端传入的模型名称 (默认 deepseek-chat)
        """
        if not self.client:
            return "❌ 请先设置 API Key"


        try:
            # 1. 运行分析
            trend_context = self._analyze_vegas_trend(t.get('symbol'), t.get('open_time'))
            what_if_result = self._analyze_missed_profit(t.get('symbol'), t.get('direction'), t.get('close_time'), t.get('price'))


            # 2. 准备数据 (防空护盾)
            pnl_emoji = "✅" if t.get('net_pnl', 0) > 0 else "❌"
            
            def safe_num(val, decimals=2):
                if val is None or str(val).lower() in ['nan', 'none']: return "N/A"
                try: return f"{float(val):.{decimals}f}"
                except: return "N/A"
            
            def safe_str(val, default="无"):
                if val is None or str(val).lower() in ['nan', 'none']: return default
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
            - 标的: {t.get('symbol')} ({t.get('direction')})
            - 结果: {pnl_emoji} ${safe_num(t.get('net_pnl', 0))}
            - 时间: {t.get('open_date_str')}
            
            {metrics_text}
            
            【上帝视角】
            - 宏观趋势: {trend_context}
            - 离场评价: {what_if_result}
            
            【交易者笔记】
            策略: {safe_str(t.get('strategy'))}
            心态: {safe_str(t.get('mental_state'))}
            复盘: {safe_str(t.get('notes'))}
            """


            system_prompt = f"""
            你是一名华尔街顶级交易员教练。请根据以下数据进行审计。
            
            审计逻辑：
            1. **宏观与择时**：参考【上帝视角】的 Vegas 趋势。
            2. **结构与位置**：如果结构显示"逼近阻力位"却做多，严厉批评。
            3. **入场依据**：检查入场信号。如果是"无显著形态"，批评其随机交易。
            4. **执行质量**：结合 MAD(痛苦时长) 和 卖飞情况进行点评。
            
            {memory_context}
            """


            # 🟢 关键：使用传入的 model_name
            print(f"DEBUG: Calling model -> {model_name}")
            response = self.client.chat.completions.create(
                model=model_name, 
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": context_text}
                ],
                temperature=0.7
            )
            return response.choices[0].message.content


        except Exception as e:
            return f"审计失败: {str(e)}"


    def analyze_strategy_suggestion(self, strategy_name, recent_trades):
        return "策略分析功能暂未启用"
