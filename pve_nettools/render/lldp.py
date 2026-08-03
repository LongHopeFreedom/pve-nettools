# [CHANGE] 2026-08-02 新增：LLDP 交換器鄰居輸出區段（選單第 16 項，待辦 #16）。
"""LLDP 鄰居摘要與完整明細。

規格真值＝bash `render_lldp`（`old/pve-network-audit.sh:1915-1973`）。

★ bash 這一段有三種「沒有資料」，各自要說不同的話：
    沒裝 lldpd            → 給安裝指令
    裝了但服務沒跑        → 給啟動指令，**然後仍繼續往下查**
    有跑但收不到鄰居      → 給三點排查清單
  第二種是唯一「印了提示還繼續」的，MUST NOT 當成終止條件。
"""

from ..collect import STATUS_OK
from ..i18n import t
# [CHANGE] 2026-08-03 九個窄版資料標題統一由 block_title 呈現粗體框線與青色名稱。
from .base import (DecoratedTable, Section, blank, block_title, note,
                   subsection)

__all__ = ["LldpSection"]


class LldpSection(Section):
    """LLDP 交換器與 Port。"""

    HEADERS = ("lldp.local_iface", "lldp.sysname", "lldp.portid",
               "lldp.portdescr")

    def __init__(self, lldp_reader):
        self.lldp = lldp_reader

    def build(self):
        if not self.lldp.installed():
            return {"reason": "not_installed", "active": False,
                    "rows": [], "raw": None}
        active = self.lldp.service_active()
        result = self.lldp.neighbors()
        rows = result["data"] if result["status"] == STATUS_OK else []
        # ★ `parsed_result` 在 empty 分支回的是 {} 而不是 []（它的形狀是為
        #   dict 解析器寫的）。這裡的解析器回 list，故 MUST 自己收斂型別，
        #   否則下游對 {} 做迭代會拿到 key 而不是紀錄。
        if not isinstance(rows, list):
            rows = []
        return {"reason": None if rows else "no_neighbors", "active": active,
                "rows": rows, "raw": self.lldp.raw()}

    def is_empty(self, data):
        return not data["rows"]

    def empty_lines(self, data, ctx):
        if data["reason"] == "not_installed":
            return [
                note(t("lldp.not_installed"), ctx.palette), blank(),
                t("lldp.install_title"),
                "  apt update",
                "  apt install -y lldpd",
                "  systemctl enable --now lldpd",
                blank(),
                t("lldp.install_hint"),
            ]
        lines = self._inactive_lines(data, ctx)
        lines.extend([
            note(t("lldp.none"), ctx.palette), blank(),
            t("lldp.check_title"), t("lldp.check1"), t("lldp.check2"),
            t("lldp.check3"),
        ])
        return lines

    @staticmethod
    def _inactive_lines(data, ctx):
        """服務沒跑時的提示。★ 印完**繼續**，不是 return。"""
        if data["active"]:
            return []
        return [note(t("lldp.inactive"), ctx.palette),
                t("lldp.inactive_hint"), blank()]

    def table(self, data, ctx):
        leading = (self._inactive_lines(data, ctx)
                   + subsection(t("lldp.summary_title"), ctx.palette) + [blank()])
        trailing = ([blank()] + subsection(t("lldp.details_title"), ctx.palette)
                    + [blank()] + (data["raw"] or "").splitlines())
        table = DecoratedTable([t(key) for key in self.HEADERS],
                               leading=leading, trailing=trailing)
        for row in data["rows"]:
            table.add([row["iface"],
                       row["sysname"] or "-",
                       row["portid"] or "-",
                       row["portdescr"] or "-"])
        return table

    def blocks(self, data, ctx):
        lines = self._inactive_lines(data, ctx)
        lines.extend(subsection(t("lldp.summary_title"), ctx.palette) + [blank()])
        headers = [t(key) for key in self.HEADERS]
        for row in data["rows"]:
            lines.append(block_title(row["iface"], ctx.palette))
            for key, header in zip(("sysname", "portid", "portdescr"),
                                   headers[1:]):
                lines.append("%s%s%s" % (header, t("app.kv_sep"),
                                         row[key] or "-"))
            lines.append(blank())
        lines.extend(subsection(t("lldp.details_title"), ctx.palette) + [blank()])
        lines.extend((data["raw"] or "").splitlines())
        return lines
