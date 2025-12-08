# -*- coding: utf-8 -*-

import sqlite3
import os
import sys
from datetime import datetime, timedelta
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

class WordExporter:
    """v3.8 路径增强版：强制锁定代码所在文件夹"""
    
    def __init__(self, db_path='trade_review.db', export_dir=None):
        self.db_path = db_path
        
        # --- 核心修复：获取 word_exporter.py 这个文件所在的"绝对路径" ---
        # 这样无论你怎么运行，它都知道自己是在 D:\TradeReview AI 里面
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
        # 拼接出 D:\TradeReview AI\Trading_Reports
        self.export_dir = os.path.join(base_dir, 'Trading_Reports')
        
        # 自动创建文件夹
        if not os.path.exists(self.export_dir):
            try:
                os.makedirs(self.export_dir, exist_ok=True)
            except Exception as e:
                print(f"创建目录失败: {e}")
            
        print(f"📂 导出目录锁定为: {self.export_dir}")
    
    def get_time_cutoff(self, time_range):
        now = datetime.now()
        if time_range == 'week': delta = timedelta(weeks=1)
        elif time_range == 'month': delta = timedelta(days=30)
        elif time_range == 'year': delta = timedelta(days=365)
        elif time_range == 'all': return 0
        else: delta = timedelta(days=30)
        return int((now - delta).timestamp() * 1000)
    
    def set_cell_text(self, cell, text, bold=False, color=None, size=None):
        paragraph = cell.paragraphs[0]
        run = paragraph.add_run(str(text))
        if bold: run.bold = True
        if color: run.font.color.rgb = color
        if size: run.font.size = Pt(size)
        return paragraph
    
    def export_round_trips_to_word(self, rounds_df, raw_df, api_key_tag=None, time_range='month', mode='full'):
        # 1. 筛选数据
        cutoff_time = self.get_time_cutoff(time_range)
        filtered_rounds = rounds_df.copy()
        if cutoff_time > 0:
            filtered_rounds = filtered_rounds[filtered_rounds['close_time'] >= cutoff_time]
        
        if filtered_rounds.empty:
            return None, "该时间段内没有找到交易记录。"
        
        # 2. 创建文档
        doc = Document()
        
        time_range_names = {
            'week': '最近一周',
            'month': '最近一月',
            'year': '最近一年',
            'all': '全部历史'
        }
        mode_title = "交易绩效审计报告" if mode == 'full' else "交易复盘原始数据包"
        time_range_cn = time_range_names.get(time_range, time_range)
        title = doc.add_heading(f'{mode_title} ({time_range_cn})', 0)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        doc.add_paragraph(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        
        if mode == 'raw':
            note_p = doc.add_paragraph("Prompt: 本文档包含交易员原始记录。")
            note_p.runs[0].font.color.rgb = RGBColor(100, 100, 100)
            
        doc.add_paragraph(f"交易数: {len(filtered_rounds)} | 总盈亏: ${filtered_rounds['net_pnl'].sum():.2f}")
        doc.add_paragraph("-" * 30)
        
        upload_dir = os.path.join(os.path.dirname(self.db_path), 'uploads')
        
        # 3. 遍历交易
        for idx, (_, trade) in enumerate(filtered_rounds.iterrows(), 1):
            symbol = trade['symbol']
            direction = trade['direction']
            pnl = trade['net_pnl']
            open_time = trade['open_date_str']
            
            strategy = trade.get('strategy', '') or "未定义"
            mental = trade.get('mental_state', '-')
            process = trade.get('process_tag', '-')
            rating = trade.get('setup_rating', 0)
            notes = trade.get('notes', '')
            ai_audit = trade.get('ai_analysis', '')
            
            screenshot = ""
            if 'screenshot' in trade:
                screenshot = trade['screenshot']
            else:
                raw_row = raw_df[raw_df['id'] == trade['round_id']]
                if not raw_row.empty:
                    screenshot = raw_row.iloc[0].get('screenshot', '')
            
            pnl_str = f"+${pnl:.2f}" if pnl > 0 else f"-${abs(pnl):.2f}"
            doc.add_heading(f"#{idx} {symbol} ({direction})  {pnl_str}", level=1)
            
            table = doc.add_table(rows=2, cols=4)
            table.style = 'Table Grid'
            
            self.set_cell_text(table.cell(0, 0), "开仓时间", bold=True)
            self.set_cell_text(table.cell(0, 1), "策略依据", bold=True)
            self.set_cell_text(table.cell(0, 2), "执行质量", bold=True)
            self.set_cell_text(table.cell(0, 3), "心态/评分", bold=True)
            
            self.set_cell_text(table.cell(1, 0), str(open_time), size=9)
            self.set_cell_text(table.cell(1, 1), str(strategy), size=9)
            
            proc_color = RGBColor(0, 150, 0) if "Good" in str(process) else RGBColor(0, 0, 0)
            if "Bad" in str(process): proc_color = RGBColor(200, 0, 0)
            self.set_cell_text(table.cell(1, 2), str(process), color=proc_color, bold=True, size=9)
            self.set_cell_text(table.cell(1, 3), f"{mental} | {rating}分", size=9)
            
            doc.add_paragraph("")
            if notes:
                doc.add_heading("📝 笔记:", level=2)
                p = doc.add_paragraph(str(notes))
                p.style = 'Quote'
            
            if mode == 'full':
                if ai_audit:
                    doc.add_heading("👮 AI审计:", level=2)
                    p_ai = doc.add_paragraph()
                    run_ai = p_ai.add_run(str(ai_audit))
                    run_ai.font.color.rgb = RGBColor(50, 50, 150)
                else:
                    doc.add_paragraph("[无审计]").italic = True
            
            if screenshot:
                img_path = os.path.join(upload_dir, screenshot)
                if os.path.exists(img_path):
                    doc.add_heading("📈 截图:", level=2)
                    try:
                        doc.add_picture(img_path, width=Inches(5.5))
                    except:
                        doc.add_paragraph("[图片加载失败]")
            
            doc.add_page_break()
            
        prefix = "Audit_Report" if mode == 'full' else "Raw_Data_Package"
        filename = f"{prefix}_{time_range}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.docx"
        save_path = os.path.join(self.export_dir, filename)
        
        try:
            doc.save(save_path)
            # 返回绝对路径，确保前端显示正确
            return os.path.abspath(save_path), f"✅ 导出成功！"
        except Exception as e:
            return None, f"导出失败: {str(e)}"
