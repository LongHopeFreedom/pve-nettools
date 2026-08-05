# [CHANGE] 2026-08-04 待辦 #13：網卡 ring buffer 與 offload 功能區段。
"""逐張實體網卡顯示 ring buffer 與 ethtool offload features。"""

from ..collect import STATUS_OK
from ..i18n import t
from ..width import disp_width, pad
from .base import Section, block_title, error, kv, note

__all__ = ["DISPLAYED_FEATURES", "RingOffloadSection"]

# [CHANGE] 2026-08-04 真機回報後改設計（enp6s0 實測 63 項）。
#
# 這份清單原本是**封閉集合**：只顯示這十項，其餘一律不印，只印一行「未顯示 N 項」。
# 真機上那一行是「共 63 項，此處顯示 10 項，未顯示 53 項」——**84% 的資料被藏起來，
# 而且沒有任何出口**。使用者當場問「其他的不顯示嗎？可以換頁嗎？」
#
# ★★ 我當初的理由是「怕洗版」，而那個限制**不存在**：互動輸出本來就走 less
#   （畫面下方那行就是它），螢幕空間從來不是限制。用一個不存在的限制換掉 84%
#   的資料，對一支**盤查**工具而言是反向的。
# ★ 現行設計：這十項仍逐行對齊顯示（它們是 PVE 網路調校最常查的），
#   其餘的**全部顯示**，以多欄壓縮排在後面。零隱藏。
#   這與專案既有的直覺一致——VLAN 清單是把 4089 行壓成 `2-4090t`，
#   **壓縮而不是隱藏**。
DISPLAYED_FEATURES = (
    "rx-checksumming",
    "tx-checksumming",
    "scatter-gather",
    "tcp-segmentation-offload",
    "generic-segmentation-offload",
    "generic-receive-offload",
    "large-receive-offload",
    "rx-vlan-offload",
    "tx-vlan-offload",
    "rx-vlan-filter",
)

FEATURE_KEY_WIDTH = 32

# 其餘項目的多欄排列。
# ★ 上限存在的理由：報告模式的 ctx.width 是 REPORT_WIDTH（9999，代表「不要折行」），
#   直接拿它算欄數會把 53 項排成**一行**。這個上限與專案「寬表格需要約 132 欄」
#   的說法對齊。
GRID_MAX_WIDTH = 132
GRID_GAP = 2


# [CHANGE] 2026-08-04 待辦 #13：這裡原本有一個 _unavailable()，是 build() 那個
#   getattr fail-open 的搭檔。fail-open 移除之後它沒有任何呼叫端，一併移除——
#   留著會讓下一個人以為「reader 缺方法」是一個被支援的情境。
def _cell_value(item):
    """一格的值；fixed 的標示沿用上方逐行區塊，不另造一套。"""
    value = (item or {}).get("value") or t("app.na")
    if (item or {}).get("fixed"):
        value = t("ringoffload.fixed", value=value)
    return value


