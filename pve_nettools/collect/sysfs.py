"""從 /sys/class/net 取介面狀態。

★ 這個模組存在的主要理由是 read_value() 的錯誤處理。

bash 版原本用 `[[ -r "$path" ]] && cat "$path"` 判斷，但 sysfs 有「檔案可讀卻讀取
失敗」的情形——介面 admin-down 時讀 carrier 會回 EINVAL。結果是回空字串而非預設
值，且 cat 的錯誤訊息外洩到 stderr；報告模式帶 2>&1，那行
`cat: …: Invalid argument` 會直接被寫進盤查報告。

Python 的 try/except OSError 天然涵蓋這個情形，不需要特別處理——但仍要明確寫下
為什麼不能用 os.access() 之類的「可讀性檢查」代替實際讀取。
"""

import os

DEFAULT_ROOT = "/sys/class/net"

# carrier_changes 超過這個值視為線路抖動。開機後正常是 1～2。
FLAP_THRESHOLD = 4


class SysfsReader:
    """讀 sysfs 的介面狀態。root 可替換，讓測試指向 fixture 而不需要真的 sysfs。"""

    def __init__(self, root=None):
        self.root = root or os.environ.get("SYS_NET_ROOT") or DEFAULT_ROOT

    # ── 基礎讀取 ──────────────────────────────────────────────────────

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    def read_value(self, *parts, **kwargs):
        """讀單一 sysfs 屬性；讀不到或內容為空時回 default。

        MUST NOT 改成「先檢查可讀再讀」——sysfs 會讓可讀的檔案在讀取時回 EINVAL
        （介面 admin-down 的 carrier 就是），那種情形只有實際讀下去才知道。
        """
        default = kwargs.pop("default", None)
        if kwargs:
            raise TypeError("未預期的參數：%s" % ", ".join(kwargs))
        try:
            with open(self.path(*parts), "r", encoding="utf-8", errors="replace") as fh:
                value = fh.read().strip()
        except OSError:
            return default
        return value if value else default

    def read_int(self, *parts, **kwargs):
        default = kwargs.pop("default", None)
        if kwargs:
            raise TypeError("未預期的參數：%s" % ", ".join(kwargs))
        raw = self.read_value(*parts)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    # ── 介面列舉 ──────────────────────────────────────────────────────

    def interfaces(self):
        try:
            names = os.listdir(self.root)
        except OSError:
            return []
        return sorted(n for n in names if n != "lo" and os.path.isdir(self.path(n)))

    def is_physical(self, nic):
        """實體 PCI/USB 網卡具有 device 連結；tap/veth/bridge/bond/vlan 皆無。"""
        return os.path.exists(self.path(nic, "device"))

    def physical_nics(self):
        return sorted((n for n in self.interfaces() if self.is_physical(n)),
                      key=_natural_key)

    def is_bridge(self, nic):
        return os.path.isdir(self.path(nic, "bridge"))

    def is_bond(self, nic):
        return os.path.isdir(self.path(nic, "bonding"))

    def bridges(self):
        return sorted((n for n in self.interfaces() if self.is_bridge(n)), key=_natural_key)

    def bridge_ports(self, bridge):
        try:
            return sorted(os.listdir(self.path(bridge, "brif")), key=_natural_key)
        except OSError:
            return []

    def exists(self, nic):
        return os.path.exists(self.path(nic))

    # [CHANGE] 2026-08-02 新增：bash get_interface_type 的等價（選單 8 的上層類型欄）。
    def interface_type(self, nic):
        """判斷介面種類，回**鍵**而不是顯示文字。

        ★ 回鍵不回文字：顯示文字要雙語，而判定邏輯只有一套。bash 直接 echo 中文，
          那是它沒有 i18n 才做得起來的；照抄會讓英文介面混進中文。

        ★ 判定順序**逐字沿用 bash**：bonding → bridge → device → 空值 → 其他。
          順序在這裡有語意——bond 與 bridge 都可能同時具有 device 連結（某些驅動
          會建），先問 bonding 才不會把 bond 判成實體網卡。
        """
        if self.is_bond(nic):
            return "bond"
        if self.is_bridge(nic):
            return "bridge"
        if self.is_physical(nic):
            return "physical"
        if not nic or nic == "N/A":
            return "unknown"
        return "other"

    # ── 常用屬性 ──────────────────────────────────────────────────────

    def mac(self, nic):
        return self.read_value(nic, "address", default="N/A")

    def mtu(self, nic):
        return self.read_value(nic, "mtu", default="N/A")

    def operstate(self, nic):
        return self.read_value(nic, "operstate", default="unknown")

    def carrier(self, nic):
        """回傳 True/False/None。None 代表讀不到——admin-down 時 sysfs 回 EINVAL。"""
        raw = self.read_value(nic, "carrier")
        if raw == "1":
            return True
        if raw == "0":
            return False
        return None

    def carrier_changes(self, nic):
        return self.read_int(nic, "carrier_changes")

    def is_flapping(self, nic):
        changes = self.carrier_changes(nic)
        return changes is not None and changes > FLAP_THRESHOLD

    def numa_node(self, nic):
        value = self.read_value(nic, "device", "numa_node")
        if value in (None, "-1"):
            return None
        return value

    def statistic(self, nic, name):
        return self.read_int(nic, "statistics", name, default=0)

    def error_counters(self, nic):
        """回傳錯誤與丟包計數。CRC 單獨列出——它非 0 幾乎必為實體層問題。"""
        return {
            "rx_errors": self.statistic(nic, "rx_errors"),
            "rx_dropped": self.statistic(nic, "rx_dropped"),
            "tx_errors": self.statistic(nic, "tx_errors"),
            "tx_dropped": self.statistic(nic, "tx_dropped"),
            "rx_crc_errors": self.statistic(nic, "rx_crc_errors"),
        }

    # ── bridge 屬性 ───────────────────────────────────────────────────

    def bridge_attr(self, bridge, name, default=None):
        return self.read_value(bridge, "bridge", name, default=default)

    def vlan_filtering(self, bridge):
        return self.bridge_attr(bridge, "vlan_filtering", default="0") == "1"

    def vlan_protocol(self, bridge):
        return self.bridge_attr(bridge, "vlan_protocol")

    def default_pvid(self, bridge):
        return self.bridge_attr(bridge, "default_pvid")

    def stp_enabled(self, bridge):
        return self.bridge_attr(bridge, "stp_state", default="0") == "1"


