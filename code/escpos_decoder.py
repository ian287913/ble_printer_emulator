#!/usr/bin/env python3
"""
ESC/POS 指令解碼器 + 智慧回覆產生器

狀態機式解析器，處理跨 BLE 封包的指令邊界。
將收到的列印資料解析為人類可讀的指令記錄到 log 檔，
並在偵測到狀態查詢指令時產生正確格式的回覆。
"""

import os
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import List, Tuple, Optional


# === 資料結構 ===

@dataclass
class ESCPOSCommand:
    """解碼後的 ESC/POS 指令"""
    timestamp: str
    mnemonic: str       # 例如 "ESC @", "GS v 0"
    name: str           # 中文名稱
    params: str         # 參數描述
    raw: bytes          # 原始位元組


class ParserState(Enum):
    IDLE = auto()
    ESC_PREFIX = auto()      # 收到 0x1B
    GS_PREFIX = auto()       # 收到 0x1D
    DLE_PREFIX = auto()      # 收到 0x10
    FS_PREFIX = auto()       # 收到 0x1C
    PARAM_FIXED = auto()     # 等待固定數量參數
    PARAM_VARIABLE = auto()  # 等待變長資料


# === 指令定義表 ===

# ESC (0x1B) 指令：第二位元組 -> (助記符, 中文名稱, 固定參數長度)
ESC_COMMANDS = {
    0x40: ('ESC @', '初始化印表機', 0),
    0x21: ('ESC !', '選擇列印模式', 1),
    0x61: ('ESC a', '選擇對齊方式', 1),
    0x64: ('ESC d', '列印並進紙 n 行', 1),
    0x45: ('ESC E', '選擇加粗模式', 1),
    0x4A: ('ESC J', '列印並進紙 n 點', 1),
    0x32: ('ESC 2', '選擇預設行距', 0),
    0x33: ('ESC 3', '設定行距', 1),
    0x2D: ('ESC -', '底線模式', 1),
    0x4D: ('ESC M', '選擇字型', 1),
    0x24: ('ESC $', '設定絕對列印位置', 2),
    0x74: ('ESC t', '選擇字元碼頁', 1),
    0x52: ('ESC R', '選擇國際字元集', 1),
    0x56: ('ESC V', '選擇旋轉列印', 1),
    0x72: ('ESC r', '選擇列印顏色', 1),
    0x42: ('ESC B', '選擇/取消黑白反轉', 1),
    0x47: ('ESC G', '選擇雙重列印', 1),
    0x70: ('ESC p', '產生錢箱脈衝', 2),
    0x63: ('ESC c', '選擇列印頁模式', 1),  # ESC c 有子命令
    0x76: ('ESC v', '傳送紙張感測器狀態', 0),
    0x69: ('ESC i', '全切紙', 0),
    0x7B: ('ESC {', '選擇倒置列印', 1),
    # 特殊處理：ESC * (點陣圖), ESC D (定位)
}

# GS (0x1D) 指令：第二位元組 -> (助記符, 中文名稱, 固定參數長度)
GS_COMMANDS = {
    0x21: ('GS !', '選擇字元大小', 1),
    0x42: ('GS B', '選擇/取消黑白反轉', 1),
    0x48: ('GS H', '選擇 HRI 字元列印位置', 1),
    0x68: ('GS h', '設定條碼高度', 1),
    0x77: ('GS w', '設定條碼寬度', 1),
    0x66: ('GS f', '選擇 HRI 字型', 1),
    0x61: ('GS a', '啟用/停用 ASB', 1),
    0x4C: ('GS L', '設定左邊界', 2),
    0x57: ('GS W', '設定列印區域寬度', 2),
    0x72: ('GS r', '傳送狀態', 1),
    0x49: ('GS I', '傳送印表機 ID', 1),
    # 特殊處理：GS V (切紙), GS v 0 (點陣圖), GS ( L (擴充), GS k (條碼)
}

# DLE (0x10) 指令
DLE_COMMANDS = {
    0x04: ('DLE EOT', '即時狀態查詢', 1),   # DLE EOT n
    0x14: ('DLE DC4', '即時控制', 3),        # DLE DC4 fn m t
    0x05: ('DLE ENQ', '即時請求', 1),        # DLE ENQ n
}

# FS (0x1C) 指令
FS_COMMANDS = {
    0x21: ('FS !', '設定中文列印模式', 1),
    0x26: ('FS &', '選擇中文模式', 0),
    0x2E: ('FS .', '取消中文模式', 0),
    0x2D: ('FS -', '中文底線模式', 1),
    0x70: ('FS p', '列印下載點陣圖', 2),    # FS p n m
}

