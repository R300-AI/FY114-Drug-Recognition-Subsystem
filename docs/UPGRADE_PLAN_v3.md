# 系統升級規劃書 — v3.0

> 對照 `docs/UXUI_Design/index.html`（新設計稿）、`utils/ui.py`（現行 UI）、
> `drawer_monitor.py` / `utils/depth_analysis.py`（抽屜感測子系統），
> 完整規劃改版工作細節，供開發者逐項查驗與指導。

---

## 目錄

1. [系統架構總覽：舊 vs 新](#1-系統架構總覽舊-vs-新)
2. [新架構各元件職責](#2-新架構各元件職責)
3. [設計稿 UI 關鍵解讀](#3-設計稿-ui-關鍵解讀)
4. [現況與新設計差異對照](#4-現況與新設計差異對照)
5. [工作清單](#5-工作清單)
6. [實作順序](#6-實作順序)
7. [待釐清事項](#7-待釐清事項)

---

## 1. 系統架構總覽：舊 vs 新

### 1.1 舊架構

```
使用者手動按「分析」按鈕
    ↓
run.py → App._on_analyse()
    ├── Picamera2 拍照
    ├── YOLODetector 偵測
    ├── ResNet34Encoder 編碼
    └── Top1Matcher 比對
    ↓
右側面板顯示結果，等待護理師填報

drawer_monitor.py  ← 完全獨立，不與 run.py 溝通
```

**問題**：分析觸發由人工按鈕控制；抽屜感測器與主系統完全分離。

---

### 1.2 新架構

```
系統啟動
    ↓
run.py → App.__init__()
    ├── Picamera2 初始化（不啟動）
    ├── MN96100C 初始化（背景執行緒持續偵測）  ← 新增
    └── UI 進入 IDLE 狀態（黑畫面）

[背景執行緒：drawer_capture_loop]
    每幀：讀取 MN96100C → 計算 intensity SMA
        → DrawerStateDetector.update()
        → 偵測到「開→閉」狀態轉換
        → root.after(0, _on_drawer_closed)   ← 事件派送到 UI 執行緒

[UI 執行緒：_on_drawer_closed()]
    如果目前是 IDLE 狀態：
        → _on_analyse()（拍照→偵測→比對→顯示）
        → 進入 REVIEWING 狀態

護理師填報完成
    → 按「完成」→ 儲存 → 回到 IDLE 狀態
    → 等待下一次抽屜觸發

drawer_monitor.py  ← 保留為獨立校準工具（部署前調校閾值用）
```

**關鍵設計原則**：
- 狀態機保護：分析進行中（ANALYSING）或填報中（REVIEWING）時，抽屜觸發**無效**，避免誤觸發
- 觸發條件：**前一狀態不是「完全閉合」** 且 **新狀態是「完全閉合」**（邊緣觸發，非位準觸發）
- 執行緒安全：抽屜感測在背景執行緒，透過 `root.after()` 派送事件到 UI 執行緒，不直接操作 UI

---

## 2. 新架構各元件職責

| 元件 | 檔案 | 職責 |
|------|------|------|
| `App` | `utils/ui.py` | 主 UI 應用，整合所有子系統 |
| `DrawerStateDetector` | `utils/depth_analysis.py` | intensity → 狀態判斷（已完成，不需修改） |
| `DepthAnalyzer` | `utils/depth_analysis.py` | intensity metrics 計算（已完成，不需修改） |
| `VideoCapture`（MN96100C） | `eminent/sensors/vision2p5d/` | USB 2.5D 傳感器讀取（已完成，不需修改） |
| `drawer_monitor.py` | 根目錄 | **獨立校準工具**（部署前調閾值，與主系統無關） |
| `config/drawer_config.yaml` | config/ | 閾值設定，主系統啟動時讀取 |
| `YOLODetector` | `run.py` | 藥錠偵測 |
| `ResNet34Encoder` | `run.py` | 特徵編碼 |
| `Top1Matcher` | `run.py` | Gallery 比對 |

---

## 3. 設計稿 UI 關鍵解讀

### 3.1 頁面結構

```
┌──────────────────────────────────────────────────────────┐
│ AI藥品輔助辨識 │ [鏡頭] [AI] │      藥盤序號 [編號]       │
│                               │      時間: YYYY/M/D HH:MM │
│                               │                   [完成]  │
├──────────────────────┬───────────────────────────────────┤
│                      │ 【藥盤】總品項  5 種  [正確][錯誤]  │
│   左側影像            │ 【藥盤】總數量  9 顆  [正確][錯誤]  │
│   (鏡頭 / AI)        │                                   │
│                      │ ┌─ 藥品面板 ──────────────────── ┐│
│   ┌─highlight──┐     │ │ [藥品名稱 — 藍底]               ││
│   │  圈選框    │     │ │ 【藥品】名稱核對  [正確] [錯誤]  ││
│   └────────────┘     │ │ ─────────────────────────────  ││
│                      │ │ [▲]  (overflow 才顯示)          ││
│                      │ │ [icon] A1 數量 1顆 [正確][錯誤] ││
│                      │ │ [icon] A2 數量 1顆 [正確][錯誤] ││
│                      │ │ [▼]  (overflow 才顯示)          ││
│                      │ │ ─────────────────────────────  ││
│                      │ │ 共計 2 顆                       ││
│                      │ │ [上一種]  第1種/共5種  [下一種] ││
│                      │ └─────────────────────────────── ┘│
└──────────────────────┴───────────────────────────────────┘
```

### 3.2 資料結構（設計稿 drugPages）

```js
drugPages = [
  {
    code: "A",
    title: "BOTERASU TABLETS FOR...",
    items: [
      { key: "A1", count: 1, color: "#ED7D31", img: "A1_image.png" },
      { key: "A2", count: 1, color: "#FFC000", img: "A2_image.png" }
    ]
  }, ...
]
```

- **分頁單位**：每「種」藥一頁
- **item**：同藥不同顆，各有獨立的圖示與確認列
- **item.key**（A1, A2…）：用於 dose_answers 索引 + 左圖 hotspot 定位

### 3.3 左圖 Hotspot 系統

- 滑鼠 hover / 點擊 dose 列 → 左圖對應位置出現紅色框線
- 框線以**相對百分比位置**定位（left%, top%, width%, height%）
- 點擊正確/錯誤 → 若不在 AI tab 則自動切換

### 3.4 完成流程

```
按「完成」
  ├─ 有未填 → Missing Modal（「回去檢查」）→ 跳至第一個缺漏並紅框標示
  └─ 全填完 → Success Modal（完整 feedback list）
       ├─ [重新回饋] → 清空所有答案，回到 REVIEWING
       └─ [儲存] → 寫檔 → Toast「儲存完成」(1.5s) → 回到 IDLE（黑畫面）
```

---

## 4. 現況與新設計差異對照

| 面向 | 現行（ui.py） | 新設計 | 影響層級 |
|------|-------------|--------|---------|
| **分析觸發** | 手動按「分析」按鈕 | 抽屜閉合（MN96100C 狀態轉換）自動觸發 | **核心** |
| **App 狀態機** | 無（隱性狀態） | IDLE / ANALYSING / REVIEWING 明確狀態 | **核心** |
| **分頁單位** | 每顆 pill（Detection）一頁 | 每種 drug 一頁 | 核心 |
| **劑量確認粒度** | 一個 dose_answer / license | 每個 item（A1, A2…）獨立確認 | 核心 |
| **名稱核對層級** | 每顆各填一次 | 每種藥只填一次 | 核心 |
| **左圖 Highlight** | YOLO overlay 重繪整張圖 | 相對定位 overlay 框（不重繪） | 中 |
| **dose 列溢出** | 無處理，截斷 | 虛擬捲動（▲▼ 箭頭，overflow 才顯示） | 中 |
| **藥品圖示** | 無 | 每個 dose item 顯示 56px 圖（裁切原圖） | 中 |
| **完成 Modal** | Tkinter Toplevel + scrollbar | in-place backdrop + 卡片 | 中 |
| **Toast 通知** | 無 | 儲存完成後顯示 1.5s | 低 |
| **藥品名稱背景** | 白底 | 藍底（#81C7D4） | 低 |
| **「分析」按鈕** | topbar 有 | 移除（抽屜觸發取代） | 低 |
| **Feedback List** | 平坦清單 | 分組（drug → items 縮排） | 低 |

---

## 5. 工作清單

---

### Task 0：App 狀態機（新增）

**目標**：明確定義系統狀態，避免抽屜觸發在錯誤時機執行分析。

```python
# utils/ui.py
from enum import Enum, auto

class AppState(Enum):
    IDLE       = auto()   # 黑畫面，等待抽屜觸發
    ANALYSING  = auto()   # 拍照+偵測+比對進行中
    REVIEWING  = auto()   # 顯示結果，護理師填報中
```

- [ ] 新增 `AppState` enum
- [ ] `App.__init__` 加入 `self._app_state = AppState.IDLE`
- [ ] `_on_analyse()` 開頭：若非 IDLE → 忽略；設為 ANALYSING
- [ ] 分析完成後：設為 REVIEWING
- [ ] 儲存完成後：`_reset_state()` → 設為 IDLE（清空影像、清空 state）
- [ ] 「重新回饋」（清空答案）：**不改變** AppState，維持 REVIEWING

---

### Task 1：Drawer Sensor 整合進 ui.py（新增）

**目標**：MN96100C 背景持續偵測，狀態從「非完全閉合」→「完全閉合」時觸發分析。

#### 1a. 初始化（`_init_drawer_sensor()`）

```python
def _init_drawer_sensor(self):
    """初始化 MN96100C 2.5D 抽屜感測器"""
    from eminent.sensors.vision2p5d import VideoCapture, MN96100CConfig
    from utils.depth_analysis import DepthAnalyzer, DrawerStateDetector
    import yaml

    cfg = yaml.safe_load(open("config/drawer_config.yaml"))

    self._drawer_cap = VideoCapture(
        vid=cfg['camera']['vid'],
        pid=cfg['camera']['pid'],
        frame_rate=getattr(MN96100CConfig.FrameRate, cfg['camera']['frame_rate']),
        led_current=getattr(MN96100CConfig.LEDCurrent, cfg['camera']['led_current']),
    )
    self._drawer_analyzer = DepthAnalyzer()
    self._drawer_detector = DrawerStateDetector(
        threshold_open=cfg['thresholds']['open'],
        threshold_closed=cfg['thresholds']['closed'],
        min_state_duration=cfg['analysis']['min_state_duration'],
    )
    self._drawer_sma_window = cfg['display']['smoothing_window']
    self._drawer_history = deque(maxlen=cfg['analysis']['history_size'])
    self._drawer_prev_state = None   # 前一幀的狀態（邊緣偵測用）
    self._drawer_running = False
    self._drawer_thread = None
```

**失敗處理**：若 MN96100C 未連接，`VideoCapture` 初始化失敗 → log 警告，`self._drawer_cap = None`，系統以「無抽屜感測」模式運行（可手動分析，或考慮保留「分析」按鈕作為 fallback）。

#### 1b. 背景執行緒（`_drawer_capture_loop()`）

```python
def _drawer_capture_loop(self):
    MAX_FAILURES = 30
    consecutive_failures = 0

    while self._drawer_running:
        ret, frame = self._drawer_cap.read()

        if not ret or frame is None:
            consecutive_failures += 1
            if consecutive_failures >= MAX_FAILURES:
                self.root.after(0, self._on_drawer_disconnect)
                break
            time.sleep(0.1)
            continue

        consecutive_failures = 0

        # ROI 擷取
        cfg = self.config['roi'] if hasattr(self, '_drawer_cfg') else ...
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # （依 config 決定是否裁切 ROI）

        # 計算 intensity
        metrics = self._drawer_analyzer.calculate_depth_metrics(gray)
        self._drawer_history.append(metrics['mean'])

        # SMA
        n = self._drawer_sma_window
        recent = list(self._drawer_history)[-n:]
        sma = sum(recent) / len(recent)

        # 狀態偵測
        new_state = self._drawer_detector.update(sma)

        # 邊緣偵測：「非完全閉合」→「完全閉合」
        if (self._drawer_prev_state != "完全閉合"
                and new_state == "完全閉合"
                and self._drawer_prev_state is not None):
            self.root.after(0, self._on_drawer_closed)

        self._drawer_prev_state = new_state
```

#### 1c. 事件處理（`_on_drawer_closed()`）

```python
def _on_drawer_closed(self):
    """抽屜閉合事件（UI 執行緒）"""
    if self._app_state != AppState.IDLE:
        return   # ANALYSING 或 REVIEWING 中，忽略
    self._on_analyse()
```

#### 1d. 執行緒管理

- [ ] `App.__init__` 最後：呼叫 `_init_drawer_sensor()`，若成功則 `_start_drawer_monitoring()`
- [ ] `_start_drawer_monitoring()`：啟動 daemon thread
- [ ] `_stop_drawer_monitoring()`：設 `_drawer_running = False`，join thread，release cap
- [ ] `_on_close()`：加入 `_stop_drawer_monitoring()`

#### 1e. Topbar 調整

- [ ] 移除「分析」按鈕
- [ ] 若 `self._drawer_cap is None`（感測器不存在）：保留「分析」按鈕作為手動 fallback

---

### Task 2：資料模型重構（utils/types.py）

**目標**：從 pill-centric 改為 drug-centric 資料模型。

#### 新 dataclass

```python
@dataclass
class DrugItem:
    key: str            # "A1", "A2", "B1"…
    count: int          # 顆數（此實作中固定為 1）
    color_hex: str      # "#ED7D31"（badge 顏色）
    crop_img: np.ndarray | None  # 從原圖裁切的 56×56 BGR 圖（供圖示用）
    bbox_pct: tuple[float, float, float, float]  # (left%, top%, w%, h%) 供 hotspot 用

@dataclass
class DrugPage:
    code: str           # "A", "B"…（ABCDE…順序）
    title: str          # 藥品全名（MatchResult.name）
    license_number: str
    items: list[DrugItem]

@dataclass
class VerificationState:
    tray_id: str = ""
    timestamp: str = ""
    total_kinds: int = 0        # len(drugs)
    total_pills: int = 0        # sum of all item.count
    variety_correct: bool | None = None
    total_correct: bool | None = None
    drugs: list[DrugPage] = field(default_factory=list)
    current_drug_index: int = 0
    name_answers: list[bool | None] = field(default_factory=list)   # len = len(drugs)
    dose_answers: dict[str, bool | None] = field(default_factory=dict)  # key = item.key
```

#### `_update_state_from_results()` 重寫邏輯

```
Detection list + MatchResult list
    ↓
1. 以 license_number 分組
   - 未識別（result=None）單獨一組，code="?"
2. 依出現順序分配 code（A, B, C…）
3. 每組內依 Detection 順序分配 item key（A1, A2, B1…）
4. 每個 DrugItem：
   - crop_img = frame[y1:y2, x1:x2]（resize to 56×56）
   - bbox_pct = (x1/W, y1/H, (x2-x1)/W, (y2-y1)/H)
5. 計算 total_kinds, total_pills
6. 初始化 name_answers（長度 = len(drugs)，全 None）
7. 初始化 dose_answers（{item.key: None for all items}）
```

- [ ] 新增 `DrugItem`, `DrugPage` 到 `utils/types.py`
- [ ] 重寫 `VerificationState`（移除舊 `pills`, `PillEntry`）
- [ ] 重寫 `_update_state_from_results()`
- [ ] 移除 `PillEntry`（確認無其他引用後）

---

### Task 3：右側面板 UI 重構（`_build_right_panel`）

**目標**：多 dose 列 + 虛擬捲動（▲▼，overflow 才顯示）。

#### 3a. 靜態結構（固定部分）

- [ ] 全域摘要區：品項列 + 總量列（現行保留）
- [ ] 藥品面板 `drug_frame`：
  - 藥品名稱 Label：`bg="#81C7D4"`, `min_height=88px`
  - 名稱核對列（固定）
  - `self._dose_container`：`tk.Frame`，用來放 ▲/dose 列/▼（動態 re-render）
  - 共計標籤（固定）
  - Footer nav：上一種 / 第N種/共M種 / 下一種（固定）

#### 3b. 虛擬捲動實作

新增狀態：
```python
self._dose_scroll_offset: int = 0
self._dose_visible_count: int = 2   # 初始預設，由 _calc_dose_visible_count() 動態修正
```

`_calc_dose_visible_count()`：
```python
DOSE_ROW_H = 70
panel_h = self.drug_frame.winfo_height()
fixed_h = 88 + 44 + 50 + 52 + 60   # 名稱+名稱核對+共計+nav+padding
self._dose_visible_count = max(1, (panel_h - fixed_h) // DOSE_ROW_H)
```
→ 綁定到 `drug_frame` 的 `<Configure>` 事件（視窗 resize 時自動重算）

`_render_dose_rows(drug_page)`：
```python
items = drug_page.items
total = len(items)
offset = self._dose_scroll_offset
visible = self._dose_visible_count
overflow = total > visible

# 清空 _dose_container 舊內容
for w in self._dose_container.winfo_children():
    w.destroy()

# ▲（只有 overflow 且 offset > 0 才 pack）
if overflow and offset > 0:
    tk.Button(_dose_container, text="▲", height=2,
              command=self._dose_scroll_up).pack(fill=tk.X)

# 顯示 items[offset : offset+visible]
for item in items[offset : offset + visible]:
    self._render_single_dose_row(item)

# ▼（只有 overflow 且後面還有才 pack）
if overflow and offset + visible < total:
    tk.Button(_dose_container, text="▼", height=2,
              command=self._dose_scroll_down).pack(fill=tk.X)
```

`_dose_scroll_up()` / `_dose_scroll_down()`：
- offset ±= 1 → `_render_dose_rows(current_drug)`

換藥種（上一種/下一種）時：`self._dose_scroll_offset = 0` → re-render

#### 3c. 單列 dose row（`_render_single_dose_row(item)`）

```
[icon 56px] [數量] [count num] [顆] [正確 btn 100px] [錯誤 btn 100px]
```

- icon：`item.crop_img` resize 56×56 → `ImageTk.PhotoImage` → `tk.Label`
- 正確/錯誤按鈕 height ≥ 44px（觸控友善）
- bind：`<Enter>` → `showImageHighlight(item.key)`；`<Leave>` → hide
- 點擊正確/錯誤 → `_set_dose(item.key, value)` + `showImageHighlight(item.key)` + auto-AI

- [ ] 完成上述所有實作

---

### Task 4：左圖 Hotspot Highlight 系統

**目標**：點擊或 hover dose 列 → 左圖對應藥錠位置顯示紅色框線。

#### 實作方式

在 `image_label`（左圖 Label）上方疊加一個透明 Frame，內有絕對定位的紅色框 Frame：

```python
# 建置（在 _build_content 中）
self._hl_canvas = tk.Frame(self.left_panel, bg="", highlightthickness=0)
self._hl_canvas.place(relx=0, rely=0, relwidth=1, relheight=1)
self._hl_rect = tk.Frame(
    self._hl_canvas,
    bg="",
    highlightbackground="#ff3333",
    highlightthickness=3
)
# 預設隱藏
self._hl_rect.place_forget()
```

`showImageHighlight(item_key)`：
```python
if self.current_tab != "ai":
    return
drug = self.state.drugs[self.state.current_drug_index]
item = next((it for it in drug.items if it.key == item_key), None)
if item is None:
    return
lp, tp, wp, hp = item.bbox_pct
pw = self.left_panel.winfo_width()
ph = self.left_panel.winfo_height()
self._hl_rect.place(
    x=int(lp * pw), y=int(tp * ph),
    width=int(wp * pw), height=int(hp * ph)
)
```

`hideImageHighlight()`：
```python
self._hl_rect.place_forget()
```

- [ ] 建立 `_hl_canvas` 和 `_hl_rect`
- [ ] 實作 `showImageHighlight()` 和 `hideImageHighlight()`
- [ ] dose row bind `<Enter>` / `<Leave>` / 按鈕 click
- [ ] 切換 tab（cam↔ai）時：if ai → 重新顯示當前 focus；if cam → 隱藏

---

### Task 5：分頁導航邏輯調整

- [ ] `current_page`（pill index）→ `current_drug_index`（drug index）
- [ ] `_prev_drug()` / `_next_drug()`：改用 `current_drug_index`，同時重置 `_dose_scroll_offset = 0`
- [ ] `page_label`：「第 N 種/共 M 種」
- [ ] `_update_info_panel()`：從 `drugs[current_drug_index]` 取資料渲染

---

### Task 6：確認邏輯調整

- [ ] `_set_name(value)`：`name_answers[current_drug_index] = value`
- [ ] `_set_dose(item_key, value)`：`dose_answers[item_key] = value`
- [ ] `_find_first_missing()` 重寫：
  ```
  1. variety_correct is None → (0, ["variety"])
  2. total_correct is None → (0, ["total"])
  3. 逐 drug i: name_answers[i] is None → (i, ["name"])
  4. 逐 drug i, item k: dose_answers[item.key] is None → (i, [item.key])
  5. 全填完 → None
  ```
  回傳 `(drug_index, [missing_keys])` 或 `None`
- [ ] 「重新回饋」：清空所有 answers（name_answers 全 None，dose_answers 全 None，variety/total_correct = None）

---

### Task 7：「完成」Modal 重構

**目標**：in-place backdrop（取代 Tkinter Toplevel）+ 層次化 feedback list + Toast。

#### Backdrop Modal

```python
def _show_modal(self):
    # 深灰半透明背景（Tkinter 無原生 alpha，用深灰色近似）
    self._backdrop = tk.Frame(self.root, bg="#333333")
    self._backdrop.place(relx=0, rely=0, relwidth=1, relheight=1)

    # 置中卡片
    card = tk.Frame(self._backdrop, bg="white", relief=tk.SOLID, bd=1)
    card.place(relx=0.5, rely=0.1, anchor=tk.N,
               width=min(600, self.root.winfo_width()-40))
    # ... modal 內容建置
```

#### Feedback List 層次

```
總品項 5 種           → 正確
總數量 9 顆           → 正確
── BOTERASU TABLETS… ──
    品項核對          → 正確
    A1 數量 1 顆      → 正確
    A2 數量 1 顆      → 錯誤
── D-CURE CALCIUM… ──
    ...
```

#### Toast

```python
def _show_toast(self, message="儲存完成", duration_ms=1500):
    toast = tk.Label(
        self.root, text=message,
        bg="#3a6186", fg="white",
        font=("Microsoft JhengHei", 20, "bold"),
        padx=24, pady=16
    )
    toast.place(relx=0.5, rely=0.25, anchor=tk.CENTER)
    self.root.after(duration_ms, toast.destroy)
```

- [ ] 實作 backdrop modal（取代 Toplevel）
- [ ] 實作層次化 feedback list（drug header + 縮排 items）
- [ ] 實作 Toast
- [ ] 「儲存」按鈕：寫檔 → destroy modal → show toast → `_reset_state()` → AppState.IDLE

---

### Task 8：樣式調整

- [ ] 視窗尺寸：依螢幕自動（`fullscreen` 模式時自動填滿）；視窗模式保持 1024×600
- [ ] 藥品名稱 Label：`bg="#81C7D4"`
- [ ] ▲▼ 按鈕高度：`height=2`（約 50px），`fill=tk.X`（全寬易按）
- [ ] topbar：維持現行深色（#1f2f46），保持視覺一致性

---

### Task 9：藥品圖示（DrugItem.crop_img）

**決定**：從偵測 bbox 裁切原圖，resize 為 56×56 BGR。

- [ ] 在 `_update_state_from_results()` 中：
  ```python
  x1, y1, x2, y2 = det.bbox
  crop = frame[y1:y2, x1:x2]
  crop_resized = cv2.resize(crop, (56, 56))
  ```
- [ ] `DrugItem.crop_img` 儲存此裁切圖
- [ ] `_render_single_dose_row()` 中將 BGR → RGB → `ImageTk.PhotoImage` 顯示
- [ ] 注意：`PhotoImage` 需掛在 widget 上防止 GC（`label.image = photo`）

---

## 6. 實作順序

```
Phase 1：狀態機與觸發機制（基礎）
  Task 0：AppState 狀態機
  Task 1：Drawer Sensor 整合（背景執行緒 + 邊緣觸發）

Phase 2：資料模型（核心邏輯）
  Task 2：DrugItem / DrugPage / VerificationState 重構

Phase 3：UI 對齊設計稿
  Task 3：右側面板重構（多 dose 列 + 虛擬捲動）
  Task 5：分頁導航調整
  Task 6：確認邏輯調整

Phase 4：互動增強
  Task 4：Hotspot Highlight 系統
  Task 7：完成 Modal 重構（backdrop + Toast）
  Task 9：藥品圖示（裁切原圖）

Phase 5：收尾
  Task 8：樣式微調
  整合測試（debug mode 驗證）
```

---

## 7. 待釐清事項

| # | 問題 | 影響 Task |
|---|------|----------|
| 1 | MN96100C 感測器不在時（未連接），是否保留「分析」按鈕作為 fallback？ | Task 1e |
| 2 | 藥盤序號格式：繼續自動遞增 6 位，或改為讀取外部資料（如條碼/HIS）？ | Task 2 |
| 3 | 「重新回饋」後，左圖是否保持顯示（維持 REVIEWING）？ | Task 7 |
| 4 | 同一種藥多顆時，AI 圖 hotspot 各自獨立框（A1/A2 各一個框）？還是整體框選該藥的所有顆？ | Task 4 |
| 5 | 「完成」後回到 IDLE 黑畫面，topbar 的藥盤序號是否立即更新為下一個序號？ | Task 0 |
| 6 | debug mode（`--debug`）下，MN96100C 感測器是否也跳過（直接以按鈕觸發）？ | Task 1 |
