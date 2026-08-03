# [CHANGE] 2026-08-01 新增：sysctl、conntrack 與鄰居容量輸出區段（待辦 #8）。
"""網路核心參數與容量指標輸出。"""

from ..collect import STATUS_UNAVAILABLE
from ..i18n import t
from ..width import Table
from .base import Section, kv, note

__all__ = ["ConntrackSection", "NeighSection", "SysctlSection"]


def _value(value):
    return t("app.na") if value is None else str(value)


class SysctlSection(Section):
    HEADERS = ("sysctl.key", "sysctl.value", "sysctl.note")

    def __init__(self, reader):
        self.reader = reader

    def build(self):
        result = self.reader.read()
        enabled = set(result["bridge_nf"].get("enabled") or [])
        rows = []
        for param in result["params"].get("params") or []:
            warning = param.get("name") in enabled
            rows.append({
                "cells": [param.get("name"), _value(param.get("value")),
                          t("sysctl.bridge_nf_warn") if warning else ""],
                "warning": warning,
            })
        return rows

    def table(self, data, ctx):
        table = Table([t(key) for key in self.HEADERS])
        for row in data:
            table.add(row["cells"])
        return table

    def blocks(self, data, ctx):
        lines = []
        for row in data:
            lines.append(kv(row["cells"][0], row["cells"][1], key_width=8))
            if row["warning"]:
                lines.append(note(row["cells"][2], ctx.palette))
        return lines

    def colorizer(self, data, ctx):
        def paint(row_index, col_index, text):
            if col_index == 2 and data[row_index]["warning"]:
                return ctx.paint(text, "yellow")
            return text
        return paint


class _CapacitySection(Section):
    """conntrack／neigh 共用的無表格容量區段。"""

    source_key = None

    def __init__(self, reader):
        self.reader = reader

    def build(self):
        return self.reader.read()[self.source_key]

    def table(self, data, ctx):
        return None

    def is_empty(self, data):
        return False

    def empty_lines(self, data, ctx):
        return []


class ConntrackSection(_CapacitySection):
    source_key = "conntrack"

    def blocks(self, data, ctx):
        if data.get("status") == STATUS_UNAVAILABLE:
            return [note(_value(data.get("error")), ctx.palette)]
        usage = data.get("usage")
        usage_text = t("app.na") if usage is None else "%.1f%%" % (usage * 100.0)
        lines = [
            kv(t("conntrack.used"), _value(data.get("count"))),
            kv(t("conntrack.max"), _value(data.get("max"))),
            kv(t("conntrack.usage"), usage_text),
        ]
        if data.get("warn") is True:
            lines.append(note(t("conntrack.warn"), ctx.palette))
        return lines


class NeighSection(_CapacitySection):
    source_key = "neigh"

    def blocks(self, data, ctx):
        if data.get("status") == STATUS_UNAVAILABLE:
            return [note(_value(data.get("error")), ctx.palette)]
        thresholds = " / ".join(
            _value(data.get(key))
            for key in ("gc_thresh1", "gc_thresh2", "gc_thresh3"))
        lines = [
            kv(t("neigh.current"), _value(data.get("current"))),
            kv(t("neigh.thresh"), thresholds),
        ]
        if data.get("warn") is True:
            lines.append(note(t("neigh.warn"), ctx.palette))
        return lines
