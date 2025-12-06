# -*- coding: utf-8 -*-
import sqlite3
import os
from datetime import datetime, timedelta
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

class WordExporter:
    """Word 文档导出器"""
    
    def __init__(self, db_path='trade_review.db', export_dir=None):
        self.db_path = db_path
        # 默认导出目录：D:\TradeReview AI\Trading_Reports (Windows) 或 /app/exports (Docker)
        if export_dir is None:
            # 检测操作系统和运行环境
            if os.name == 'nt':  # Windows 系统
                export_dir = r'D:\TradeReview AI\Trading_Reports'
            else:  # Linux/Docker 环境
                # 优先使用挂载的导出目录（如果存在）
                if os.path.exists('/app/exports'):
                    export_dir = '/app/exports'
                elif os.path.exists('/mnt/d/TradeReview AI/Trading_Reports'):
                    export_dir = '/mnt/d/TradeReview AI/Trading_Reports'
                else:
                    export_dir = '/app/Trading_Reports'  # Docker 容器内默认路径
        self.export_dir = os.path.abspath(export_dir)  # 转换为绝对路径
        # 确保导出目录存在
        if not os.path.exists(self.export_dir):
            try:
                os.makedirs(self.export_dir, exist_ok=True)
            except Exception as e:
                print(f"⚠️ 无法创建导出目录 {self.export_dir}: {e}")
                # 如果创建失败，尝试使用当前目录下的相对路径
                self.export_dir = os.path.abspath('Trading_Reports')
                os.makedirs(self.export_dir, exist_ok=True)
    
    def get_time_cutoff(self, time_range):
        """根据选择的时间范围计算截止时间戳（毫秒）"""
        now = datetime.now()
        
        if time_range == 'week':
            delta = timedelta(weeks=1)
        elif time_range == 'month':
            delta = timedelta(days=30)
        elif time_range == 'year':
            delta = timedelta(days=365)
        elif time_range == 'all':
            return 0  # 0 时间戳代表很久以前
        else:
            print("未知的筛选条件，默认导出最近一个月")
            delta = timedelta(days=30)
        
        # 计算截止时间戳（毫秒）
        cutoff_timestamp = int((now - delta).timestamp() * 1000)
        return cutoff_timestamp
    
    def export_round_trips_to_word(self, rounds_df, raw_df, api_key_tag=None, time_range='month'):
        """
        导出交易记录到 Word 文档
        
        :param rounds_df: 处理后的完整交易 DataFrame（round trips），已经按账户筛选
        :param raw_df: 原始交易数据 DataFrame，已经按账户筛选
        :param api_key_tag: API key 标签（可选，用于日志）
        :param time_range: 'week', 'month', 'year', 'all'
        :return: (文件路径, 消息) 元组，失败返回 (None, 错误消息)
        """
        
        # 1. 根据时间范围筛选数据
        cutoff_time = self.get_time_cutoff(time_range)
        
        if cutoff_time > 0:
            filtered_rounds = rounds_df[rounds_df['close_time'] >= cutoff_time].copy()
        else:
            filtered_rounds = rounds_df.copy()
        
        if filtered_rounds.empty:
            return None, "该时间段内没有找到交易记录。"
        
        # 2. 创建 Word 文档对象
        doc = Document()
        
        # 设置文档标题
        time_range_names = {
            'week': '最近一周',
            'month': '最近一月',
            'year': '最近一年',
            'all': '全部历史'
        }
        title_text = f'交易复盘报告 ({time_range_names.get(time_range, time_range)})'
        title = doc.add_heading(title_text, 0)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        # 添加元信息
        doc.add_paragraph(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        doc.add_paragraph(f"共计交易: {len(filtered_rounds)} 笔")
        
        # 计算统计信息
        total_pnl = filtered_rounds['net_pnl'].sum()
        win_count = len(filtered_rounds[filtered_rounds['net_pnl'] > 0])
        win_rate = round((win_count / len(filtered_rounds) * 100), 1) if len(filtered_rounds) > 0 else 0
        
        doc.add_paragraph(f"总盈亏: ${total_pnl:,.2f}")
        doc.add_paragraph(f"胜率: {win_rate}%")
        doc.add_paragraph("-" * 50)  # 分割线
        
        # 3. 循环写入每一笔交易
        upload_dir = os.path.join(os.path.dirname(self.db_path), 'uploads')
        
        for idx, (_, trade) in enumerate(filtered_rounds.iterrows(), 1):
            round_id = trade['round_id']
            
            # 从原始数据中获取详细信息（策略、笔记、截图）
            trade_row = raw_df[raw_df['id'] == round_id]
            if not trade_row.empty:
                trade_info = trade_row.iloc[0]
                strategy = trade_info.get('strategy', '') or ''
                notes = trade_info.get('notes', '') or ''
                screenshot_name = trade_info.get('screenshot', '') or ''
            else:
                strategy = trade.get('strategy', '') or ''
                notes = trade.get('notes', '') or ''
                screenshot_name = ''
            
            # --- A. 写入标题 (交易序号 + 币种 + 方向) ---
            direction_display = trade['direction']
            heading = doc.add_heading(f"交易 #{idx}: {trade['symbol']} ({direction_display})", level=1)
            
            # --- B. 写入硬数据 ---
            p_info = doc.add_paragraph()
            p_info.add_run(f"开仓时间: ").bold = True
            p_info.add_run(f"{trade['open_date_str']}   ")
            p_info.add_run(f"平仓时间: ").bold = True
            p_info.add_run(f"{trade['close_date_str']}")
            
            p_info2 = doc.add_paragraph()
            p_info2.add_run(f"持仓时长: ").bold = True
            p_info2.add_run(f"{trade['duration_str']}   ")
            p_info2.add_run(f"操作次数: ").bold = True
            p_info2.add_run(f"{trade['trade_count']} 次")
            
            # 盈亏信息（突出显示）
            p_pnl = doc.add_paragraph()
            pnl_color = '盈利' if trade['net_pnl'] >= 0 else '亏损'
            p_pnl.add_run(f"净盈亏: ").bold = True
            pnl_run = p_pnl.add_run(f"${trade['net_pnl']:,.2f} ({pnl_color})")
            if trade['net_pnl'] >= 0:
                pnl_run.font.color.rgb = RGBColor(0, 128, 0)  # 绿色
            else:
                pnl_run.font.color.rgb = RGBColor(255, 0, 0)  # 红色
            
            p_pnl.add_run(f"  (手续费: ${trade['total_fee']:.2f})")
            
            # --- C. 写入策略（如果有）---
            if strategy:
                doc.add_heading("策略/依据:", level=2)
                doc.add_paragraph(strategy)
            
            # --- D. 写入复盘笔记 ---
            doc.add_heading("复盘笔记:", level=2)
            if notes:
                doc.add_paragraph(notes)
            else:
                doc.add_paragraph("（无笔记）").italic = True
            
            # --- E. 插入截图（核心功能）---
            doc.add_heading("图表截图:", level=2)
            
            if screenshot_name:
                screenshot_path = os.path.join(upload_dir, screenshot_name)
                if os.path.exists(screenshot_path):
                    try:
                        # 插入图片，限制宽度为 6 英寸（约 15cm）
                        doc.add_picture(screenshot_path, width=Inches(6))
                    except Exception as e:
                        p_err = doc.add_paragraph(f"[图片加载失败: {str(e)}]")
                        # 设置错误文本为红色（如果支持）
                        try:
                            p_err.runs[0].font.color.rgb = (255, 0, 0)
                        except:
                            pass
                else:
                    doc.add_paragraph(f"[未找到截图文件: {screenshot_name}]").italic = True
            else:
                doc.add_paragraph("[未上传截图]").italic = True
            
            # --- F. 添加分页符（让每一笔交易都在新的一页）---
            if idx < len(filtered_rounds):  # 最后一笔交易不需要分页
                doc.add_page_break()
        
        # 4. 保存文件
        filename = f"TradeReview_Report_{time_range_names.get(time_range, time_range)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
        save_path = os.path.join(self.export_dir, filename)
        
        try:
            doc.save(save_path)
            return save_path, f"✅ 导出成功！共导出 {len(filtered_rounds)} 笔交易。"
        except Exception as e:
            return None, f"❌ 保存文件失败: {str(e)}"