# 控制字元
CONTROL_CHARS = {
    0x0A: ('LF', '列印並換行'),
    0x0D: ('CR', '歸位'),
    0x09: ('HT', '水平定位'),
    0x0C: ('FF', '列印並換頁'),
}

# ESC ! 列印模式位元說明
PRINT_MODE_BITS = {
    0x01: 'Font B',
    0x08: '加粗',
    0x10: '倍高',
    0x20: '倍寬',
    0x80: '底線',
}

# ESC a 對齊方式
ALIGNMENT = {0: '靠左', 1: '置中', 2: '靠右'}

# GS V 切紙模式
CUT_MODE = {0: '全切', 1: '部分切', 48: '全切', 49: '部分切', 65: '進紙後全切', 66: '進紙後部分切'}


# === Log 設定 ===

def setup_logger(log_dir='logs'):
    """設定檔案 + 終端雙輸出 logger"""
    # 確保 log 目錄存在
    os.makedirs(log_dir, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = os.path.join(log_dir, f'escpos_{timestamp}.log')

    logger = logging.getLogger('escpos')
    logger.setLevel(logging.DEBUG)

    # 避免重複 handler
    if logger.handlers:
        return logger

    fmt = logging.Formatter('[%(asctime)s.%(msecs)03d] %(message)s',
                            datefmt='%Y-%m-%dT%H:%M:%S')

    # 檔案輸出
    fh = logging.FileHandler(log_file, encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # 終端輸出
    sh = logging.StreamHandler()
    sh.setLevel(logging.DEBUG)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    logger.info('--- ESC/POS 解碼器啟動 ---')
    logger.info('Log 檔案: %s', log_file)

    return logger


# === 工具函式 ===

def hex_dump(data: bytes) -> str:
    """格式化 hex 輸出，每 byte 用空格隔開"""
    return ' '.join(f'{b:02x}' for b in data)


def describe_print_mode(n: int) -> str:
    """解析 ESC ! 的列印模式位元"""
    if n == 0:
        return 'Font A'
    parts = []
    for bit, desc in PRINT_MODE_BITS.items():
        if n & bit:
            parts.append(desc)
    return ', '.join(parts) if parts else f'0x{n:02x}'


# === 解碼器核心 ===

class ESCPOSDecoder:
    """
    ESC/POS 狀態機解碼器

    使用方式：
        decoder = ESCPOSDecoder()
        commands, responses = decoder.feed(data)
    """

    def __init__(self, log_dir='logs'):
        self.logger = setup_logger(log_dir)
        self.state = ParserState.IDLE
        self.buffer = bytearray()

        # 變長指令等待狀態
        self._pending_mnemonic = ''
        self._pending_name = ''
        self._pending_params_needed = 0  # 還需幾個 byte
        self._pending_raw_start = bytearray()  # 已收到的指令前綴

        # ASB（自動狀態回傳）設定
        self.asb_enabled = 0  # GS a n 的 n 值

    def feed(self, data: bytes) -> Tuple[List[ESCPOSCommand], List[bytes]]:
        """
        餵入資料，回傳 (解碼的指令列表, 需回傳的回覆列表)

        Args:
            data: 收到的 BLE 封包資料

        Returns:
            (commands, responses) — commands 為解碼結果，responses 為需透過 notify 回傳的資料
        """
        self.logger.info('PKT  收到 %d bytes: %s', len(data), hex_dump(data))

        self.buffer.extend(data)
        commands = []
        responses = []

        while self.buffer:
            if self.state == ParserState.IDLE:
                result = self._parse_idle(commands, responses)
            elif self.state == ParserState.ESC_PREFIX:
                result = self._parse_esc(commands, responses)
            elif self.state == ParserState.GS_PREFIX:
                result = self._parse_gs(commands, responses)
            elif self.state == ParserState.DLE_PREFIX:
                result = self._parse_dle(commands, responses)
            elif self.state == ParserState.FS_PREFIX:
                result = self._parse_fs(commands, responses)
            elif self.state == ParserState.PARAM_FIXED:
                result = self._parse_param_fixed(commands, responses)
            elif self.state == ParserState.PARAM_VARIABLE:
                result = self._parse_param_variable(commands, responses)
            else:
                # 不應到達，重置
                self.state = ParserState.IDLE
                result = True

            if not result:
                # 資料不足，等下一包
                break

        return commands, responses

    # --- IDLE 狀態 ---

    def _parse_idle(self, commands, responses) -> bool:
        b = self.buffer[0]

        if b == 0x1B:  # ESC
            self.state = ParserState.ESC_PREFIX
            self._pending_raw_start = bytearray([self.buffer.pop(0)])
            return True
        elif b == 0x1D:  # GS
            self.state = ParserState.GS_PREFIX
            self._pending_raw_start = bytearray([self.buffer.pop(0)])
            return True
        elif b == 0x10:  # DLE
            self.state = ParserState.DLE_PREFIX
            self._pending_raw_start = bytearray([self.buffer.pop(0)])
            return True
        elif b == 0x1C:  # FS
            self.state = ParserState.FS_PREFIX
            self._pending_raw_start = bytearray([self.buffer.pop(0)])
            return True
        elif b in CONTROL_CHARS:
            mnemonic, name = CONTROL_CHARS[b]
            raw = bytes([self.buffer.pop(0)])
            cmd = self._make_cmd(mnemonic, name, '', raw)
            commands.append(cmd)
            self._log_cmd(cmd)
            return True
        else:
            # 文字資料：收集連續非指令位元組
            return self._parse_text(commands)

    # --- ESC 前綴 ---

    def _parse_esc(self, commands, responses) -> bool:
        if not self.buffer:
            return False

        b = self.buffer[0]

        # ESC * — 位元模式點陣圖（變長）
        if b == 0x2A:
            self.buffer.pop(0)
            self._pending_raw_start.append(0x2A)
            self._pending_mnemonic = 'ESC *'
            self._pending_name = '選擇位元映像模式'
            self._pending_params_needed = 2  # 先讀 m nL（再算資料長度）
            self.state = ParserState.PARAM_VARIABLE
            self._var_phase = 'esc_star_header'
            return True

        # ESC D — 水平定位（NUL 結尾）
        if b == 0x44:
            self.buffer.pop(0)
            self._pending_raw_start.append(0x44)
            self._pending_mnemonic = 'ESC D'
            self._pending_name = '設定水平定位'
            self.state = ParserState.PARAM_VARIABLE
            self._var_phase = 'esc_d_tabs'
            self._var_collected = bytearray()
            return True

        if b in ESC_COMMANDS:
            mnemonic, name, param_len = ESC_COMMANDS[b]
            self.buffer.pop(0)
            self._pending_raw_start.append(b)

            if param_len == 0:
                raw = bytes(self._pending_raw_start)
                params = ''
                cmd = self._make_cmd(mnemonic, name, params, raw)
                commands.append(cmd)
                self._log_cmd(cmd)
                resp = self._generate_response(mnemonic, raw, commands, responses)
                if resp is not None:
                    responses.append(resp)
                self.state = ParserState.IDLE
                return True
            else:
                self._pending_mnemonic = mnemonic
                self._pending_name = name
                self._pending_params_needed = param_len
                self.state = ParserState.PARAM_FIXED
                return True
        else:
            # 未知的 ESC 指令
            self._pending_raw_start.append(self.buffer.pop(0))
            raw = bytes(self._pending_raw_start)
            cmd = self._make_cmd(f'ESC 0x{b:02X}', '未知 ESC 指令', '', raw)
            commands.append(cmd)
            self._log_cmd(cmd)
            self.state = ParserState.IDLE
            return True

    # --- GS 前綴 ---

    def _parse_gs(self, commands, responses) -> bool:
        if not self.buffer:
            return False

        b = self.buffer[0]

        # GS V — 切紙（參數數量依模式而定）
        if b == 0x56:
            self.buffer.pop(0)
            self._pending_raw_start.append(0x56)
            self._pending_mnemonic = 'GS V'
            self._pending_name = '選擇切紙模式'
            # 先讀一個參數判斷模式
            self.state = ParserState.PARAM_VARIABLE
            self._var_phase = 'gs_v_mode'
            return True

        # GS v 0 — 點陣圖列印（變長）
        if b == 0x76:
            if len(self.buffer) < 2:
                return False
            if self.buffer[1] == 0x30:
                self.buffer.pop(0)  # v
                self.buffer.pop(0)  # 0
                self._pending_raw_start.extend([0x76, 0x30])
                self._pending_mnemonic = 'GS v 0'
                self._pending_name = '列印光柵點陣圖'
                self._pending_params_needed = 5  # m xL xH yL yH
                self.state = ParserState.PARAM_VARIABLE
                self._var_phase = 'gs_v0_header'
                return True
            # 不是 GS v 0，當作未知
            self.buffer.pop(0)
            self._pending_raw_start.append(0x76)
            raw = bytes(self._pending_raw_start)
            cmd = self._make_cmd('GS v', '未知 GS v 指令', '', raw)
            commands.append(cmd)
            self._log_cmd(cmd)
            self.state = ParserState.IDLE
            return True

        # GS ( L — 擴充圖形功能（變長，pL pH 定長度）
        if b == 0x28:
            if len(self.buffer) < 2:
                return False
            if self.buffer[1] == 0x4C:
                self.buffer.pop(0)  # (
                self.buffer.pop(0)  # L
                self._pending_raw_start.extend([0x28, 0x4C])
                self._pending_mnemonic = 'GS ( L'
                self._pending_name = '擴充圖形功能'
                self._pending_params_needed = 2  # pL pH
                self.state = ParserState.PARAM_VARIABLE
                self._var_phase = 'gs_paren_l_header'
                return True
            # 其他 GS ( 指令
            self.buffer.pop(0)
            sub = self.buffer.pop(0)
            self._pending_raw_start.extend([0x28, sub])
            # 讀 pL pH
            self._pending_mnemonic = f'GS ( {chr(sub)}'
            self._pending_name = '擴充功能'
            self._pending_params_needed = 2
            self.state = ParserState.PARAM_VARIABLE
            self._var_phase = 'gs_paren_generic_header'
            return True

        # GS k — 列印條碼（變長）
        if b == 0x6B:
            self.buffer.pop(0)
            self._pending_raw_start.append(0x6B)
            self._pending_mnemonic = 'GS k'
            self._pending_name = '列印條碼'
            self.state = ParserState.PARAM_VARIABLE
            self._var_phase = 'gs_k_type'
            return True

        if b in GS_COMMANDS:
            mnemonic, name, param_len = GS_COMMANDS[b]
            self.buffer.pop(0)
            self._pending_raw_start.append(b)

            if param_len == 0:
                raw = bytes(self._pending_raw_start)
                cmd = self._make_cmd(mnemonic, name, '', raw)
                commands.append(cmd)
                self._log_cmd(cmd)
                self.state = ParserState.IDLE
                return True
            else:
                self._pending_mnemonic = mnemonic
                self._pending_name = name
                self._pending_params_needed = param_len
                self.state = ParserState.PARAM_FIXED
                return True
        else:
            # 未知 GS 指令
            self._pending_raw_start.append(self.buffer.pop(0))
            raw = bytes(self._pending_raw_start)
            cmd = self._make_cmd(f'GS 0x{b:02X}', '未知 GS 指令', '', raw)
            commands.append(cmd)
            self._log_cmd(cmd)
            self.state = ParserState.IDLE
            return True

    # --- DLE 前綴 ---

    def _parse_dle(self, commands, responses) -> bool:
        if not self.buffer:
            return False

        b = self.buffer[0]
        if b in DLE_COMMANDS:
            mnemonic, name, param_len = DLE_COMMANDS[b]
            self.buffer.pop(0)
            self._pending_raw_start.append(b)
            self._pending_mnemonic = mnemonic
            self._pending_name = name
            self._pending_params_needed = param_len
            self.state = ParserState.PARAM_FIXED
            return True
        else:
            self._pending_raw_start.append(self.buffer.pop(0))
            raw = bytes(self._pending_raw_start)
            cmd = self._make_cmd(f'DLE 0x{b:02X}', '未知 DLE 指令', '', raw)
            commands.append(cmd)
            self._log_cmd(cmd)
            self.state = ParserState.IDLE
            return True

    # --- FS 前綴 ---

    def _parse_fs(self, commands, responses) -> bool:
        if not self.buffer:
            return False

        b = self.buffer[0]
        if b in FS_COMMANDS:
            mnemonic, name, param_len = FS_COMMANDS[b]
            self.buffer.pop(0)
            self._pending_raw_start.append(b)

            if param_len == 0:
                raw = bytes(self._pending_raw_start)
                cmd = self._make_cmd(mnemonic, name, '', raw)
                commands.append(cmd)
                self._log_cmd(cmd)
                self.state = ParserState.IDLE
                return True
            else:
                self._pending_mnemonic = mnemonic
                self._pending_name = name
                self._pending_params_needed = param_len
                self.state = ParserState.PARAM_FIXED
                return True
        else:
            self._pending_raw_start.append(self.buffer.pop(0))
            raw = bytes(self._pending_raw_start)
            cmd = self._make_cmd(f'FS 0x{b:02X}', '未知 FS 指令', '', raw)
            commands.append(cmd)
            self._log_cmd(cmd)
            self.state = ParserState.IDLE
            return True

    # --- 固定長度參數 ---

    def _parse_param_fixed(self, commands, responses) -> bool:
        if len(self.buffer) < self._pending_params_needed:
            return False

        params_bytes = bytes(self.buffer[:self._pending_params_needed])
        del self.buffer[:self._pending_params_needed]

        self._pending_raw_start.extend(params_bytes)
        raw = bytes(self._pending_raw_start)
        params = self._describe_params(self._pending_mnemonic, params_bytes)

        cmd = self._make_cmd(self._pending_mnemonic, self._pending_name, params, raw)
        commands.append(cmd)
        self._log_cmd(cmd)

        resp = self._generate_response(self._pending_mnemonic, raw, commands, responses)
        if resp is not None:
            responses.append(resp)

        self.state = ParserState.IDLE
        return True

    # --- 變長參數 ---

    def _parse_param_variable(self, commands, responses) -> bool:
        phase = self._var_phase

        # --- ESC * 點陣圖 ---
        if phase == 'esc_star_header':
            if len(self.buffer) < 3:
                return False
            m = self.buffer.pop(0)
            nL = self.buffer.pop(0)
            nH = self.buffer.pop(0)
            self._pending_raw_start.extend([m, nL, nH])
            n = nL + nH * 256
            # 資料長度依模式
            if m == 0 or m == 1:
                data_len = n
            elif m == 32 or m == 33:
                data_len = n * 3
            else:
                data_len = n
            self._var_data_len = data_len
            self._var_phase = 'esc_star_data'
            self._var_mode = m
            self._var_n = n
            return True

        if phase == 'esc_star_data':
            if len(self.buffer) < self._var_data_len:
                return False
            data = bytes(self.buffer[:self._var_data_len])
            del self.buffer[:self._var_data_len]
            self._pending_raw_start.extend(data)
            raw = bytes(self._pending_raw_start)
            params = f'm={self._var_mode}, 寬={self._var_n} 點, 資料={len(data)} bytes'
            cmd = self._make_cmd('ESC *', '選擇位元映像模式', params, raw)
            commands.append(cmd)
            self._log_cmd(cmd)
            self.state = ParserState.IDLE
            return True

        # --- ESC D 水平定位 ---
        if phase == 'esc_d_tabs':
            while self.buffer:
                b = self.buffer.pop(0)
                self._pending_raw_start.append(b)
                if b == 0x00:
                    # NUL 結尾
                    raw = bytes(self._pending_raw_start)
                    tabs = list(self._var_collected) if hasattr(self, '_var_collected') else []
                    params = f'定位: {", ".join(str(t) for t in tabs)}' if tabs else '清除定位'
                    cmd = self._make_cmd('ESC D', '設定水平定位', params, raw)
                    commands.append(cmd)
                    self._log_cmd(cmd)
                    self.state = ParserState.IDLE
                    return True
                else:
                    self._var_collected.append(b)
            return False

        # --- GS V 切紙 ---
        if phase == 'gs_v_mode':
            if not self.buffer:
                return False
            m = self.buffer.pop(0)
            self._pending_raw_start.append(m)
            mode_desc = CUT_MODE.get(m, f'模式 {m}')
            if m in (65, 66):  # 需要額外一個參數 n
                self._var_phase = 'gs_v_extra'
                self._var_mode_desc = mode_desc
                return True
            else:
                raw = bytes(self._pending_raw_start)
                cmd = self._make_cmd('GS V', '選擇切紙模式', mode_desc, raw)
                commands.append(cmd)
                self._log_cmd(cmd)
                self.state = ParserState.IDLE
                return True

        if phase == 'gs_v_extra':
            if not self.buffer:
                return False
            n = self.buffer.pop(0)
            self._pending_raw_start.append(n)
            raw = bytes(self._pending_raw_start)
            params = f'{self._var_mode_desc}, 進紙 n={n}'
            cmd = self._make_cmd('GS V', '選擇切紙模式', params, raw)
            commands.append(cmd)
            self._log_cmd(cmd)
            self.state = ParserState.IDLE
            return True

        # --- GS v 0 點陣圖 ---
        if phase == 'gs_v0_header':
            if len(self.buffer) < 5:
                return False
            m = self.buffer.pop(0)
            xL = self.buffer.pop(0)
            xH = self.buffer.pop(0)
            yL = self.buffer.pop(0)
            yH = self.buffer.pop(0)
            self._pending_raw_start.extend([m, xL, xH, yL, yH])
            x = xL + xH * 256
            y = yL + yH * 256
            data_len = x * y
            self._var_data_len = data_len
            self._var_x = x
            self._var_y = y
            self._var_mode = m
            self._var_phase = 'gs_v0_data'
            return True

        if phase == 'gs_v0_data':
            if len(self.buffer) < self._var_data_len:
                return False
            data = bytes(self.buffer[:self._var_data_len])
            del self.buffer[:self._var_data_len]
            self._pending_raw_start.extend(data)
            raw = bytes(self._pending_raw_start)
            params = f'm={self._var_mode}, 寬={self._var_x*8} 點, 高={self._var_y} 點, 資料={len(data)} bytes'
            cmd = self._make_cmd('GS v 0', '列印光柵點陣圖', params, raw)
            commands.append(cmd)
            self._log_cmd(cmd)
            self.state = ParserState.IDLE
            return True

        # --- GS ( L 擴充圖形功能 ---
        if phase == 'gs_paren_l_header':
            if len(self.buffer) < 2:
                return False
            pL = self.buffer.pop(0)
            pH = self.buffer.pop(0)
            self._pending_raw_start.extend([pL, pH])
            data_len = pL + pH * 256
            self._var_data_len = data_len
            self._var_phase = 'gs_paren_l_data'
            return True

        if phase == 'gs_paren_l_data':
            if len(self.buffer) < self._var_data_len:
                return False
            data = bytes(self.buffer[:self._var_data_len])
            del self.buffer[:self._var_data_len]
            self._pending_raw_start.extend(data)
            raw = bytes(self._pending_raw_start)
            params = f'資料={len(data)} bytes'
            cmd = self._make_cmd('GS ( L', '擴充圖形功能', params, raw)
            commands.append(cmd)
            self._log_cmd(cmd)
            self.state = ParserState.IDLE
            return True

        # --- GS ( 其他 ---
        if phase == 'gs_paren_generic_header':
            if len(self.buffer) < 2:
                return False
            pL = self.buffer.pop(0)
            pH = self.buffer.pop(0)
            self._pending_raw_start.extend([pL, pH])
            data_len = pL + pH * 256
            self._var_data_len = data_len
            self._var_phase = 'gs_paren_generic_data'
            return True

        if phase == 'gs_paren_generic_data':
            if len(self.buffer) < self._var_data_len:
                return False
            data = bytes(self.buffer[:self._var_data_len])
            del self.buffer[:self._var_data_len]
            self._pending_raw_start.extend(data)
            raw = bytes(self._pending_raw_start)
            params = f'資料={len(data)} bytes'
            cmd = self._make_cmd(self._pending_mnemonic, self._pending_name, params, raw)
            commands.append(cmd)
            self._log_cmd(cmd)
            self.state = ParserState.IDLE
            return True

        # --- GS k 條碼 ---
        if phase == 'gs_k_type':
            if not self.buffer:
                return False
            m = self.buffer.pop(0)
            self._pending_raw_start.append(m)
            if m <= 6:
                # Format A：NUL 結尾
                self._var_phase = 'gs_k_format_a'
                self._var_barcode_type = m
                self._var_collected = bytearray()
                return True
            else:
                # Format B：下一 byte 為長度
                self._var_phase = 'gs_k_format_b_len'
                self._var_barcode_type = m
                return True

        if phase == 'gs_k_format_a':
            while self.buffer:
                b = self.buffer.pop(0)
                self._pending_raw_start.append(b)
                if b == 0x00:
                    raw = bytes(self._pending_raw_start)
                    barcode_data = self._var_collected.decode('ascii', errors='replace')
                    params = f'類型={self._var_barcode_type}, 資料="{barcode_data}"'
                    cmd = self._make_cmd('GS k', '列印條碼', params, raw)
                    commands.append(cmd)
                    self._log_cmd(cmd)
                    self.state = ParserState.IDLE
                    return True
                else:
                    self._var_collected.append(b)
            return False

        if phase == 'gs_k_format_b_len':
            if not self.buffer:
                return False
            n = self.buffer.pop(0)
            self._pending_raw_start.append(n)
            self._var_data_len = n
            self._var_phase = 'gs_k_format_b_data'
            return True

        if phase == 'gs_k_format_b_data':
            if len(self.buffer) < self._var_data_len:
                return False
            data = bytes(self.buffer[:self._var_data_len])
            del self.buffer[:self._var_data_len]
            self._pending_raw_start.extend(data)
            raw = bytes(self._pending_raw_start)
            barcode_data = data.decode('ascii', errors='replace')
            params = f'類型={self._var_barcode_type}, 資料="{barcode_data}"'
            cmd = self._make_cmd('GS k', '列印條碼', params, raw)
            commands.append(cmd)
            self._log_cmd(cmd)
            self.state = ParserState.IDLE
            return True

        # 未知變長狀態，重置
        self.state = ParserState.IDLE
        return True

    # --- 文字資料 ---

    def _parse_text(self, commands) -> bool:
        """收集連續非指令位元組作為文字"""
        text_bytes = bytearray()
        while self.buffer:
            b = self.buffer[0]
            # 遇到指令前綴或控制字元就停
            if b in (0x1B, 0x1D, 0x10, 0x1C) or b in CONTROL_CHARS:
                break
            text_bytes.append(self.buffer.pop(0))

        if not text_bytes:
            return False

        raw = bytes(text_bytes)
        # 嘗試解碼文字：GBK → UTF-8 → Latin-1
        text = self._decode_text(raw)
        cmd = self._make_cmd('TEXT', '', f'"{text}"', raw)
        commands.append(cmd)
        self._log_cmd(cmd)
        return True

    @staticmethod
    def _decode_text(data: bytes) -> str:
        """嘗試以多種編碼解碼文字"""
        for encoding in ('gb18030', 'utf-8', 'latin-1'):
            try:
                return data.decode(encoding)
            except (UnicodeDecodeError, ValueError):
                continue
        return data.hex()

    # --- 參數描述 ---

    def _describe_params(self, mnemonic: str, params: bytes) -> str:
        """根據指令類型產生參數的人類可讀描述"""
        if not params:
            return ''

        if mnemonic == 'ESC !':
            n = params[0]
            return f'n=0x{n:02X} ({describe_print_mode(n)})'

        if mnemonic == 'ESC a':
            n = params[0]
            return f'n={n} ({ALIGNMENT.get(n, f"未知 {n}")})'

        if mnemonic == 'ESC d':
            return f'n={params[0]} 行'

        if mnemonic == 'ESC E':
            return f'{"啟用" if params[0] & 1 else "停用"}'

        if mnemonic == 'ESC J':
            return f'n={params[0]} 點'

        if mnemonic == 'ESC 3':
            return f'n={params[0]} 點'

        if mnemonic == 'ESC -':
            modes = {0: '停用', 1: '一點底線', 2: '二點底線'}
            return modes.get(params[0], f'n={params[0]}')

        if mnemonic == 'ESC M':
            fonts = {0: 'Font A', 1: 'Font B', 48: 'Font A', 49: 'Font B'}
            return fonts.get(params[0], f'n={params[0]}')

        if mnemonic == 'ESC $':
            nL, nH = params[0], params[1]
            pos = nL + nH * 256
            return f'位置={pos}'

        if mnemonic == 'ESC t':
            return f'碼頁={params[0]}'

        if mnemonic == 'ESC R':
            countries = {
                0: '美國', 1: '法國', 2: '德國', 3: '英國', 4: '丹麥I',
                5: '瑞典', 6: '義大利', 7: '西班牙I', 8: '日本',
                9: '挪威', 10: '丹麥II', 11: '西班牙II', 12: '拉丁美洲',
                13: '韓國', 15: '中國',
            }
            return countries.get(params[0], f'n={params[0]}')

        if mnemonic == 'ESC v':
            return ''

        if mnemonic == 'ESC p':
            return f'm={params[0]}, t1={params[1]}'

        if mnemonic == 'DLE EOT':
            n = params[0]
            desc = {1: '印表機狀態', 2: '離線狀態', 3: '錯誤狀態', 4: '紙張感測器狀態'}
            return f'n={n} ({desc.get(n, f"未知 {n}")})'

        if mnemonic == 'DLE DC4':
            return f'fn={params[0]}, m={params[1]}, t={params[2]}'

        if mnemonic == 'DLE ENQ':
            return f'n={params[0]}'

        if mnemonic == 'GS !':
            n = params[0]
            w = (n >> 4) + 1
            h = (n & 0x0F) + 1
            return f'n=0x{n:02X} (寬{w}倍, 高{h}倍)'

        if mnemonic == 'GS B':
            return f'{"啟用" if params[0] & 1 else "停用"}'

        if mnemonic == 'GS H':
            pos = {0: '不列印', 1: '上方', 2: '下方', 3: '上下皆列印'}
            return pos.get(params[0], f'n={params[0]}')

        if mnemonic == 'GS h':
            return f'高度={params[0]} 點'

        if mnemonic == 'GS w':
            return f'寬度={params[0]}'

        if mnemonic == 'GS f':
            fonts = {0: 'Font A', 1: 'Font B', 48: 'Font A', 49: 'Font B'}
            return fonts.get(params[0], f'n={params[0]}')

        if mnemonic == 'GS a':
            return f'n=0x{params[0]:02X}'

        if mnemonic == 'GS L':
            nL, nH = params[0], params[1]
            return f'左邊界={nL + nH * 256}'

        if mnemonic == 'GS W':
            nL, nH = params[0], params[1]
            return f'寬度={nL + nH * 256}'

        if mnemonic == 'GS r':
            desc = {1: '紙張感測器', 2: '錢箱狀態'}
            return f'n={params[0]} ({desc.get(params[0], f"未知 {params[0]}")})'

        if mnemonic == 'GS I':
            desc = {1: '印表機型號', 2: '印表機類型', 3: '韌體版本'}
            return f'n={params[0]} ({desc.get(params[0], f"未知 {params[0]}")})'

        if mnemonic == 'FS !':
            return f'n=0x{params[0]:02X}'

        if mnemonic == 'FS -':
            return f'{"啟用" if params[0] & 1 else "停用"}'

        if mnemonic == 'FS p':
            return f'n={params[0]}, m={params[1]}'

        if mnemonic == 'ESC V':
            return f'n={params[0]}'

        if mnemonic == 'ESC r':
            return f'n={params[0]}'

        if mnemonic == 'ESC B':
            return f'{"啟用" if params[0] & 1 else "停用"}'

        if mnemonic == 'ESC G':
            return f'{"啟用" if params[0] & 1 else "停用"}'

        if mnemonic == 'ESC {':
            return f'{"啟用" if params[0] & 1 else "停用"}'

        if mnemonic == 'ESC c':
            return f'n={params[0]}'

        # 預設：直接顯示 hex
        return hex_dump(params)

    # --- 智慧回覆 ---

    def _generate_response(self, mnemonic: str, raw: bytes,
                           commands: list, responses: list) -> Optional[bytes]:
        """
        根據指令產生回覆資料

        Returns:
            需回傳的 bytes，或 None（不需回覆）
        """
        # DLE EOT — 即時狀態查詢
        if mnemonic == 'DLE EOT' and len(raw) >= 3:
            n = raw[2]
            if n == 1:
                # 印表機狀態：在線、無錯誤
                resp = bytes([0x16])
                self._log_response(resp, '在線、無錯誤')
                return resp
            elif n == 2:
                # 離線狀態正常
                resp = bytes([0x12])
                self._log_response(resp, '離線狀態正常')
                return resp
            elif n == 3:
                # 無錯誤
                resp = bytes([0x12])
                self._log_response(resp, '無錯誤')
                return resp
            elif n == 4:
                # 紙張充足
                resp = bytes([0x12])
                self._log_response(resp, '紙張充足')
                return resp

        # GS I — 印表機 ID
        if mnemonic == 'GS I' and len(raw) >= 3:
            n = raw[2]
            if n == 1:
                resp = b'BT-B36'
                self._log_response(resp, '印表機型號')
                return resp
            elif n == 2:
                resp = bytes([0x02])
                self._log_response(resp, '印表機類型')
                return resp
            elif n == 3:
                resp = b'0.1.3'
                self._log_response(resp, '韌體版本')
                return resp

        # GS r — 狀態查詢
        if mnemonic == 'GS r' and len(raw) >= 3:
            n = raw[2]
            if n == 1:
                resp = bytes([0x00])
                self._log_response(resp, '紙張狀態正常')
                return resp
            elif n == 2:
                resp = bytes([0x00])
                self._log_response(resp, '錢箱狀態')
                return resp

        # GS a — ASB 設定
        if mnemonic == 'GS a' and len(raw) >= 3:
            self.asb_enabled = raw[2]
            self.logger.info('RSP  ASB 設定更新: n=0x%02X', self.asb_enabled)
            return None  # 不直接回覆

        # ESC v — 紙張感測器狀態
        if mnemonic == 'ESC v':
            resp = bytes([0x00])
            self._log_response(resp, '紙張感測器正常')
            return resp

        return None

    # --- Log 輸出 ---

    def _make_cmd(self, mnemonic: str, name: str, params: str, raw: bytes) -> ESCPOSCommand:
        ts = datetime.now().strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]
        return ESCPOSCommand(
            timestamp=ts,
            mnemonic=mnemonic,
            name=name,
            params=params,
            raw=raw,
        )

    def _log_cmd(self, cmd: ESCPOSCommand):
        """格式化並記錄一條指令"""
        if cmd.mnemonic == 'TEXT':
            # 文字特殊格式
            raw_hex = hex_dump(cmd.raw)
            # 限制 raw hex 顯示長度
            if len(cmd.raw) > 32:
                raw_hex = hex_dump(cmd.raw[:32]) + '...'
            self.logger.info(
                'CMD  %-12s %-20s %-30s | %s',
                cmd.mnemonic, cmd.name, cmd.params, raw_hex
            )
        else:
            raw_hex = hex_dump(cmd.raw)
            if len(cmd.raw) > 32:
                raw_hex = hex_dump(cmd.raw[:32]) + '...'
            param_str = f'    {cmd.params}' if cmd.params else ''
            self.logger.info(
                'CMD  %-12s %-20s%s | %s',
                cmd.mnemonic, cmd.name, param_str, raw_hex
            )

    def _log_response(self, data: bytes, description: str):
        """記錄回覆"""
        self.logger.info(
            'RSP  → 回覆狀態   %s (%s) | %s',
            f'0x{data[0]:02X}' if len(data) == 1 else data.hex(),
            description,
            hex_dump(data),
        )
