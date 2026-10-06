"""從 /sys/class/net 取介面狀態。

這個模組存在的主要理由是 read_value() 的錯誤處理。

bash 版原本用 `[[ -r "$path" ]] && cat "$path"` 判斷，但 sysfs 有「檔案可讀卻讀取
失敗」的情形——介面 admin-down 時讀 carrier 會回 EINVAL。結果是回空字串而非預設
值，且 cat 的錯誤訊息外洩到 stderr；報告模式帶 2>&1，那行
`cat: …: Invalid argument` 會直接被寫進盤查報告。

Python 的 try/except OSError 天然涵蓋這個情形，不需要特別處理——但仍要明確寫下
為什麼不能用 os.access() 之類的「可讀性檢查」代替實際讀取。
"""

import os

from .lspci import valid_pci_address

DEFAULT_ROOT = "/sys/class/net"


def pci_address_from_path(resolved):
    """已解析的 device 路徑 → PCI 位址（basename）；格式不符回 None。"""
    name = os.path.basename(str(resolved).rstrip("/\\"))
    return name if valid_pci_address(name) else None

# carrier_changes 超過這個值視為線路抖動。開機後正常是 1～2。
FLAP_THRESHOLD = 4

# [CHANGE] 2026-08-25 新增：`/sys/class/net/<nic>/flags` 裡的 IFF_UP 位元。
# 這是 admin state（管理者有沒有把它 up 起來）的唯一可靠來源，見 admin_up()。
IFF_UP = 0x1


