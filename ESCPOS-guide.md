# ESC/POS 指令解碼器 + 智慧回覆 技術文件

## 概覽

`code/escpos_decoder.py` 實作完整的 ESC/POS 指令解碼與智慧回覆功能，整合於 `code/test_gatt.py` 的 `PrintWriteCharacteristic` 中。

**功能：**
1. 狀態機式 ESC/POS 解碼器，處理跨 BLE 封包的指令邊界
2. 將收到的列印資料解析為人類可讀的指令並記錄到 log 檔
3. 偵測到狀態查詢指令時，透過 ff01 回傳正確格式的狀態回覆

## 檔案結構

| 檔案 | 說明 |
|------|------|
| `code/escpos_decoder.py` | ESC/POS 狀態機解碼器 + 回覆產生器 |
| `code/test_gatt.py` | BLE GATT 伺服器，整合解碼器進行智慧回覆 |
| `logs/escpos_*.log` | 執行時自動產生的指令 log 檔 |

## 架構設計

### 狀態機

```
ParserState: IDLE → ESC_PREFIX/GS_PREFIX/DLE_PREFIX/FS_PREFIX → PARAM_FIXED → PARAM_VARIABLE
```

處理跨 BLE 封包的指令邊界：當一個指令被分割到兩個 BLE 封包時（例如 `0x1B` 和 `0x40` 分開到達），解碼器透過內部緩衝區保持狀態，直到收集到完整指令才進行解碼。

### 核心類別

- `ESCPOSDecoder` — 帶緩衝區的狀態機，`feed(data)` 回傳 `(commands, responses)`
- `ESCPOSCommand` — dataclass（時間戳、助記符、中文名稱、參數、原始 bytes）

### 使用方式

```python
from escpos_decoder import ESCPOSDecoder

decoder = ESCPOSDecoder()             # log_dir 預設為 'logs'
commands, responses = decoder.feed(data)
# commands: List[ESCPOSCommand] — 解碼的指令列表
# responses: List[bytes] — 需透過 notify 回傳的回覆資料
```

### 整合方式（test_gatt.py）

```python
class PrintWriteCharacteristic(Characteristic):
    def __init__(self, bus, index, service, uuid, flags):
        super().__init__(bus, index, service, uuid, flags)
        self.decoder = ESCPOSDecoder()

    def WriteValue(self, value, options):
        data = bytes(value)
        commands, responses = self.decoder.feed(data)
        # 智慧回覆：有特定回覆時送出，否則回傳標準 ACK (0x00)
        if responses:
            for resp in responses:
                GLib.idle_add(lambda r=resp: self._send_response(r))
        else:
            GLib.idle_add(lambda: self._send_response(bytes([0x00])))
```

## 支援的指令群組

### 1. 控制字元

| Byte | 助記符 | 說明 |
|------|--------|------|
| `0x0A` | LF | 列印並換行 |
| `0x0D` | CR | 歸位 |
| `0x09` | HT | 水平定位 |
| `0x0C` | FF | 列印並換頁 |

### 2. ESC 指令 (0x1B)

