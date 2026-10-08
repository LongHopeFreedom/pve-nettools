# [CHANGE] 2026-08-01 新增：VM/CT 網卡對應輸出區段。
"""PVE guest 設定網卡與 host-side 介面的對應輸出。"""

from ..collect.pve import KIND_CT
from ..i18n import t
# [CHANGE] 2026-08-03 窄版標題改走共用 helper，並讓新增的 guest colorizer 同時
#          供表格與區塊版使用，避免兩種版面對狀態／VLAN 各自判色。
from .base import Section, block_title, kv, note, subsection
from .nic import _TrailingTable

__all__ = ["GuestSection"]


def _value(value):
    return t("app.na") if value is None else str(value)


class GuestSection(Section):
    # [CHANGE] 2026-08-02：欄位與順序回到與 bash 版逐欄等價的 11 欄。
    #
    # 補回 guest.mac／guest.mtu：bash 版的表格版與逐張區塊版**都有**這兩欄，
    #    Python 版卻連 i18n key 都不存在（grep 零命中）——這是實質的功能倒退，
    #    而 bash 版正要靠「Python 版驗證通過」來除役。資料一直都在
    #    （collect/pve.py:121,124 早就解析了 mac 與 mtu），只是沒有人呈現它。
    # 移除 guest.linkdown／guest.model／guest.rate：三者在 bash 版**完全不存在**
    #    （全檔 grep 零命中）。bash 解析 `virtio=XX:XX:…` 這種形態時是把值當作
    #    **MAC**，model 名稱只是 key、從不顯示。
    # 順序刻意逐欄對齊 bash 的 render_guest_nics_table：
    #    VMID／類型／名稱／網卡／介面／MAC／Bridge／VLAN Tag／MTU／防火牆／介面狀態。
    HEADERS = (
        "guest.vmid", "guest.kind", "guest.name", "guest.netid", "guest.iface",
        "guest.mac", "guest.bridge", "guest.tag", "guest.mtu",
        "guest.firewall", "guest.state",
    )
    # [CHANGE] 2026-08-03 由 HEADERS 推導欄位位置，避免欄序調整後硬編碼索引失準。
    TAG_COLUMN = HEADERS.index("guest.tag")       # VLAN Tag header
    STATE_COLUMN = HEADERS.index("guest.state")  # State header

    # [CHANGE] 2026-10-08 v03.021.000：zoned=True 時分成「VM 區」「LXC 區」兩張表。
    # 預設 False ＝ 與舊版逐位元相同；完整報告走預設（已決定這一版報告輸出不動），
    #   只有互動選單的工廠傳 True。
    # 區的歸屬取自設定檔來源（collect/pve.py 的 SOURCES → row["kind"]），不由介面名稱猜。
    def __init__(self, guest_reader, sysfs_reader, zoned=False):
        self.guest = guest_reader
        self.sysfs = sysfs_reader
        self.zoned = zoned

    def build(self):
        return self.build_from(self.guest.nics())

    # [CHANGE] 2026-10-08 v03.022.000：由 build() 拆出，讓選單 6（Linux Bridge）把同一份
    #          guest.nics() 結果丟進來，不必另寫一份列的建構、也不必讀兩次設定檔。
    def build_from(self, result):
        rows = []
        for nic in result.get("nics") or []:
            running = self.sysfs.exists(nic.get("iface"))
            rows.append({
                "cells": [
                    str(nic.get("vmid")), _value(nic.get("kind")),
                    _value(nic.get("name")), _value(nic.get("netid")),
                    _value(nic.get("iface")), _value(nic.get("mac")),
                    _value(nic.get("bridge")), _value(nic.get("tag")),
                    _value(nic.get("mtu")),
                    t("app.yes") if nic.get("firewall") else t("app.no"),
                    t("guest.running") if running else t("guest.stopped"),
                ],
                "running": running,
                "has_tag": nic.get("tag") is not None,
                "kind": nic.get("kind"),
                # [CHANGE] 2026-10-08 v03.022.000：原始橋接名（None＝設定檔沒寫）。選單 6 依它
                #          歸戶；不從 cells 取，因為 cells 裡沒寫橋接會顯示成 N/A，與一座叫 N/A 的橋同形。
                "bridge": nic.get("bridge"),
            })
        return {"rows": rows, "unreadable": result.get("unreadable") or []}

    def is_empty(self, data):
        return not data["rows"]

    def _notes(self, data, ctx):
        unreadable = len(data["unreadable"])
        if not unreadable:
            return []
        # 規格未提供專用句型；依指定以 app.not_found 加上數量，避免靜默漏報。
        # [CHANGE] 2026-08-02 分隔符改走 i18n（見 i18n.py 的 app.kv_sep）。
        return [note("%s%s%d" % (t("app.not_found"), t("app.kv_sep"), unreadable),
                     ctx.palette)]

    def table(self, data, ctx):
        table = _TrailingTable([t(key) for key in self.HEADERS], self._notes(data, ctx))
        for row in data["rows"]:
            table.add(row["cells"])
        return table

    def blocks(self, data, ctx):
        return self._block_lines(data, ctx) + self._notes(data, ctx)

    def _block_lines(self, data, ctx):
        lines = []
        paint = self.colorizer(data, ctx)
        for row_index, row in enumerate(data["rows"]):
            cells = row["cells"]
            lines.append(block_title("%s / %s" % (cells[0], cells[3]),
                                     ctx.palette))
            for col_index, (key, value) in enumerate(
                    zip(self.HEADERS[1:], cells[1:]), start=1):
                lines.append(kv(t(key), paint(row_index, col_index, value),
                                key_width=8))
            lines.append("")
        return lines

    # [CHANGE] 2026-08-02：原本對第 8 欄（linkdown）在斷線時上黃色。
    # 那一欄本身是 Python 版多出來的（bash 全檔無 link_down），欄位既已移除，
    # 著色也一併移除，改用基底的預設（不著色）。
    # [CHANGE] 2026-08-03 上一行的「註明未做」**已完成**，敘述一併更新——留著一句
    #   已經不成立的自述，與 README 照抄 bash 自檢涵蓋範圍是同一種病：文件說謊。
    #   併記判準變更（2026-08-03 決定）：著色與措辭改由 Python 自主，
    #     bash 只是**功能**參考、不再是**文字**真值，故此處不再以 bash 逐欄對照。

    # [CHANGE] 2026-08-03 補上 Python render 自有的 guest 顏色判準：狀態依 host-side
    #          介面存在性分綠／黃，實際存在的 VLAN Tag 才上青色。
    def colorizer(self, data, ctx):
        def paint(row_index, col_index, text):
            row = data["rows"][row_index]
            if col_index == self.STATE_COLUMN:
                return ctx.paint(text, "green" if row["running"] else "yellow")
            if col_index == self.TAG_COLUMN and row["has_tag"]:
                return ctx.paint(text, "cyan")
            return text
        return paint

    # [CHANGE] 2026-08-01 基底的 empty_lines 改收 data，不再需要 instance 屬性。
    def empty_lines(self, data, ctx):
        return [note(t("guest.none"), ctx.palette)] + self._notes(data, ctx)

    # [CHANGE] 2026-10-08 v03.021.000：VM／LXC 分區輸出。
    def render(self, ctx):
        if not self.zoned:
            return Section.render(self, ctx)
        data = self.build()
        if self.is_empty(data):
            return self.empty_lines(data, ctx)
        lines = []
        for title_key, none_key, rows in self._zones(data):
            if lines:
                lines.append("")
            lines.extend(subsection(t(title_key), ctx.palette))
            if rows:
                lines.extend(self._zone_lines(
                    {"rows": rows, "unreadable": data["unreadable"]}, ctx))
            else:
                lines.append(note(t(none_key), ctx.palette))
        return lines + self._notes(data, ctx)

    @staticmethod
    def _zones(data):
        """(標題鍵, 空區訊息鍵, 列) 兩組；LXC 以外一律歸 VM 區，兩區列數相加恆等於總列數。"""
        lxc = [row for row in data["rows"] if row["kind"] == KIND_CT]
        vm = [row for row in data["rows"] if row["kind"] != KIND_CT]
        return (("guest.zone_vm", "guest.zone_vm_none", vm),
                ("guest.zone_lxc", "guest.zone_lxc_none", lxc))

    def _zone_lines(self, zone_data, ctx):
        table = _TrailingTable([t(key) for key in self.HEADERS], [])
        for row in zone_data["rows"]:
            table.add(row["cells"])
        if ctx.fits(table.total_width()):
            return table.render(self.colorizer(zone_data, ctx))
        # 區塊版每張卡後面都有一行空白；區與區之間的空白由呼叫端加，這裡去掉最後那一行。
        return self._block_lines(zone_data, ctx)[:-1]
