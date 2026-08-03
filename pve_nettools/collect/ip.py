# [CHANGE] 2026-08-02 新增：iproute2 的 `ip` 指令供料（選單 5／6／8／12 的共用原語）。
"""從 iproute2 的 ``ip`` 取位址、路由、鄰居與 VLAN 子介面。

## 為什麼是一個模組而不是散在各區段

bash 版的 `get_addresses` 被 `render_bonds`、`render_bridges`、`render_ovs`、
`render_vlan_subinterfaces` 四個區段呼叫；`ip -br addr`／`ip route`／`ip neigh`
則集中在 `render_ip_routing`。這些全都是同一支指令的不同子命令，錯誤處理（沒裝
iproute2、非零離開碼）也完全一樣，因此供料只寫一份。

## 欄位取法為什麼是 split()[3]

bash 的 `get_addresses` 是 ``ip -o -4 addr show dev X | awk '{print $4}'``。
``-o``（oneline）保證每個位址一行，欄位固定為：

    2: eno1    inet 192.168.1.10/24 brd ... scope global eno1\\  valid_lft ...
    ^索引0     ^2   ^3

IPv6 同樣是第 4 欄（``inet6 fe80::1/64``），所以兩個 family 共用一套解析。

★ 這裡**刻意不**改用 ``ip -j``（JSON）：PVE 8 的 iproute2 支援，但更舊的
  Debian 版本不支援，而本工具的相容下界是「能跑就要對」。輸出格式的穩定性由
  ``-o`` 保證，不是靠推測。
"""

import re

from . import (STATUS_EMPTY, STATUS_OK, STATUS_UNAVAILABLE, default_run,
               run_command)
# [CHANGE] 2026-08-02 排序鍵取用 sysfs 的既有實作，不自己再寫一份。
# ★ 我第一版真的另寫了一份（re.split 版），而它與 sysfs 版**行為不同**：混合型別
#   的 tuple 在某些名稱組合下會拋 TypeError。同一個概念的第二份實作不只是重複，
#   它還可能是錯的——而排序錯了畫面上只是順序不同，沒有任何東西會變紅。
#   render/netconf.py 早已這樣跨模組取用，本檔照辦。
from .sysfs import _natural_key

__all__ = [
    "IpReader",
    "parse_addr_show",
    "parse_neigh",
    "parse_vlan_id",
    "parse_vlan_link_names",
    "parse_vlan_parent",
]

# bash render_ip_routing 只列這兩種鄰居狀態，其餘（FAILED／INCOMPLETE）濾掉。
NEIGH_STATES = ("REACHABLE", "STALE")

_VLAN_ID_RE = re.compile(r"\bvlan\s+protocol\s+\S+\s+id\s+(\d+)\b")


def parse_addr_show(text):
    """從 ``ip -o -{4,6} addr show`` 取出位址清單（含前綴長度）。"""
    found = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 4:
            found.append(fields[3])
    return found


def parse_neigh(text, states=NEIGH_STATES):
    """只留下指定狀態的鄰居行。

    ★ 用**整詞**比對而不是子字串：`grep -E 'REACHABLE|STALE'` 在 bash 是對整行做
      的，而鄰居行的狀態一定是獨立的一個欄位。以欄位判定可避免某天有人把介面命名
      成 `stale0` 就混進來——形態列舉（找這串字）與性質（這一欄是狀態）在這裡會
      給出不同答案。

    ★★ **這是與 bash 的具名差異，不是等價實作。** bash 的 `grep -E` 是子字串比對，
      而 `REACHABLE` **是 `UNREACHABLE` 的子字串** ⇒ bash 會把 UNREACHABLE 的鄰居
      也收進表裡。那與它自己在同一頁印出來的兩句話相矛盾：小標題寫「僅列 REACHABLE
      與 STALE」，註腳寫「本表已先濾掉 FAILED / INCOMPLETE 等狀態」。
      這裡取 bash 的**宣告意圖**而不是它的實作——一個「不可達」的鄰居被列在
      「可達」表裡，會讓人往完全錯誤的方向查。
      ★ 若哪天要求逐字等價（連 bug 一起），改回子字串比對即可，但 MUST 同時
        修掉那兩句說明，否則畫面自己會互相打臉。
    """
    wanted = set(states)
    return [line for line in text.splitlines()
            if wanted & set(line.split())]


def parse_vlan_link_names(text):
    """從 ``ip -d -o link show type vlan`` 取出 VLAN 介面名（去掉 ``@parent``）。"""
    found = []
    for line in text.splitlines():
        parts = line.split(": ")
        if len(parts) < 2:
            continue
        name = parts[1].strip()
        if "@" in name:
            name = name.split("@", 1)[0]
        if name and name not in found:
            found.append(name)
    return found