def _grid(pairs, width):
    """把 (名稱, 值) 排成等寬多欄。offload 的其餘項與 ring 的其餘欄位共用。

    ★ 欄寬取**最長的那一格**：不截斷。被切一半的名稱讀起來像另一個名稱，
      與 width.pad() 不截斷是同一條理由。
    ★ 可用寬度取 min(ctx.width, GRID_MAX_WIDTH)——報告模式的 ctx.width 是 9999，
      不設上限會把所有項目排成一行。
    """
    if not pairs:
        return []
    # 名稱在格內補到共同寬度，讓值也對齊——不補的話，名稱長短不一時
    # 值會散在各處，多欄反而比逐行難掃。
    name_width = max(disp_width(name) for name, _ in pairs) + 1
    cells = ["%s%s" % (pad(name, name_width), value) for name, value in pairs]
    cell_width = max(disp_width(cell) for cell in cells) + GRID_GAP
    usable = min(width, GRID_MAX_WIDTH)
    per_row = max(1, usable // cell_width)
    lines = []
    for start in range(0, len(cells), per_row):
        row = cells[start:start + per_row]
        # 最後一格不補尾隨空白：行尾空白在 diff 與貼上時都是雜訊。
        padded = [pad(cell, cell_width) for cell in row[:-1]] + [row[-1]]
        lines.append("".join(padded))
    return lines


def _pair(current, maximum):
    current_text = t("app.na") if current is None else str(current)
    maximum_text = t("app.na") if maximum is None else str(maximum)
    return t("ringoffload.ring_pair", current=current_text,
             maximum=maximum_text)


class RingOffloadSection(Section):
    """每張實體網卡的 ring 與 offload；兩道查詢各自保留狀態。"""

    def __init__(self, sysfs, ethtool):
        self.sysfs = sysfs
        self.ethtool = ethtool

    # [CHANGE] 2026-08-04 待辦 #13：原本這裡有一個 title()，回傳本模組專屬的標題 key。
    #   它**產品碼零呼叫端**——區段標題由 app.MENU_ENTRIES 的 title_key 提供，
    #   而那兩個 key 的值在 en 與 zh-TW **逐字相同**。同一句話兩份真值、沒有任何
    #   東西在對帳 ⇒ 方法與那兩個 key 已一併移除。
    #   （由孤兒方法掃描抓到：它是本棒唯一新增的零呼叫端公開方法。）
    #   ★ 此處刻意不寫出被移除的 key 名：i18n 的「未被引用 key」掃描是掃原始碼字串，
    #     註解裡逐字抄一次，那個 key 就會被讀成「有人在用」。

    def build(self):
        # [CHANGE] 2026-08-04 待辦 #13：原本以 getattr(..., None) 取這兩個方法，
        #          reader 少了方法就整段降級成「取不到」。那是 **fail-open**：
        #          把 ring() 打錯成 rings()、或哪天有人刪掉它，畫面上只會顯示
        #          「取不到」——與「這張卡真的問不到」**完全同形**，而且全綠。
        #          降級的唯一存在理由是遷就一個還沒補上方法的舊 fixture，
        #          正解是把 fixture 補齊（已補 tests/test_render_nic.py 的
        #          FakeEthtool），不是讓產品碼替測試留後門。
        rows = []
        for iface in self.sysfs.physical_nics():
            rows.append({
                "iface": iface,
                "ring": self.ethtool.ring(iface),
                "offload": self.ethtool.offload(iface),
            })
        return rows

    def table(self, data, ctx):
        return None

    def blocks(self, data, ctx):
        lines = []
        for row in data:
            lines.append(block_title(row["iface"], ctx.palette))
            lines.extend(self._ring_lines(row["ring"], ctx))
            lines.extend(self._offload_lines(row["offload"], ctx))
            lines.append("")
        return lines

    def _ring_lines(self, result, ctx):
        if result.get("status") != STATUS_OK:
            return [kv(t("ringoffload.ring"),
                       t("ringoffload.ring_unavailable"))]

        data = result.get("data") or {}
        rx = _pair(data.get("rx_current"), data.get("rx_max"))
        tx = _pair(data.get("tx_current"), data.get("tx_max"))
        lines = [kv(t("ringoffload.ring"),
                    t("ringoffload.ring_summary", rx=rx, tx=tx))]
        for stem, key in (("rx_mini", "ringoffload.ring_mini"),
                          ("rx_jumbo", "ringoffload.ring_jumbo")):
            current = data.get(stem + "_current")
            maximum = data.get(stem + "_max")
            if current is not None or maximum is not None:
                lines.append(kv(t(key), _pair(current, maximum)))
        # [CHANGE] 2026-08-04 真機回報後新增：`ethtool -g` 的其餘欄位。
        #   實測 r8169 另有 6 個（TX Push／RX Push／RX Buf Len／CQE Size／
        #   TCP data split／TX push buff len），其中前兩個是真值不是 n/a。
        #   ★ 這些欄位**不成對**（多半只出現在 Current 段），所以不套 current／max
        #     的配對版面，直接以名稱與值列出。
        extra = data.get("extra") or {}
        if extra:
            lines.append(t("ringoffload.ring_extra", count=len(extra)))
            lines.extend(_grid(
                [(name, t("app.na") if value is None else str(value))
                 for name, value in extra.items()], ctx.width))
        return lines

    def _offload_lines(self, result, ctx):
        if result.get("status") != STATUS_OK:
            return [kv(t("ringoffload.offload"),
                       t("ringoffload.offload_unavailable"))]

        data = result.get("data") or {}
        features = data.get("features") or {}
        lines = [t("ringoffload.offload")]
        for feature in DISPLAYED_FEATURES:
            item = features.get(feature)
            if item is None:
                value = t("app.na")
            else:
                value = item.get("value") or t("app.na")
                if item.get("fixed"):
                    value = t("ringoffload.fixed", value=value)
            lines.append(kv(feature, value, key_width=FEATURE_KEY_WIDTH))

        # [CHANGE] 2026-08-04 真機回報後改設計：其餘項目**全部顯示**，不再只印一行
        #   「未顯示 N 項」。原本的 more 訊息已從 i18n 移除——留著它會是一句假話。
        # ★ 順序沿用驅動輸出的順序（order），不排序：ethtool 把子項印在父項旁邊，
        #   那個分組比字母序好查。要找特定一項用 less 的 `/關鍵字`。
        rest = []
        seen = set()
        for name in data.get("order") or []:
            if name in DISPLAYED_FEATURES or name in seen:
                continue
            seen.add(name)
            rest.append(name)
        if rest:
            lines.append("")
            lines.append(t("ringoffload.rest", count=len(rest),
                           total=len(features)))
            lines.extend(_grid([(name, _cell_value(features.get(name)))
                                for name in rest], ctx.width))

        lro = features.get("large-receive-offload")
        if lro is not None and lro.get("value") == "on":
            lines.append(note(t("ringoffload.lro_note"), ctx.palette))
        return lines

    def empty_lines(self, data, ctx):
        return [error(t("nic.none_found"), ctx.palette)]
