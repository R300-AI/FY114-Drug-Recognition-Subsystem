"""utils/ — Drug-Recognition-Subsystem 核心模組

模組總覽：
  types          Detection, MatchResult   偵測/比對結果資料類別
  ui             App                      Tkinter GUI 應用程式
  depth_analysis DepthAnalyzer            2.5D 感測器深度分析
                 DrawerStateDetector      抽屜狀態偵測
  excel_writer   ExcelWriter              Excel 驗證記錄匯出
"""

from .types import Detection, MatchResult

__all__ = ["Detection", "MatchResult"]

__version__ = "2.0.0"
