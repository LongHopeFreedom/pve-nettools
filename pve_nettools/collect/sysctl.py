# [CHANGE] 2026-08-01 新增：讀取網路核心參數、conntrack 與 IPv4 鄰居用量（待辦 #6）。
"""從 ``/proc/sys`` 與 ``/proc/net/arp`` 取網路核心狀態。

本模組只負責取數與判定，不格式化或輸出報告。路徑以元素 tuple／list 傳入，
不能由點式名稱替換句點，因為 VLAN 介面名稱本身可以包含句點。

鄰居用量只涵蓋 IPv4：目前的筆數來源是 ``/proc/net/arp``，所以只和 IPv4 的
``gc_thresh3`` 比較。per-interface ``rp_filter`` 的有效值是 all 與介面值的最大值，
本模組依本次範圍只收集 all 與 default，不展開各介面，這是已知限制。
"""

import os

from . import STATUS_OK, STATUS_UNAVAILABLE

DEFAULT_ROOT = "/proc/sys"
DEFAULT_ARP_TABLE = "/proc/net/arp"

CONNTRACK_WARN_RATIO = 0.8
NEIGH_WARN_RATIO = 0.8

GROUP_BRIDGE_NF = "bridge_nf"
GROUP_FORWARDING = "forwarding"
GROUP_RP_FILTER = "rp_filter"

KEY_PARAMS = (
    (("net", "bridge", "bridge-nf-call-iptables"),
     "net.bridge.bridge-nf-call-iptables", GROUP_BRIDGE_NF),
    (("net", "bridge", "bridge-nf-call-ip6tables"),
     "net.bridge.bridge-nf-call-ip6tables", GROUP_BRIDGE_NF),
    (("net", "bridge", "bridge-nf-call-arptables"),
     "net.bridge.bridge-nf-call-arptables", GROUP_BRIDGE_NF),
    (("net", "ipv4", "ip_forward"),
     "net.ipv4.ip_forward", GROUP_FORWARDING),
    (("net", "ipv6", "conf", "all", "forwarding"),
     "net.ipv6.conf.all.forwarding", GROUP_FORWARDING),
    (("net", "ipv4", "conf", "all", "rp_filter"),
     "net.ipv4.conf.all.rp_filter", GROUP_RP_FILTER),
    (("net", "ipv4", "conf", "default", "rp_filter"),
     "net.ipv4.conf.default.rp_filter", GROUP_RP_FILTER),
)