class SysfsReader:
    """讀 sysfs 的介面狀態。root 可替換，讓測試指向 fixture 而不需要真的 sysfs。"""

    def __init__(self, root=None):
        self.root = root or os.environ.get("SYS_NET_ROOT") or DEFAULT_ROOT

    # ── 基礎讀取 ──────────────────────────────────────────────────────

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    def read_value(self, *parts, **kwargs):
        """讀單一 sysfs 屬性；讀不到或內容為空時回 default。

        不得改成「先檢查可讀再讀」——sysfs 會讓可讀的檔案在讀取時回 EINVAL
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

    # [CHANGE] 2026-10-06 v03.018.000：型號查詢要用的 PCI 位址。
    # 取 sysfs 而不取 `ethtool -i` 的 bus-info：ethtool 失敗時型號仍要取得到。
    #   `device` 連結解析後的 basename 即位址（例：0000:af:00.0）；USB／virtio 等非
    #   PCI 裝置的 basename 對不上格式，回 None 而不是把它丟給 lspci。
    def pci_address(self, nic):
        try:
            resolved = os.path.realpath(self.path(nic, "device"))
        except (OSError, ValueError):
            return None
        return pci_address_from_path(resolved)

    def is_bridge(self, nic):
        return os.path.isdir(self.path(nic, "bridge"))

    def is_bond(self, nic):
        return os.path.isdir(self.path(nic, "bonding"))

    # [CHANGE] 2026-08-27 新增：VLAN 判定與 bond/vlan 列舉（虛擬介面流量用）。
    #
    # 為什麼不判目錄：bridge 有 `bridge/`、bond 有 `bonding/`，而 **VLAN 在
    #   sysfs 沒有專屬目錄**。8021q 只掛 `lower_<parent>` 連結，而那個連結
    #   bridge port 與 bond slave 也有——拿它判 VLAN 會把每一張 slave 都判成
    #   VLAN。
    # 為什麼不判名稱含點：PVE 現場兩種命名都在用（`vmbr0.100` 含點，
    #   VLAN-aware bridge 的 `vmbr0v100` 與手工的 `vlan200` 不含點），而任何
    #   介面都可以被命名成含點。名稱在這裡**兩個方向都會錯**：漏掉不含點的
    #   真 VLAN，又把含點的實體卡誤判成 VLAN。
    # ⇒ 真值取 uevent 的 DEVTYPE，那是 kernel 自己寫的欄位。
    def devtype(self, nic):
        """回 uevent 的 DEVTYPE；實體網卡沒有這個欄位，故回 None。

        uevent 是多行 KEY=VALUE，DEVTYPE **不保證在第一行**——逐行找，
          不得拿整份內容去 startswith("DEVTYPE=")。
        """
        raw = self.read_value(nic, "uevent")
        if raw is None:
            return None
        for line in raw.splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() == "DEVTYPE":
                return value.strip() or None
        return None

    def is_vlan(self, nic):
        return self.devtype(nic) == "vlan"

    def bonds(self):
        return sorted((n for n in self.interfaces() if self.is_bond(n)),
                      key=_natural_key)

    def vlans(self):
        return sorted((n for n in self.interfaces() if self.is_vlan(n)),
                      key=_natural_key)

    def bridges(self):
        return sorted((n for n in self.interfaces() if self.is_bridge(n)), key=_natural_key)

    # [CHANGE] 2026-08-27 新增：流量表的母體。
    #
    # 這個方法存在的理由是一個**同形**缺陷：在它之前，流量表的母體是
    #   physical_nics()，而 bond／bridge／VLAN 一律沒有 `device` 連結
    #   ⇒ 它們從來沒有進過表格。而「這個介面不在表格裡」與「這個介面沒有
    #   流量」在畫面上完全一樣——都是看不到那一列。
    # 順序是**分組**不是全域排序：實體卡在前，其後 bond → bridge → VLAN。
    #   全域字母序會讓 bond0 排到 eno1 前面，實體卡被虛擬介面打散,而使用者
    #   看這張表的第一個問題幾乎總是「我的網卡怎麼了」。
    # 去重不是防禦性程式設計，是實地形態：某些 bonding 驅動會為 bond
    #   介面建 `device` 連結，那時 bond0 同時滿足 is_physical 與 is_bond，
    #   四段直接相接就會出現**兩列 bond0**——表格裡的重複列看起來像「有兩
    #   張卡」，而那是比缺一列更難察覺的錯。
    def traffic_nics(self):
        """流量表母體：實體卡 ＋ bond ＋ bridge ＋ VLAN（去重、分組排序）。"""
        out = []
        seen = set()
        for group in (self.physical_nics(), self.bonds(), self.bridges(),
                      self.vlans()):
            for nic in group:
                if nic not in seen:
                    seen.add(nic)
                    out.append(nic)
        return out

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

        回鍵不回文字：顯示文字要雙語，而判定邏輯只有一套。bash 直接 echo 中文，
          那是它沒有 i18n 才做得起來的；照抄會讓英文介面混進中文。

        判定順序**逐字沿用 bash**：bonding → bridge → device → 空值 → 其他。
          順序在這裡有語意——bond 與 bridge 都可能同時具有 device 連結（某些驅動
          會建），先問 bonding 才不會把 bond 判成實體網卡。
        """
        if self.is_bond(nic):
            return "bond"
        if self.is_bridge(nic):
            return "bridge"
        if self.is_physical(nic):
            return "physical"
        # [CHANGE] 2026-08-27 新增 vlan 分支。
        # 刻意排在 physical **之後**：bash 原序是 bonding → bridge → device
        #   → 空值 → 其他，插到前面會改動既有三類的判定路徑。VLAN 介面沒有
        #   device 連結，排後面不影響它自己的結果，卻能讓既有三類一格都不動。
        if self.is_vlan(nic):
            return "vlan"
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

    # [CHANGE] 2026-08-25 新增：admin state 與 master，供 collect/linkprobe.py 判斷
    #          一張網卡「能不能碰」。兩者都是**零副作用判斷**，讀而已。
    def admin_up(self, nic):
        """介面的 admin state（`ip link set up` 設的那一個）。讀不到回 None。

        不得用 `operstate` 或 `carrier` 代替，兩者都會給出錯的答案，
          而且在多數主機上**恰好相同**，所以誤用不會立刻現形：

            operstate → admin-up 但沒插線的卡也是 "down"（它是 RFC 2863 的 OPER
                        狀態，不是 admin 狀態）⇒ 會把服役中的卡判成未啟用。
            carrier   → admin-up 但驅動讀不到 carrier 的卡回 None ⇒ 同樣誤判。

          後果不是顯示錯誤：`linkprobe` 會據此對一張**正在承載流量的卡**送出
          `ip link set down`，也就是我們自己製造斷線。

        `flags` 是十六進位字串（例如 "0x1003"），IFF_UP 是最低位元。
        """
        raw = self.read_value(nic, "flags")
        if raw is None:
            return None
        try:
            value = int(raw, 16)
        except ValueError:
            return None
        return bool(value & IFF_UP)

    def master(self, nic):
        """介面的 master（bond／bridge）名稱；沒有 master 時回 None。

        `/sys/class/net/<nic>/master` 是指向 master 介面目錄的符號連結。
        用 `lexists` 而不是 `exists`：連結目標若已消失（master 剛被拆掉），
          `exists` 對斷掉的符號連結回 False，於是這張仍掛在 master 底下的卡會被
          判成「自由的」而遭探測。斷連結代表**狀態正在變動**，那更該別碰。
        """
        path = self.path(nic, "master")
        if not os.path.lexists(path):
            return None
        name = os.path.basename(os.path.realpath(path))
        return name or None

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


# [CHANGE] 2026-08-05：ASCII 數字集合。原本這裡用 ch.isdigit()，
# 而 collect/pve.py 與 collect/bridge.py 兩處都已明文記載「不得用
# str.isdigit()」——它對上標與全形數字也回 True，隨後的 int() 會拋 ValueError。
# 實測 _natural_key("eth²") 直接拋 ValueError，而網卡清單排序在整份報告的最前段。
# 可達性**本版未實測**（開發機是 Windows，建不了 Linux 介面）：介面名來自
#   /sys/class/net/ 的目錄名，依核心 dev_valid_name() 的規則（只擋 '/'、空白、
#   空字串與長度）**推論** `ip link add name eth² type dummy` 應可成立——
#   那是推論不是量測，不得當成已驗證。已列入真機驗證手冊的待驗項。
# 但修法的正當性**不依賴可達性**：判斷用 isdigit()、轉換用 int()，是拿
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