# [CHANGE] 2026-08-05 待辦 #66：ASCII 數字集合。原本這裡用 ch.isdigit()，
# 而 collect/pve.py 與 collect/bridge.py 兩處都已明文記載「MUST NOT 用
# str.isdigit()」——它對上標與全形數字也回 True，隨後的 int() 會拋 ValueError。
# 實測 _natural_key("eth²") 直接拋 ValueError，而網卡清單排序在整份報告的最前段。
# ★ 可達性**本棒未實測**（開發機是 Windows，建不了 Linux 介面）：介面名來自
#   /sys/class/net/ 的目錄名，依核心 dev_valid_name() 的規則（只擋 '/'、空白、
#   空字串與長度）**推論** `ip link add name eth² type dummy` 應可成立——
#   那是推論不是量測，MUST NOT 當成已驗證。已列入真機驗證手冊的待驗項。
# ★★ 但修法的正當性**不依賴可達性**：判斷用 isdigit()、轉換用 int()，是拿
#   **兩套不同的數字判準**處理同一份資料，它們對同一個輸入給出不一致的答案
#   （"２" 一個判成數字一個判成非數字；"²" 一個判成數字另一個直接拋例外）。
#   那本身就是缺陷，與有沒有人真的建出那種介面無關。
_ASCII_DIGITS = frozenset("0123456789")


def _natural_key(name):
    """讓 eno2 排在 eno10 前面。純字典序會把 eno10 排到 eno2 之前。"""
    parts = []
    digits = ""
    for ch in name:
        if ch in _ASCII_DIGITS:
            digits += ch
        else:
            if digits:
                parts.append((1, int(digits), ""))
                digits = ""
            parts.append((0, 0, ch))
    if digits:
        parts.append((1, int(digits), ""))
    return parts


def sample_traffic(reader, nics, seconds=3, sleep_fn=None):
    """取樣 RX/TX 計數器，回傳 {nic: (rx_delta, tx_delta)}。

    sleep_fn 可注入，讓測試不必真的等——真的 sleep 會讓一個單元測試花好幾秒，
    最後的下場就是沒有人跑它。
    """
    import time
    sleep = sleep_fn if sleep_fn is not None else time.sleep

    before = {n: (reader.statistic(n, "rx_bytes"), reader.statistic(n, "tx_bytes"))
              for n in nics}
    if seconds > 0:
        sleep(seconds)
    out = {}
    for nic in nics:
        rx_after = reader.statistic(nic, "rx_bytes")
        tx_after = reader.statistic(nic, "tx_bytes")
        rx_before, tx_before = before[nic]
        # 計數器可能歸零（驅動重載），負值一律視為 0 而非顯示負數流量
        out[nic] = (max(0, rx_after - rx_before), max(0, tx_after - tx_before))
    return out
