"""test_excel_writer.py — 測試 Excel 寫入功能

在整合到主程式前，先測試 Excel 寫入是否正常運作。
"""

from pathlib import Path
from utils.excel_writer import ExcelWriter, create_backup, HAS_OPENPYXL
from utils.ui import PillEntry

def test_excel_writer():
    """測試 Excel 寫入功能"""
    
    if not HAS_OPENPYXL:
        print("❌ openpyxl 未安裝，請執行: pip install openpyxl")
        return False
    
    excel_path = Path("成大第一階段辨識問卷_1150304建議修改版.xlsx")
    
    if not excel_path.exists():
        print(f"❌ Excel 檔案不存在: {excel_path}")
        print("   請將問卷檔案放在專案根目錄")
        return False
    
    print(f"✅ 找到 Excel 檔案: {excel_path.name}")
    
    # 建立測試資料
    pills = [
        PillEntry(license="衛署藥製字第000001號", name="測試藥品A", same_count=3, color_idx=0),
        PillEntry(license="衛署藥製字第000002號", name="測試藥品B", same_count=5, color_idx=1),
        PillEntry(license="", name="未識別", same_count=1, color_idx=4),
    ]
    
    try:
        # 開啟 Excel
        writer = ExcelWriter(excel_path)
        print(f"✅ 成功開啟工作簿，工作表: {writer.sheet.title}")
        
        # 找到下一個空白列
        next_row = writer.find_next_empty_row()
        print(f"✅ 下一個空白列: 第 {next_row} 列")
        
        # 寫入測試資料
        writer.write_verification_data(
            tray_id="TEST01",
            timestamp="2026-03-24 15:00:00",
            variety_count=2,
            variety_correct=True,
            total_count=9,
            total_correct=False,
            pills=pills,
            name_answers=[True, True, None],
            dose_answers=[True, False, None],
        )
        print("✅ 資料寫入成功")
        
        # 儲存（建議先備份）
        print("\n⚠️  即將儲存到 Excel，這會修改原始檔案！")
        response = input("是否繼續？(y/n): ")
        
        if response.lower() == 'y':
            # 建立備份
            backup_path = create_backup(excel_path)
            print(f"✅ 已建立備份: {backup_path.name}")
            
            # 儲存
            writer.save()
            writer.close()
            print("✅ Excel 檔案儲存成功")
            print(f"\n請開啟 {excel_path.name} 檢查第 {next_row} 列的資料")
            return True
        else:
            writer.close()
            print("❌ 已取消儲存")
            return False
            
    except Exception as e:
        print(f"❌ 錯誤: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("Excel 寫入功能測試")
    print("=" * 60)
    print()
    
    success = test_excel_writer()
    
    print()
    print("=" * 60)
    if success:
        print("✅ 測試成功！可以整合到主程式")
    else:
        print("❌ 測試失敗，請檢查錯誤訊息")
    print("=" * 60)
