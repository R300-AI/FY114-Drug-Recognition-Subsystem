"""utils/excel_writer.py — Excel 問卷自動填寫模組

負責將辨識結果自動填寫至「成大第一階段辨識問卷」Excel 檔案。
支援 .xlsx 和 .xlsm 格式。
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    from openpyxl import load_workbook
    from openpyxl.worksheet.worksheet import Worksheet
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


class ExcelWriter:
    """Excel 問卷填寫器
    
    使用方式：
        writer = ExcelWriter("問卷.xlsx")
        writer.write_verification_data(
            tray_id="000001",
            timestamp="2026-03-24 10:30:00",
            variety_count=3,
            variety_correct=True,
            total_count=10,
            total_correct=True,
            pills=[...],
            name_answers=[True, False, ...],
            dose_answers=[True, True, ...]
        )
        writer.save()
    """
    
    def __init__(self, excel_path: str | Path, sheet_name: Optional[str] = None):
        """初始化 Excel 寫入器
        
        Args:
            excel_path: Excel 檔案路徑
            sheet_name: 工作表名稱（預設使用 active sheet）
        """
        if not HAS_OPENPYXL:
            raise ImportError("openpyxl 未安裝，請執行: pip install openpyxl")
        
        self.excel_path = Path(excel_path)
        if not self.excel_path.exists():
            raise FileNotFoundError(f"Excel 檔案不存在: {self.excel_path}")
        
        # 載入工作簿（保留巨集）
        self.workbook = load_workbook(self.excel_path, keep_vba=True)
        
        # 選擇工作表
        if sheet_name:
            if sheet_name not in self.workbook.sheetnames:
                raise ValueError(f"工作表 '{sheet_name}' 不存在。可用工作表: {self.workbook.sheetnames}")
            self.sheet = self.workbook[sheet_name]
        else:
            self.sheet = self.workbook.active
        
        print(f"[excel] 已載入: {self.excel_path.name}, 工作表: {self.sheet.title}")
    
    def find_next_empty_row(self, start_row: int = 2, column: int = 1) -> int:
        """找到下一個空白列（用於追加資料）
        
        Args:
            start_row: 開始搜尋的列號（預設從第 2 列開始，假設第 1 列是標題）
            column: 檢查的欄位（預設第 1 欄）
        
        Returns:
            空白列的列號
        """
        row = start_row
        while self.sheet.cell(row, column).value is not None:
            row += 1
        return row
    
    def write_verification_data(
        self,
        tray_id: str,
        timestamp: str,
        variety_count: int,
        variety_correct: bool | None,
        total_count: int,
        total_correct: bool | None,
        pills: list,
        name_answers: list[bool | None],
        dose_answers: list[bool | None],
        start_row: Optional[int] = None,
    ):
        """將驗證資料寫入 Excel
        
        Args:
            tray_id: 藥盤序號
            timestamp: 時間戳記
            variety_count: 品項數量
            variety_correct: 品項是否正確
            total_count: 總顆數
            total_correct: 總數是否正確
            pills: PillEntry 列表
            name_answers: 各藥品名稱的正確性
            dose_answers: 各藥品劑量的正確性
            start_row: 寫入的起始列（None 則自動找下一個空白列）
        """
        if start_row is None:
            row = self.find_next_empty_row()
        else:
            row = start_row
        
        # 範例欄位對應（請根據實際問卷調整）
        # 假設問卷格式：
        # A: 序號, B: 時間, C: 品項數, D: 品項正確, E: 總數, F: 總數正確, 
        # G~: 各藥品資訊
        
        col = 1  # A 欄
        self.sheet.cell(row, col, tray_id)  # 藥盤序號
        
        col += 1  # B 欄
        self.sheet.cell(row, col, timestamp)  # 時間戳記
        
        col += 1  # C 欄
        self.sheet.cell(row, col, variety_count)  # 品項數
        
        col += 1  # D 欄
        self.sheet.cell(row, col, self._bool_to_text(variety_correct))  # 品項正確性
        
        col += 1  # E 欄
        self.sheet.cell(row, col, total_count)  # 總顆數
        
        col += 1  # F 欄
        self.sheet.cell(row, col, self._bool_to_text(total_correct))  # 總數正確性
        
        # 寫入各藥品的詳細資訊（從 G 欄開始）
        for i, pill in enumerate(pills):
            if i < len(name_answers) and i < len(dose_answers):
                col += 1
                self.sheet.cell(row, col, pill.name)  # 藥品名稱
                
                col += 1
                self.sheet.cell(row, col, pill.license)  # 許可證字號
                
                col += 1
                self.sheet.cell(row, col, pill.same_count)  # 顆數
                
                col += 1
                self.sheet.cell(row, col, self._bool_to_text(name_answers[i]))  # 名稱正確
                
                col += 1
                self.sheet.cell(row, col, self._bool_to_text(dose_answers[i]))  # 劑量正確
        
        print(f"[excel] 資料已寫入第 {row} 列")
        return row
    
    @staticmethod
    def _bool_to_text(value: bool | None) -> str:
        """將布林值轉換為文字"""
        if value is True:
            return "正確"
        elif value is False:
            return "錯誤"
        else:
            return "未填"
    
    def save(self, output_path: Optional[str | Path] = None):
        """儲存 Excel 檔案
        
        Args:
            output_path: 輸出路徑（None 則覆寫原檔案）
        """
        save_path = Path(output_path) if output_path else self.excel_path
        self.workbook.save(save_path)
        print(f"[excel] 已儲存: {save_path}")
    
    def close(self):
        """關閉工作簿"""
        self.workbook.close()


def create_backup(excel_path: str | Path) -> Path:
    """建立 Excel 檔案備份
    
    Args:
        excel_path: 原始檔案路徑
    
    Returns:
        備份檔案路徑
    """
    excel_path = Path(excel_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = excel_path.parent / f"{excel_path.stem}_backup_{timestamp}{excel_path.suffix}"
    
    import shutil
    shutil.copy2(excel_path, backup_path)
    print(f"[excel] 已建立備份: {backup_path.name}")
    return backup_path


__all__ = ["ExcelWriter", "create_backup", "HAS_OPENPYXL"]