class SysctlReader(object):
    """讀取可替換根目錄的 procfs 網路核心參數。"""

    def __init__(self, root=None, arp_table=None):
        self.root = (root if root is not None else
                     os.environ.get("PROC_SYS_ROOT", DEFAULT_ROOT))
        self.arp_table = (arp_table if arp_table is not None else
                          os.environ.get("PROC_NET_ARP", DEFAULT_ARP_TABLE))

    # ── 基礎讀取 ──────────────────────────────────────────────────────

    def path(self, *parts):
        """把路徑元素接在 root 後，回傳絕對路徑。"""
        return os.path.abspath(os.path.join(self.root, *parts))

    @staticmethod
    def _validate_parts(parts):
        """只接受路徑元素 tuple／list，避免誤拆含句點的介面名稱。"""
        if not isinstance(parts, (tuple, list)):
            raise TypeError("parts 必須是路徑元素的 tuple 或 list")
        if not all(isinstance(part, str) for part in parts):
            raise TypeError("每個路徑元素都必須是字串")

    def read_raw(self, parts):
        """讀單一參數並去掉前後空白；讀不到或內容為空時回 None。"""
        self._validate_parts(parts)
        try:
            with open(self.path(*parts), "r", encoding="utf-8",
                      errors="replace") as fh:
                value = fh.read().strip()
        except OSError:
            return None
        return value if value else None

    def read_int(self, parts):
        """讀單一整數；讀不到、非整數或含多個值時回 None。"""
        raw = self.read_raw(parts)
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    # ── 網路核心參數 ──────────────────────────────────────────────────

    def key_params(self):
        """依 KEY_PARAMS 的固定順序回傳關鍵參數與存在狀態。"""
        params = []
        present_count = 0
        for parts, name, _group in KEY_PARAMS:
            value = self.read_raw(parts)
            present = value is not None
            if present:
                present_count += 1
            params.append({"name": name, "value": value, "present": present})
        return {
            "status": STATUS_OK if present_count else STATUS_UNAVAILABLE,
            "params": params,
        }

    def bridge_nf(self):
        """回傳 bridge netfilter 三項值；只有 IP 流量規則會觸發警告。"""
        params = {}
        enabled = []
        missing = []
        warn = False
        for parts, name, group in KEY_PARAMS:
            if group != GROUP_BRIDGE_NF:
                continue
            value = self.read_raw(parts)
            params[name] = value
            if value is None:
                missing.append(name)
            if value == "1":
                enabled.append(name)
                if name in ("net.bridge.bridge-nf-call-iptables",
                            "net.bridge.bridge-nf-call-ip6tables"):
                    warn = True
        return {
            "status": STATUS_UNAVAILABLE if len(missing) == 3 else STATUS_OK,
            "params": params,
            "enabled": enabled,
            "missing": missing,
            "warn": warn,
        }

    def conntrack(self):
        """回傳 conntrack 用量；max 新路徑不存在時支援舊核心 fallback。"""
        count = self.read_int(("net", "netfilter", "nf_conntrack_count"))
        maximum = self.read_int(("net", "netfilter", "nf_conntrack_max"))
        if maximum is None:
            maximum = self.read_int(("net", "nf_conntrack_max"))

        usage = None
        if count is not None and maximum is not None and maximum > 0:
            usage = float(count) / maximum
        unavailable = count is None and maximum is None
        return {
            "status": STATUS_UNAVAILABLE if unavailable else STATUS_OK,
            "count": count,
            "max": maximum,
            "usage": usage,
            "warn": usage is not None and usage >= CONNTRACK_WARN_RATIO,
            "error": "無法讀取 conntrack 核心參數，模組可能尚未載入" if unavailable else None,
        }

    def _arp_count(self):
        """計算 IPv4 ARP 資料列；第一行標題不計，incomplete 項目仍計入。"""
        try:
            with open(self.arp_table, "r", encoding="utf-8",
                      errors="replace") as fh:
                lines = fh.read().splitlines()
        except OSError:
            return None
        return sum(1 for line in lines[1:] if line.strip())

    def neigh(self):
        """回傳 IPv4 鄰居用量；不以較低門檻替代缺少的 gc_thresh3。"""
        threshold1 = self.read_int(
            ("net", "ipv4", "neigh", "default", "gc_thresh1"))
        threshold2 = self.read_int(
            ("net", "ipv4", "neigh", "default", "gc_thresh2"))
        threshold3 = self.read_int(
            ("net", "ipv4", "neigh", "default", "gc_thresh3"))
        current = self._arp_count()

        usage = None
        if current is not None and threshold3 is not None and threshold3 > 0:
            usage = float(current) / threshold3
        unavailable = (current is None and threshold1 is None and
                       threshold2 is None and threshold3 is None)
        return {
            "status": STATUS_UNAVAILABLE if unavailable else STATUS_OK,
            "current": current,
            "gc_thresh1": threshold1,
            "gc_thresh2": threshold2,
            "gc_thresh3": threshold3,
            "usage": usage,
            "warn": usage is not None and usage >= NEIGH_WARN_RATIO,
            "error": "無法讀取 IPv4 鄰居表與核心門檻" if unavailable else None,
        }

    def read(self):
        """彙整關鍵參數、bridge netfilter、conntrack 與 IPv4 鄰居狀態。"""
        params = self.key_params()
        bridge = self.bridge_nf()
        conntrack = self.conntrack()
        neigh = self.neigh()
        children = (params, bridge, conntrack, neigh)
        unavailable = all(item["status"] == STATUS_UNAVAILABLE
                          for item in children)
        return {
            "status": STATUS_UNAVAILABLE if unavailable else STATUS_OK,
            "params": params,
            "bridge_nf": bridge,
            "conntrack": conntrack,
            "neigh": neigh,
        }
