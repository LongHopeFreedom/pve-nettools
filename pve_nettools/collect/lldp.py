# [CHANGE] 2026-08-02 新增：LLDP 鄰居解析、服務狀態判定與指令快取。
"""收集 lldpd 鄰居資訊，並保留完整原始輸出。"""

import re

from . import (STATUS_EMPTY, STATUS_OK, STATUS_UNAVAILABLE, default_run,
               parsed_result, run_command)


_VALUE_RE = re.compile(r"^[^:]*:\s*(.*)$")


def _value(line):
    found = _VALUE_RE.match(line)
    return found.group(1) if found is not None else ""


def parse_neighbors(text):
    """回傳 iface、sysname、portid、portdescr；缺值保留為 None。"""
    records = []
    current = None
    fields = {
        "SysName": "sysname",
        "PortID": "portid",
        "PortDescr": "portdescr",
    }
    for line in (text or "").splitlines():
        stripped = line.lstrip()
        if line.startswith("Interface:"):
            if current is not None:
                records.append(current)
            tail = line.split(":", 1)[1]
            iface = tail.split(",", 1)[0].strip()
            current = {
                "iface": iface,
                "sysname": None,
                "portid": None,
                "portdescr": None,
            }
            continue
        if current is None or ":" not in stripped:
            continue
        name = stripped.split(":", 1)[0]
        if name in fields and current[fields[name]] is None:
            value = _value(stripped)
            current[fields[name]] = value if value else None
    if current is not None:
        records.append(current)
    return records


class LldpReader(object):
    """執行 lldpcli/systemctl；快取讓摘要與 raw 共用同一次鄰居查詢。"""

    def __init__(self, run_fn=None):
        self.run_fn = run_fn if run_fn is not None else default_run
        self._cache = {}

    def _command(self, argv):
        key = tuple(argv)
        if key not in self._cache:
            self._cache[key] = run_command(self.run_fn, argv)
        return self._cache[key]

    def _neighbors_command(self):
        return self._command(["lldpcli", "show", "neighbors", "details"])

    def installed(self):
        # [CHANGE] 2026-08-02 裸字串 "unavailable" 改用常數。
        # ★ collect/__init__.py 的 docstring 明寫過這條的理由：狀態是靠字面
        #   字串比對的，某一邊把 "unavailable" 打成 "unavailble"，呼叫端只會
        #   **靜默**走進另一條分支——沒有例外、沒有紅色，只有錯誤的結論。
        return self._neighbors_command()["status"] != STATUS_UNAVAILABLE

    def service_active(self):
        """`systemctl is-active --quiet lldpd` 的離開碼是否為 0。

        ★ `--quiet` 的意思就是不印東西，所以「服務正常」在 run_command 眼中是
          **STATUS_EMPTY**（離開碼 0、stdout 空），不是 STATUS_OK。只認 OK 會
          讓這個函式永遠回 False，而畫面上只會多印一句「lldpd 未執行」——看起來
          完全像真的。
        """
        result = self._command(["systemctl", "is-active", "--quiet", "lldpd"])
        return result["status"] in (STATUS_OK, STATUS_EMPTY)

    def neighbors(self):
        return parsed_result(self._neighbors_command(), parse_neighbors)

    def raw(self):
        result = self._neighbors_command()
        return result["stdout"] if result["status"] == STATUS_OK else None
