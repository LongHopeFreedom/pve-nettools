# [CHANGE] 2026-08-02 待辦 #17：SFP/QSFP 模組明細輸出區段（選單第 3 項）。
"""SFP/QSFP 模組明細的逐張區塊輸出。"""

from ..collect import STATUS_OK
from ..i18n import t
from .base import Section, kv, note
# ★ 複用而非複製：媒介文字的轉換只能有一份實作。兩份複本一旦漂移，不會有任何
#   測試變紅——這是本套件 collect/__init__.py 的 docstring 明文寫過的立場。
from .nic import _medium_text

__all__ = ["ModuleSection"]

# bash render_nic_modules 的欄位順序，對照 `ethtool -m` 的原始欄位名。
# ★ 右邊是**正規化後**的名稱（小寫、連續空白壓成一個），與
#   collect/ethtool.py 的 _normalise_field_name 同一道規則——兩邊若漂移，
#   這裡會全部取不到值而印成一整片 N/A，故測試以真實欄位名的樣本守它。
FIELDS = (
    ("module.vendor", "vendor name"),
    ("module.pn", "vendor pn"),
    ("module.sn", "vendor sn"),
    ("module.connector", "connector"),
    ("module.type", "transceiver type"),
    ("module.cable_tech", "cable technology"),
    ("module.length_copper", "length (copper)"),
    ("module.temperature", "module temperature"),
    ("module.voltage", "module voltage"),
    ("module.tx_power", "laser output power"),
    ("module.rx_power", "receiver signal average optical power"),
)

# bash 的 kv() 是 pad(key, 16)；此處對齊它。
KEY_WIDTH = 16


def _value(value):
    """缺值一律 N/A。

    ★ 與 bash 的**刻意差異**：bash 的 field_value 找不到欄位時回空字串，畫面上
      會是「廠商　　　　：」這樣的空值，看起來像工具壞了。本套件其他區段一律以
      app.na 表示缺值，保持工具內一致比逐字對齊 bash 更重要——使用者是在同一個
      畫面裡上下對照不同區段的。此差異已具名，若要改回空字串請一併調整測試。
    """
    return t("app.na") if value is None or value == "" else str(value)


class ModuleSection(Section):
    """SFP/QSFP 模組明細。

    ★ bash 的 render_nic_modules **沒有表格版**，只有逐張區塊，故 table() 回
      None——Section.render() 會據此直接走 blocks()，不必也不該造一個表格。
    """

    def __init__(self, sysfs_reader, ethtool_reader):
        self.sysfs = sysfs_reader
        self.ethtool = ethtool_reader

    def build(self):
        """只收「真的讀得到 EEPROM」的網卡。

        ★ 讀不到 EEPROM 在純 RJ45 電口網卡上是**正常**的，不是錯誤——bash 對此
          的處理是整段略過該網卡，最後若一張都沒有才印一句說明。這裡照做：
          把「沒有模組」與「有模組但讀不到」都排除在 rows 之外，兩者對使用者
          的意義相同（這張卡沒有可看的模組資訊）。
        """
        rows = []
        for iface in self.sysfs.physical_nics():
            module = self.ethtool.module_eeprom(iface)
            if module.get("status") != STATUS_OK:
                continue
            fields = module.get("data") or {}
            if not fields:
                continue
            rows.append({
                "iface": iface,
                "medium": _medium_text(self.ethtool.medium(iface)),
                "fields": fields,
            })
        return rows

    def table(self, data, ctx):
        return None

    def blocks(self, data, ctx):
        lines = []
        for row in data:
            lines.append("")
            lines.append(ctx.paint(
                t("module.header", nic=row["iface"], medium=row["medium"]),
                "bold"))
            for key, field in FIELDS:
                lines.append(kv(t(key), _value(row["fields"].get(field)),
                                key_width=KEY_WIDTH))
        return lines

    def empty_lines(self, data, ctx):
        return [note(t("module.none"), ctx.palette)]
