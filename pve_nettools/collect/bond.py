# [CHANGE] 2026-08-02 新增：Bond procfs 解析與可注入 sysfs 的供料層。
"""解析 Linux bonding 驅動輸出。

Bond 與 slave 都會出現 ``MII Status``；頂層欄位只在第一個 slave 之前取第一筆，
避免成員狀態覆蓋整個 Bond 的狀態。
"""

import os

from . import STATUS_EMPTY, STATUS_OK, STATUS_UNAVAILABLE
from .sysfs import SysfsReader


_BOND_FIELDS = {
    "Bonding Mode": "mode",
    "Transmit Hash Policy": "hash_policy",
    "MII Status": "status",
    "Currently Active Slave": "active_slave",
    "Primary Slave": "primary_slave",
}

_SLAVE_FIELDS = {
    "MII Status": "status",
    "Speed": "speed",
    "Permanent HW addr": "permanent_mac",
    "Aggregator ID": "aggregator_id",
}


def _field(line):
    if ":" not in line:
        return None, None
    name, value = line.split(":", 1)
    return name.strip(), value.strip()


def parse_bond(text):
    """回傳 Bond 頂層欄位與依原始順序排列的 slave 明細。"""
    parsed = dict((name, None) for name in _BOND_FIELDS.values())
    slaves = []
    current = None
    in_slaves = False

    for line in (text or "").splitlines():
        name, value = _field(line)
        if name == "Slave Interface":
            if current is not None:
                slaves.append(current)
            current = {
                "name": value or None,
                "status": None,
                "speed": None,
                "permanent_mac": None,
                "aggregator_id": None,
            }
            in_slaves = True
            continue

        if not in_slaves and name in _BOND_FIELDS:
            key = _BOND_FIELDS[name]
            if parsed[key] is None:
                parsed[key] = value or None
        elif current is not None and name in _SLAVE_FIELDS:
            current[_SLAVE_FIELDS[name]] = value or None

    if current is not None:
        slaves.append(current)
    parsed["slaves"] = slaves
    return parsed


def slave_names_text(parsed):
    """以 ``, `` 串接成員名稱，逐字維持 bash 報告原有的逗號加空格分隔符。"""
    names = [item.get("name") for item in (parsed or {}).get("slaves", [])]
    return ", ".join(name for name in names if name)


class BondReader(object):
    """讀 procfs Bond 檔；run_fn 僅為遵守 Reader 注入介面，這一層不跑外部指令。"""

    def __init__(self, proc_dir=None, sysfs_reader=None, run_fn=None):
        self.proc_dir = proc_dir or os.environ.get("PROC_BONDING_DIR") or "/proc/net/bonding"
        self.sysfs_reader = sysfs_reader if sysfs_reader is not None else SysfsReader()
        self.run_fn = run_fn
        self._cache = {}

    def bonds(self):
        try:
            names = os.listdir(self.proc_dir)
        except OSError:
            return []
        return sorted(name for name in names
                      if os.path.isfile(os.path.join(self.proc_dir, name)))

    def read(self, name):
        if name in self._cache:
            return self._cache[name]
        path = os.path.join(self.proc_dir, name)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                text = handle.read()
        except OSError as exc:
            result = {"status": STATUS_UNAVAILABLE, "data": None, "error": str(exc)}
        else:
            if text.strip():
                result = {"status": STATUS_OK, "data": parse_bond(text), "error": None}
            else:
                result = {"status": STATUS_EMPTY, "data": {}, "error": None}
        self._cache[name] = result
        return result

    def lacp_rate(self, name):
        return self.sysfs_reader.read_value(name, "bonding", "lacp_rate")

    def min_links(self, name):
        return self.sysfs_reader.read_value(name, "bonding", "min_links")

    def available(self):
        return os.path.isdir(self.proc_dir) and bool(self.bonds())
