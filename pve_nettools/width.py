"""終端顯示寬度與表格排版。

為什麼獨立成一個模組：欄位對齊在 bash 版是反覆出錯的地方，而它的正確性可以完全
離線驗證，不需要任何系統狀態。

bash 版的做法是「顯示寬度 = 字元數 + (byte 數 - 字元數) / 2」——這個推算對常見的
CJK 全形字（UTF-8 下 3 bytes、顯示 2 欄）剛好成立，但對 emoji（4 bytes）、組合字、
零寬字元都會算錯。改用 unicodedata.east_asian_width 是換 Python 最直接的收益。
"""

import unicodedata

__all__ = ["disp_width", "pad", "pad_left", "truncate", "wrap_csv", "hr", "Table"]


def disp_width(text):
    """字串在等寬終端上佔幾欄。

    East Asian Wide (W) 與 Fullwidth (F) 佔 2 欄；組合字（Mn/Me）與零寬字元佔 0 欄；
    其餘佔 1 欄。控制字元不計入——它們不該出現在要排版的欄位裡，若出現了寬度也無
    意義，計 0 至少不會把整列推歪。
    """
    if not text:
        return 0

    width = 0
    for ch in text:
        if ch in ("​", "﻿"):          # 零寬空格、BOM
            continue
        category = unicodedata.category(ch)
        if category in ("Mn", "Me", "Cf"):       # 組合記號、圍繞記號、格式字元
            continue
        if category == "Cc":                     # 控制字元
            continue
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


def pad(text, width, fill=" "):
    """靠左對齊補到指定顯示寬度。超過寬度時不截斷，原樣返回。

    不截斷是刻意的：欄位撐破只是版面難看，截斷卻會讓資料失真——一個被截掉的
    PCI 位址或 MAC 讀起來像是另一張網卡。要截斷請顯式呼叫 truncate()。
    """
    padding = width - disp_width(text)
    return text + fill * padding if padding > 0 else text


def pad_left(text, width, fill=" "):
    """靠右對齊補到指定顯示寬度（數值欄位用）。"""
    padding = width - disp_width(text)
    return fill * padding + text if padding > 0 else text


def truncate(text, width, ellipsis="…"):
    """截斷到指定顯示寬度，尾端加省略號。寬度不足以容納省略號時直接硬切。"""
    if disp_width(text) <= width:
        return text

    ell_w = disp_width(ellipsis)
    if width <= ell_w:
        out = ""
        for ch in text:
            if disp_width(out + ch) > width:
                break
            out += ch
        return out

    budget = width - ell_w
    out = ""
    for ch in text:
        if disp_width(out + ch) > budget:
            break
        out += ch
    return out + ellipsis


# [CHANGE] 2026-07-31 新增：逗號分隔清單折行（待辦 #3 的 VLAN 清單要用）。
def wrap_csv(text, width):
    """把逗號分隔清單折成多行，每行顯示寬度盡量不超過 width。

    VLAN 清單壓成範圍後仍可能很長——`100t,200t,300t…` 這種不連續的壓不掉。

    ★ 保證的是「盡量」：單一 token 本身就超過 width 時不切斷它，寧可讓那一行撐破，
    理由與 pad() 不截斷相同——被切一半的 VLAN 範圍讀起來像是另一個範圍。逗號留在
    前一行的行尾，所以每行最多會比 width 多一欄。
    """
    if not text:
        return []

    items = text.split(",")
    lines = []
    line = ""
    for index, item in enumerate(items):
        token = item + ("," if index < len(items) - 1 else "")
        if line and disp_width(line) + disp_width(token) > width:
            lines.append(line)
            line = token
        else:
            line += token
    if line:
        lines.append(line)
    return lines


def hr(width, char="="):
    return char * width


class Table:
    """固定欄寬的表格。

    欄寬由「表頭與所有資料的最大顯示寬度」決定，而不是寫死——bash 版把欄寬寫死成
    數字（pad "介面" 14），中英文切換後英文表頭與中文表頭寬度不同，那些數字就全部
    要重算。由資料決定欄寬讓 i18n 不必動排版。
    """

    def __init__(self, headers, min_widths=None, gap=2):
        self.headers = list(headers)
        self.rows = []
        self.gap = gap
        self.min_widths = list(min_widths) if min_widths else [0] * len(self.headers)
        if len(self.min_widths) != len(self.headers):
            raise ValueError("min_widths 長度必須與 headers 相同")

    def add(self, cells):
        if len(cells) != len(self.headers):
            raise ValueError(
                "欄數不符：表頭 %d 欄，此列 %d 欄" % (len(self.headers), len(cells))
            )
        self.rows.append([("" if c is None else str(c)) for c in cells])

    def widths(self):
        """各欄實際採用的寬度。"""
        cols = len(self.headers)
        widths = []
        for i in range(cols):
            candidates = [disp_width(self.headers[i])]
            candidates.extend(disp_width(row[i]) for row in self.rows)
            candidates.append(self.min_widths[i])
            widths.append(max(candidates))
        return widths

    def total_width(self):
        w = self.widths()
        return sum(w) + self.gap * (len(w) - 1) if w else 0

    def render(self, colorizer=None):
        """回傳表格的每一行。

        colorizer(row_index, col_index, text) -> text 可為指定儲存格加上 ANSI 碼。
        著色在補白之後才套用，否則顏色碼的長度會被算進欄寬而把版面推歪——這是
        bash 版特地寫 padc() 的原因，這裡用同樣的順序。
        """
        widths = self.widths()
        gap = " " * self.gap
        out = [gap.join(pad(h, w) for h, w in zip(self.headers, widths)).rstrip()]
        out.append(hr(self.total_width()))

        for r, row in enumerate(self.rows):
            cells = []
            for c, (text, w) in enumerate(zip(row, widths)):
                cell = pad(text, w)
                if colorizer is not None:
                    coloured = colorizer(r, c, text)
                    if coloured != text:
                        # 只換掉文字本體，補白留在外面不著色
                        cell = coloured + " " * max(0, w - disp_width(text))
                cells.append(cell)
            out.append(gap.join(cells).rstrip())
        return out