| 第二 byte | 助記符 | 說明 | 參數長度 |
|-----------|--------|------|----------|
| `0x40` | ESC @ | 初始化印表機 | 0 |
| `0x21` | ESC ! | 選擇列印模式 | 1 |
| `0x61` | ESC a | 選擇對齊方式 | 1 |
| `0x64` | ESC d | 列印並進紙 n 行 | 1 |
| `0x45` | ESC E | 選擇加粗模式 | 1 |
| `0x4A` | ESC J | 列印並進紙 n 點 | 1 |
| `0x32` | ESC 2 | 選擇預設行距 | 0 |
| `0x33` | ESC 3 | 設定行距 | 1 |
| `0x2D` | ESC - | 底線模式 | 1 |
| `0x4D` | ESC M | 選擇字型 | 1 |
| `0x24` | ESC $ | 設定絕對列印位置 | 2 |
| `0x74` | ESC t | 選擇字元碼頁 | 1 |
| `0x52` | ESC R | 選擇國際字元集 | 1 |
| `0x56` | ESC V | 選擇旋轉列印 | 1 |
| `0x72` | ESC r | 選擇列印顏色 | 1 |
| `0x42` | ESC B | 選擇/取消黑白反轉 | 1 |
| `0x47` | ESC G | 選擇雙重列印 | 1 |
| `0x70` | ESC p | 產生錢箱脈衝 | 2 |
| `0x76` | ESC v | 傳送紙張感測器狀態 | 0 |
| `0x7B` | ESC { | 選擇倒置列印 | 1 |
| `0x2A` | ESC * | 選擇位元映像模式 | **變長** |
| `0x44` | ESC D | 設定水平定位 | **變長** (NUL 結尾) |

### 3. GS 指令 (0x1D)

| 第二 byte | 助記符 | 說明 | 參數長度 |
|-----------|--------|------|----------|
| `0x21` | GS ! | 選擇字元大小 | 1 |
| `0x42` | GS B | 選擇/取消黑白反轉 | 1 |
| `0x48` | GS H | 選擇 HRI 字元列印位置 | 1 |
| `0x68` | GS h | 設定條碼高度 | 1 |
| `0x77` | GS w | 設定條碼寬度 | 1 |
| `0x66` | GS f | 選擇 HRI 字型 | 1 |
| `0x61` | GS a | 啟用/停用 ASB | 1 |
| `0x4C` | GS L | 設定左邊界 | 2 |
| `0x57` | GS W | 設定列印區域寬度 | 2 |
| `0x72` | GS r | 傳送狀態 | 1 |
| `0x49` | GS I | 傳送印表機 ID | 1 |
| `0x56` | GS V | 選擇切紙模式 | **變長** (1-2) |
| `0x76 0x30` | GS v 0 | 列印光柵點陣圖 | **變長** |
| `0x28 0x4C` | GS ( L | 擴充圖形功能 | **變長** (pL/pH) |
| `0x6B` | GS k | 列印條碼 | **變長** |

### 4. DLE 指令 (0x10)

| 第二 byte | 助記符 | 說明 | 參數長度 |
|-----------|--------|------|----------|
| `0x04` | DLE EOT | 即時狀態查詢 | 1 |
| `0x14` | DLE DC4 | 即時控制 | 3 |
| `0x05` | DLE ENQ | 即時請求 | 1 |

### 5. FS 指令 (0x1C)

| 第二 byte | 助記符 | 說明 | 參數長度 |
|-----------|--------|------|----------|
| `0x21` | FS ! | 設定中文列印模式 | 1 |
| `0x26` | FS & | 選擇中文模式 | 0 |
| `0x2E` | FS . | 取消中文模式 | 0 |
| `0x2D` | FS - | 中文底線模式 | 1 |
| `0x70` | FS p | 列印下載點陣圖 | 2 |

### 6. 文字資料

連續的非指令位元組會被收集為文字資料，嘗試以下編碼順序解碼：GBK → UTF-8 → Latin-1。

## 特殊變長指令處理

| 指令 | 長度計算方式 |
|------|-------------|
| `ESC *` | 讀取 m, nL, nH；模式 0/1: n bytes, 模式 32/33: n*3 bytes |
| `ESC D` | 讀取定位值直到遇到 NUL (0x00) |
| `GS v 0` | 讀取 m, xL, xH, yL, yH；資料長度 = x * y bytes |
| `GS ( L` | 讀取 pL, pH；資料長度 = pL + pH*256 bytes |
| `GS k` | Format A (m≤6): NUL 結尾；Format B (m>6): 下一 byte 為長度 |
| `GS V` | 模式 0/1/48/49: 無額外參數；模式 65/66: 額外 1 byte |

## 智慧回覆產生器

`feed()` 回傳的 `responses` 列表包含需要透過 ff01 notify 回傳給客戶端的資料：

| 收到的指令 | Hex | 回覆內容 | 說明 |
|-----------|-----|---------|------|
| DLE EOT 1 | `10 04 01` | `0x16` | 印表機在線、無錯誤 |
| DLE EOT 2 | `10 04 02` | `0x12` | 離線狀態正常 |
| DLE EOT 3 | `10 04 03` | `0x12` | 無錯誤 |
| DLE EOT 4 | `10 04 04` | `0x12` | 紙張充足 |
| GS I 1 | `1D 49 01` | `BT-B36` | 印表機型號 |
| GS I 2 | `1D 49 02` | `0x02` | 印表機類型 |
| GS I 3 | `1D 49 03` | `0.1.3` | 韌體版本 |
| GS r 1 | `1D 72 01` | `0x00` | 紙張狀態正常 |
| GS r 2 | `1D 72 02` | `0x00` | 錢箱狀態 |
| GS a n | `1D 61 n` | （無回覆） | 設定 ASB，記錄 n 值 |
| ESC v | `1B 76` | `0x00` | 紙張感測器正常 |
| 其他一般指令 | — | `0x00` | 標準 ACK（由 test_gatt.py 發送） |

## Log 輸出

**檔案位置：** `logs/escpos_YYYYMMDD_HHMMSS.log`（自動建立 `logs/` 目錄）

同時透過 Python `logging` 輸出到 FileHandler（UTF-8）和 StreamHandler（終端）。

**格式範例：**
```
[2026-02-12T14:30:05.123] --- ESC/POS 解碼器啟動 ---
[2026-02-12T14:30:05.123] PKT  收到 14 bytes: 1b 40 1b 61 01 1b 21 00 48 65 6c 6c 6f 0a
[2026-02-12T14:30:05.123] CMD  ESC @        初始化印表機               | 1b 40
[2026-02-12T14:30:05.123] CMD  ESC a        選擇對齊方式    n=1 (置中) | 1b 61 01
[2026-02-12T14:30:05.123] CMD  ESC !        選擇列印模式    n=0x00 (Font A) | 1b 21 00
[2026-02-12T14:30:05.123] CMD  TEXT                          "Hello"   | 48 65 6c 6c 6f
[2026-02-12T14:30:05.123] CMD  LF           列印並換行                 | 0a
[2026-02-12T14:30:06.000] PKT  收到 3 bytes: 10 04 01
[2026-02-12T14:30:06.000] CMD  DLE EOT      即時狀態查詢    n=1 (印表機狀態) | 10 04 01
[2026-02-12T14:30:06.000] RSP  → 回覆狀態   0x16 (在線、無錯誤)       | 16
```

**Log 欄位說明：**
- `PKT` — 收到的原始 BLE 封包
- `CMD` — 解碼後的指令（助記符 + 中文名稱 + 參數 + 原始 hex）
- `RSP` — 透過 ff01 回傳的回覆資料
- `TEXT` — 收到的文字資料

## 驗證方式

1. 用 nRF Connect 手動送 `1B 40`（ESC @），確認 log 記錄且收到 `0x00` ACK
2. 送 `10 04 01`（DLE EOT 1），確認收到 `0x16` 狀態回覆而非 `0x00`
3. 送 `1D 49 01`（GS I 1），確認收到 `BT-B36` 型號字串
4. 測試跨封包：分兩次送 `1B` 和 `40`，確認正確解碼
5. 檢查 `logs/` 目錄下的 log 檔格式是否正確
