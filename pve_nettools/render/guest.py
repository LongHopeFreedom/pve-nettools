# [CHANGE] 2026-08-01 新增：VM/CT 網卡對應輸出區段（待辦 #8）。
"""PVE guest 設定網卡與 host-side 介面的對應輸出。"""

from ..i18n import t
# [CHANGE] 2026-08-03 窄版標題改走共用 helper，並讓新增的 guest colorizer 同時
#          供表格與區塊版使用，避免兩種版面對狀態／VLAN 各自判色。
from .base import Section, block_title, kv, note
from .nic import _TrailingTable

__all__ = ["GuestSection"]


def _value(value):
    return t("app.na") if value is None else str(value)


class GuestSection(Section):
    # [CHANGE] 2026-08-02 待辦 #26：欄位與順序回到與 bash 版逐欄等價的 11 欄。
    #
    # ★★ 補回 guest.mac／guest.mtu：bash 版的表格版與逐張區塊版**都有**這兩欄，
    #    Python 版卻連 i18n key 都不存在（grep 零命中）——這是實質的功能倒退，
    #    而 bash 版正要靠「Python 版驗證通過」來除役。資料一直都在
    #    （collect/pve.py:121,124 早就解析了 mac 與 mtu），只是沒有人呈現它。
    # ★ 移除 guest.linkdown／guest.model／guest.rate：三者在 bash 版**完全不存在**
    #    （全檔 grep 零命中）。bash 解析 `virtio=XX:XX:…` 這種形態時是把值當作
    #    **MAC**，model 名稱只是 key、從不顯示。
    # ★ 順序刻意逐欄對齊 bash 的 render_guest_nics_table：
    #    VMID／類型／名稱／網卡／介面／MAC／Bridge／VLAN Tag／MTU／防火牆／介面狀態。
    HEADERS = (
        "guest.vmid", "guest.kind", "guest.name", "guest.netid", "guest.iface",
        "guest.mac", "guest.bridge", "guest.tag", "guest.mtu",
        "guest.firewall", "guest.state",
    )
    # [CHANGE] 2026-08-03 由 HEADERS 推導欄位位置，避免欄序調整後硬編碼索引失準。
    TAG_COLUMN = HEADERS.index("guest.tag")       # VLAN Tag header
    STATE_COLUMN = HEADERS.index("guest.state")  # State header

    def __init__(self, guest_reader, sysfs_reader):
        self.guest = guest_reader
        self.sysfs = sysfs_reader

    def build(self):
        result = self.guest.nics()
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
        return lines + self._notes(data, ctx)

    # [CHANGE] 2026-08-02 待辦 #26：原本對第 8 欄（linkdown）在斷線時上黃色。
    # 那一欄本身是 Python 版多出來的（bash 全檔無 link_down），欄位既已移除，
    # 著色也一併移除，改用基底的預設（不著色）。
    # [CHANGE] 2026-08-03 上一行的「具名未做」**已完成**，敘述一併更新——留著一句
    #   已經不成立的自述，與 README 照抄 bash 自檢涵蓋範圍是同一種病：文件說謊。
    #   ★ 併記判準變更（使用者 2026-08-03 裁決）：著色與措辭改由 Python 自主，
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
