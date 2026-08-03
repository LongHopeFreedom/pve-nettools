# [CHANGE] 2026-08-01 新增：開機啟用與執行狀態對帳區段（待辦 #8）。
"""持久化 autostart 設定與目前執行狀態的對帳輸出。"""

from ..collect import STATUS_UNAVAILABLE
from ..collect.sysfs import _natural_key
from ..i18n import t
# [CHANGE] 2026-08-03 窄版標題改走共用 helper，verdict 值重用表格 colorizer。
from .base import Section, block_title, kv, note
from .nic import _TrailingTable

__all__ = ["AutostartSection"]


class AutostartSection(Section):
    HEADERS = ("nic.iface", "autostart.configured", "autostart.running",
               "autostart.verdict")

    def __init__(self, netconf_reader, sysfs_reader):
        self.netconf = netconf_reader
        self.sysfs = sysfs_reader

    def build(self):
        # [CHANGE] 2026-08-01 改用 read() 並檢查三態，原本走 autostart()。
        #
        # ★ `autostart()` 只回 {auto, hotplug}，**結構上無法表達 unavailable**。
        #   讀不到 /etc/network/interfaces 時它回 auto=[]，於是每一張執行中的網卡
        #   都會被判成「★ 執行中但未設 autostart——重開機後會消失」。那不是漏報，
        #   是**憑空生出的嚴重警告**，而且整份報告沒有一個字說設定檔根本沒讀到。
        #   collect 層的介面缺陷已具名為待辦；這一層先自己走 read() 繞過。
        conf = self.netconf.read()
        if conf.get("status") == STATUS_UNAVAILABLE:
            return {"unavailable": True, "rows": [], "error": conf.get("error")}

        configured = set(conf.get("auto") or [])
        running = set(iface for iface in self.sysfs.interfaces()
                      if self.sysfs.operstate(iface) == "up")
        rows = []
        for iface in sorted(configured | running, key=_natural_key):
            is_configured = iface in configured
            is_running = iface in running
            if is_configured and is_running:
                verdict = t("autostart.ok")
            elif is_running:
                verdict = t("autostart.running_not_auto")
            else:
                verdict = t("autostart.auto_not_running")
            rows.append({
                "cells": [iface,
                          t("app.yes") if is_configured else t("app.no"),
                          t("app.yes") if is_running else t("app.no"), verdict],
                "mismatch": is_configured != is_running,
            })
        return {"unavailable": False, "rows": rows, "error": None}

    def _notes(self, ctx):
        return [note(t("autostart.note"), ctx.palette)]

    def is_empty(self, data):
        return not data["rows"]

    def table(self, data, ctx):
        table = _TrailingTable([t(key) for key in self.HEADERS], self._notes(ctx))
        for row in data["rows"]:
            table.add(row["cells"])
        return table

    def blocks(self, data, ctx):
        lines = []
        paint = self.colorizer(data, ctx)
        for row_index, row in enumerate(data["rows"]):
            cells = row["cells"]
            lines.append(block_title(cells[0], ctx.palette))
            lines.append(kv(t("autostart.configured"), paint(row_index, 1, cells[1]),
                            key_width=8))
            lines.append(kv(t("autostart.running"), paint(row_index, 2, cells[2]),
                            key_width=8))
            lines.append(kv(t("autostart.verdict"), paint(row_index, 3, cells[3]),
                            key_width=8))
            lines.append("")
        return lines + self._notes(ctx)

    def colorizer(self, data, ctx):
        def paint(row_index, col_index, text):
            if col_index == 3 and data["rows"][row_index]["mismatch"]:
                return ctx.paint(text, "yellow")
            return text
        return paint

    def empty_lines(self, data, ctx):
        # 「讀不到設定檔」MUST NOT 顯示成「沒有需要對帳的介面」，也不印對帳說明
        # ——沒有對帳發生過。
        if data["unavailable"]:
            return [note(data.get("error") or t("app.not_found"), ctx.palette)]
        return [note(t("app.none"), ctx.palette)] + self._notes(ctx)
