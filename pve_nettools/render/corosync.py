# [CHANGE] 2026-08-02 新增：叢集網路 corosync 輸出區段（選單第 14 項，待辦 #16）。
"""corosync 環網設定與即時狀態。

規格真值＝bash `render_corosync`（`old/pve-network-audit.sh:1784-1827`）。
"""

from ..collect import FAILURE_NOT_EXECUTABLE, STATUS_OK, STATUS_UNAVAILABLE
from ..i18n import t
from ..width import pad
from .base import Section, blank, note, subsection

__all__ = ["CorosyncSection"]

# bash：printf "  節點 %-16s nodeid=%-4s ring0=%-20s ring1=%s\n"
NODE_NAME_WIDTH = 16
NODE_ID_WIDTH = 4
RING0_WIDTH = 20


class CorosyncSection(Section):
    """叢集網路（corosync）。"""

    def __init__(self, cluster_reader):
        self.cluster = cluster_reader

    def build(self):
        conf = self.cluster.read()
        if conf["status"] != STATUS_OK:
            return {"conf": conf, "cfgtool": None, "pvecm": None}
        # ★ 只有在 corosync.conf 存在時才去跑那兩支指令。bash 的結構也是這樣
        #   （整個函式在找不到設定檔時就 return），而這不只是等價問題：
        #   `pvecm status` 在非叢集主機上會等到 timeout。
        return {"conf": conf,
                "cfgtool": self.cluster.cfgtool_status(),
                "pvecm": self.cluster.pvecm_status()}

    def is_empty(self, data):
        return data["conf"]["status"] != STATUS_OK

    def empty_lines(self, data, ctx):
        return [note(t("corosync.not_found", path=data["conf"]["path"]),
                     ctx.palette)]

    def table(self, data, ctx):
        return None

    def blocks(self, data, ctx):
        parsed = data["conf"]["data"]
        lines = subsection(t("corosync.title"), ctx.palette) + [blank()]

        for entry in parsed["entries"]:
            if entry["kind"] == "node":
                lines.append(self._node_line(entry))
            else:
                lines.append("  %s" % entry["text"])

        lines.append(blank())
        if not parsed["has_ring1"]:
            lines.append(note(t("corosync.single_ring_warn"), ctx.palette))

        lines.extend(self._command_block(
            data["cfgtool"], t("corosync.cfgtool_title"),
            t("corosync.cfgtool_failed"), ctx))
        lines.extend(self._command_block(
            data["pvecm"], t("corosync.pvecm_title"),
            t("corosync.pvecm_failed"), ctx))
        return lines

    @staticmethod
    def _node_line(entry):
        """對齊 bash 的 printf 欄寬。缺值以空字串補（bash 的變數未設定即為空）。"""
        return "  %s %s nodeid=%s ring0=%s ring1=%s" % (
            t("corosync.node"),
            pad(entry["name"] or "", NODE_NAME_WIDTH),
            pad(entry["nodeid"] or "", NODE_ID_WIDTH),
            pad(entry["ring0"] or "", RING0_WIDTH),
            entry["ring1"] or t("corosync.ring1_unset"))

    @staticmethod
    def _command_block(result, title, failed_text, ctx):
        """一支外部指令的輸出區塊。

        ★ 指令**不存在**時整段不印（bash 的 `command_exists`）；存在但失敗時
          印小標題再印一句「無法取得」。兩者合併會讓單機 PVE 的報告憑空多出
          兩段紅字，而那台主機本來就不該有叢集資訊。
        """
        if result is None:
            return []
        if (result["status"] == STATUS_UNAVAILABLE
                and result.get("failure") == FAILURE_NOT_EXECUTABLE):
            return []
        lines = [blank()] + subsection(title, ctx.palette) + [blank()]
        if result["status"] == STATUS_OK:
            lines.extend(result["stdout"].splitlines())
        else:
            lines.append(note(failed_text, ctx.palette))
        return lines