# [CHANGE] 2026-10-06 v03.016.001：預設取樣窗 3 → 10 秒，並收成單一常數。
# WHY: 真機上 bond 的 TX 很稀疏，3 秒窗內多半一個封包都沒有，正常的 slave 被
#      顯示成「無流量」。此前同一個 3 分別寫在本檔、render/nic.py、app.py。
# usage 與 README 也寫著這個值，由 tests/test_sample_seconds_default.py 對帳。
DEFAULT_SAMPLE_SECONDS = 10


# [CHANGE] 2026-10-06 v03.019.000：bond 與成員相鄰讀取、量測兩輪讀取耗時、矛盾偵測。
# WHY: 母體順序是 實體卡 → bond → bridge → VLAN，bond 與它的成員不是同一瞬間讀的；
#      真機曾出現一次 bond0 TX 有流量而兩張成員 TX 皆無，成因未證實，讀取時間差是
#      程式內唯一可能的路徑（只是推測）。這裡縮小時間差，並讓矛盾再出現時留下數字。
def _read_order(nics, bond_members):
    """讀取順序：某個 bond 的成員緊接在該 bond 之前；其餘維持原相對順序。

    只有同時在 nics 內的成員才會被搬動。成員本身若也列了成員（不應發生）不當成員處理，
    一張網卡被多個 bond 列為成員時以先出現者為準，確保每張網卡恰好讀一次。
    """
    if not bond_members:
        return list(nics)
    present = set(nics)
    owner = {}
    for bond in nics:
        for member in bond_members.get(bond) or ():
            if (member in present and member != bond
                    and member not in bond_members and member not in owner):
                owner[member] = bond
    order = []
    for nic in nics:
        if nic in owner:
            continue
        order.extend(m for m in nics if owner.get(m) == nic)
        order.append(nic)
    return order


def sample_traffic(reader, nics, seconds=DEFAULT_SAMPLE_SECONDS,
                   sleep_fn=None, bond_members=None, timing=None, clock=None):
    """取樣 RX/TX 計數器，回傳 {nic: (rx_delta, tx_delta)}。

    sleep_fn 可注入，讓測試不必真的等——真的 sleep 會讓一個單元測試花好幾秒，
    最後的下場就是沒有人跑它。

    bond_members：{bond: [成員名]}，可省略。給了之後兩輪讀取都改成「成員 → 緊接著該
    bond」，縮小兩者之間的時間差；回傳 dict 的鍵順序仍與 nics 相同。
    timing：可省略的輸出 dict，會被填入 first／second（兩輪讀取各自的耗時，秒，不含
    等待）。clock 可注入（預設 time.monotonic）。
    """
    import time
    sleep = sleep_fn if sleep_fn is not None else time.sleep
    now = clock if clock is not None else time.monotonic
    order = _read_order(nics, bond_members)

    def read_all():
        started = now()
        values = {n: (reader.statistic(n, "rx_bytes"), reader.statistic(n, "tx_bytes"))
                  for n in order}
        return values, now() - started

    before, first = read_all()
    if seconds > 0:
        sleep(seconds)
    after, second = read_all()
    if timing is not None:
        timing["first"] = first
        timing["second"] = second
    out = {}
    for nic in nics:
        rx_after, tx_after = after[nic]
        rx_before, tx_before = before[nic]
        # 計數器可能歸零（驅動重載），負值一律視為 0 而非顯示負數流量
        out[nic] = (max(0, rx_after - rx_before), max(0, tx_after - tx_before))
    return out


def bond_traffic_conflicts(traffic, bond_members):
    """找出 bond 與成員取樣結果互相矛盾的方向，回傳 list（可為空）。

    RX 與 TX 分開判斷；只算本次取樣內（traffic 有該鍵）的成員，一張都沒有就不判斷。
    矛盾＝「bond 有差值而成員合計為 0」或「bond 為 0 而成員合計大於 0」。兩邊都有
    差值但不相等是忙碌 bond 的常態，不算。每筆為 dict：
    bond、direction（"rx"／"tx"）、bond_delta、members_delta、members。
    """
    out = []
    for bond, names in (bond_members or {}).items():
        if bond not in traffic:
            continue
        members = [n for n in (names or ()) if n in traffic and n != bond]
        if not members:
            continue
        for index, direction in enumerate(("rx", "tx")):
            bond_delta = traffic[bond][index]
            members_delta = sum(traffic[n][index] for n in members)
            if (bond_delta > 0) != (members_delta > 0):
                out.append({"bond": bond, "direction": direction,
                            "bond_delta": bond_delta,
                            "members_delta": members_delta,
                            "members": members})
    return out
