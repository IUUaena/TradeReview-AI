import numpy as np
import pandas as pd

class MonteCarloEngine:
    """
    v5.0 核心：蒙特卡洛模拟引擎
    用于预测未来的资金曲线分布和破产风险
    """
    
    def __init__(self, trades_df):
        # 提取净盈亏序列
        if not trades_df.empty:
            self.pnl_series = trades_df['net_pnl'].values
        else:
            self.pnl_series = np.array([])
            
    def run_simulation(self, start_equity, sim_runs=100, trades_per_run=100):
        """
        执行模拟
        :param start_equity: 初始资金
        :param sim_runs: 模拟多少个平行宇宙 (例如 100 次)
        :param trades_per_run: 每个宇宙交易多少笔 (例如 未来100笔)
        :return: 模拟结果字典
        """
        if len(self.pnl_series) < 10:
            return None, "交易样本太少 (至少需要10笔)"
        
        # 1. 核心统计特征
        win_rate = np.mean(self.pnl_series > 0)
        avg_win = np.mean(self.pnl_series[self.pnl_series > 0]) if np.any(self.pnl_series > 0) else 0
        avg_loss = np.mean(self.pnl_series[self.pnl_series <= 0]) if np.any(self.pnl_series <= 0) else 0
        
        # 2. 蒙特卡洛抽样 (Bootstrap Method)
        # 从历史盈亏中随机抽取，生成未来的盈亏序列
        # shape: (sim_runs, trades_per_run)
        random_pnls = np.random.choice(self.pnl_series, size=(sim_runs, trades_per_run), replace=True)
        
        # 3. 计算资金曲线
        # cumulative sum across trades
        cum_pnl = np.cumsum(random_pnls, axis=1)
        # add start equity
        equity_curves = start_equity + cum_pnl
        
        # 4. 计算关键指标
        
        # A. 破产率 (Risk of Ruin): 资金触及 0 或某条警戒线的概率
        ruin_count = np.sum(np.any(equity_curves <= 0, axis=1))
        risk_of_ruin = (ruin_count / sim_runs) * 100
        
        # B. 预期期末资金 (中位数和均值)
        final_equities = equity_curves[:, -1]
        median_final = np.median(final_equities)
        worst_case = np.percentile(final_equities, 5)  # 最倒霉的 5% 的情况
        best_case = np.percentile(final_equities, 95)  # 最幸运的 5% 的情况
        
        # C. 最大回撤预测 (Max Drawdown)
        # 计算每条曲线的最大回撤
        max_dds = []
        for curve in equity_curves:
            peak = start_equity
            max_dd = 0
            for val in curve:
                if val > peak: peak = val
                dd = (peak - val) / peak
                if dd > max_dd: max_dd = dd
            max_dds.append(max_dd)
            
        avg_max_dd = np.mean(max_dds) * 100
        worst_max_dd = np.max(max_dds) * 100
        
        return {
            "equity_curves": equity_curves,  # 原始曲线数据
            "risk_of_ruin": risk_of_ruin,
            "median_final": median_final,
            "worst_case": worst_case,
            "best_case": best_case,
            "avg_max_dd": avg_max_dd,
            "worst_max_dd": worst_max_dd,
            "sim_runs": sim_runs,
            "trades_per_run": trades_per_run
        }, "OK"