def parse_vlan_parent(text):
    """從 ``ip -o link show <vlan>`` 取出 ``@`` 之後的上層介面名。"""
    for line in text.splitlines():
        parts = line.split(": ")
        if len(parts) < 2:
            continue
        name = parts[1].strip()
        if "@" in name:
            # bash 用 sub(/^.*@/, "")＝貪婪，取**最後**一個 @ 之後的內容。
            return name.rsplit("@", 1)[1]
    return None


def parse_vlan_id(text):
    """從 ``ip -d link show <vlan>`` 取出 ``vlan protocol 802.1Q id N`` 的 N。"""
    found = _VLAN_ID_RE.search(text)
    return found.group(1) if found is not None else None


class IpReader(object):
    """讀 ``ip``；run_fn 可替換，避免測試依賴主機是否安裝 iproute2。"""

    def __init__(self, run_fn=None):
        self.run_fn = run_fn if run_fn is not None else default_run
        self._cache = {}

    def _command(self, argv):
        """★ 快取以 argv 為鍵。`get_addresses` 在 bash 版被每個介面各呼叫兩次
        （v4／v6），區段之間也重複——沒有快取時一台 12 介面的主機要跑 24 次。
        """
        key = tuple(argv)
        if key not in self._cache:
            self._cache[key] = run_command(self.run_fn, argv)
        return self._cache[key]

    # ── 位址 ──────────────────────────────────────────────────────────

    def addresses(self, iface, family=4):
        """單一介面的位址清單，回 {status, data, error}；data 為 list。"""
        command = self._command(
            ["ip", "-o", "-%d" % family, "addr", "show", "dev", iface])
        if command["status"] != STATUS_OK:
            return {"status": command["status"], "data": None,
                    "error": command["error"]}
        found = parse_addr_show(command["stdout"])
        return {"status": STATUS_OK if found else STATUS_EMPTY,
                "data": found, "error": None}

    def address_text(self, iface, family=4, empty="-"):
        """bash `get_addresses` 的等價：逗號串接，查無時回 ``-``。

        ★ 與 bash 逐字等價，包含「查不到 ip 指令」與「查到但沒有位址」都印 ``-``
          這一點。兩者在 bash 裡是同一個分支（`${addresses:--}`），這裡刻意不
          「改善」成分辨兩者——畫面等價優先，要分辨請用 addresses()。
        """
        result = self.addresses(iface, family)
        if not result["data"]:
            return empty
        return ",".join(result["data"])

    def brief_addresses(self, family=4):
        """``ip -br -{4,6} addr show`` 的原始行，供選單 12 逐行印出。"""
        return self._lines(["ip", "-br", "-%d" % family, "addr", "show"])

    # ── 路由與鄰居 ────────────────────────────────────────────────────

    def routes(self, family=4):
        return self._lines(["ip", "-%d" % family, "route", "show"])

    def neighbours(self):
        """只回 REACHABLE／STALE 的鄰居行，與 bash 的 grep -E 同範圍。"""
        result = self._lines(["ip", "neigh", "show"])
        if result["status"] != STATUS_OK:
            return result
        lines = parse_neigh("\n".join(result["lines"]))
        return {"status": STATUS_OK if lines else STATUS_EMPTY,
                "lines": lines, "error": None}

    # ── VLAN 子介面 ───────────────────────────────────────────────────

    def vlan_interfaces(self):
        command = self._command(["ip", "-d", "-o", "link", "show", "type", "vlan"])
        if command["status"] != STATUS_OK:
            return {"status": command["status"], "data": None,
                    "error": command["error"]}
        names = sorted(parse_vlan_link_names(command["stdout"]), key=_natural_key)
        return {"status": STATUS_OK if names else STATUS_EMPTY,
                "data": names, "error": None}

    def vlan_parent(self, iface):
        command = self._command(["ip", "-o", "link", "show", iface])
        if command["status"] != STATUS_OK:
            return None
        return parse_vlan_parent(command["stdout"])

    def vlan_id(self, iface):
        command = self._command(["ip", "-d", "link", "show", iface])
        if command["status"] != STATUS_OK:
            return None
        return parse_vlan_id(command["stdout"])

    # ── 共用 ──────────────────────────────────────────────────────────

    def available(self):
        """`ip` 指令本身能不能跑。對應 bash 的 `command_exists ip`。

        ★ 判準是「跑不跑得起來」而不是「有沒有輸出」——`ip -o link show` 在
          只有 lo 的極端環境仍會有輸出，但真正要問的是 iproute2 裝了沒有。
        """
        # [CHANGE] 2026-08-02 原本寫成裸字串 "unavailable"（我自己也犯了同一條）。
        return (self._command(["ip", "-o", "link", "show"])["status"]
                != STATUS_UNAVAILABLE)

    def _lines(self, argv):
        command = self._command(argv)
        if command["status"] != STATUS_OK:
            return {"status": command["status"], "lines": None,
                    "error": command["error"]}
        lines = [line for line in command["stdout"].splitlines() if line.strip()]
        return {"status": STATUS_OK if lines else STATUS_EMPTY,
                "lines": lines, "error": None}
