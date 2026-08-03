# [CHANGE] 2026-07-31 新增：bridge vlan show 解析、VLAN 範圍壓縮與包含判斷（待辦 #3）。
"""解析 ``bridge vlan show``，並以「範圍」為核心處理 VLAN 清單。

★ 這個模組存在的兩個理由都與範圍有關，而且方向相反。

一、顯示要「壓成範圍」
    PVE 常見設定 ``bridge-vids 2-4090``。當 bridge vlan show 逐個列出而非合併成
    範圍時，單一 port 的 VLAN 清單會串成 23432 字元的單行——實測即為此值。這一行
    在 80 欄終端折成約 300 行，把表頭與前面所有 port 全部推出畫面，使用者只看得到
    最後一小段。壓成 ``1u,2-4090t`` 後是 10 字元。

二、對帳要「不展開範圍」
    判斷某個 VLAN 有沒有被放行時 MUST NOT 展開。實測展開 ``2-4090`` 要 171 ms，
    再建 4090 個鍵要 586 ms，共約 757 ms——而那只是單一 bridge 單一 uplink 的成本，
    多 bridge 會累加成數秒。對帳實際只需查 guest 用到的那十幾個 VLAN。

``expand_vlan_list()`` 仍然保留，但它的用途是**替範圍比對背書**：兩份獨立實作對
同一組輸入必須給出相同判斷。單靠一份實作自己驗自己沒有意義。
"""

import re

from . import STATUS_OK, default_run, parsed_result, run_command

TAG_UNTAGGED = "u"
TAG_TAGGED = "t"

PORT_GUEST = "guest"
PORT_BRIDGE = "bridge"
PORT_UPLINK = "uplink"

# PVE 動態產生的 guest 介面。字尾必須接數字，否則 `tapioca0` 這種名字也會中。
_GUEST_IFACE_RE = re.compile(r"^(?:tap|veth|fwbr|fwpr|fwln)[0-9]")

_DIGITS_RE = re.compile(r"^[0-9]+$")
_RANGE_RE = re.compile(r"^([0-9]+)-([0-9]+)$")

# 判斷 token 是否為 VLAN ID MUST 用 ^[0-9]+$ 而不是 str.isdigit()：後者對全形數字
# 與上標數字都回 True（'１'、'²'），而 int('²') 會直接拋 ValueError。
_LEADING_DIGIT_RE = re.compile(r"^[0-9]")


# ── VLAN 清單的三種運算 ────────────────────────────────────────────────


def _parse_item(item):
    """把 ``100u`` / ``100t`` / ``100`` 解析成 (vid, tag)；其他形態回 None。

    兩種形態都要支援：顯示走帶標記的 ``100t``，對帳走去掉標記後的純數字 ``100``。
    抽成函式是因為主迴圈與內層前瞻要做同一件事，各寫一次必然會漏掉其中一邊。
    """
    text = (item or "").strip()
    if not text:
        return None
    tail = text[-1:]
    if tail in (TAG_UNTAGGED, TAG_TAGGED):
        head = text[:-1]
        if _DIGITS_RE.match(head):
            return int(head), tail
        return None
    if _DIGITS_RE.match(text):
        return int(text), ""
    return None


def compress_vlan_list(text):
    """把逐個列出的 VLAN 壓回範圍表示。

    只有「連續且標記相同」才合併：``1u,2u,3t`` 壓成 ``1-2u,3t``，不會把 3t 併進去。
    已經是範圍的 token（``2-4090t``）解析不出來，原樣保留並中斷合併鏈。
    """
    items = (text or "").split(",")
    out = []
    index = 0
    total = len(items)
    while index < total:
        current = _parse_item(items[index])
        if current is None:
            # 其他形態（例如已經是範圍）原樣保留
            out.append(items[index].strip())
            index += 1
            continue

        start, tag = current
        end = start
        probe = index + 1
        while probe < total:
            nxt = _parse_item(items[probe])
            if nxt is None or nxt[1] != tag or nxt[0] != end + 1:
                break
            end = nxt[0]
            probe += 1

        if end > start:
            out.append("%d-%d%s" % (start, end, tag))
        else:
            out.append("%d%s" % (start, tag))
        index = probe
    return ",".join(out)


def expand_vlan_list(text):
    """展開 ``100,200-203,300`` → [100, 200, 201, 202, 203, 300]。

    MUST NOT 用於對帳（成本見模組說明），它的職責是替 vlan_in_list() 背書。
    """
    out = []
    for part in (text or "").split(","):
        part = re.sub(r"\s+", "", part)
        if not part:
            continue
        found = _RANGE_RE.match(part)
        if found:
            # start > end 時 range 為空，與 bash 版的 for 迴圈一致
            out.extend(range(int(found.group(1)), int(found.group(2)) + 1))
        elif _DIGITS_RE.match(part):
            out.append(int(part))
    return out


def vlan_in_list(vid, text):
    """判斷某個 VLAN 是否落在清單內；清單可含 ``100`` 或 ``2-4090`` 這類範圍。

    與 bash 版的差異（刻意）：單值比對走數值而非字串，所以 ``0100`` 與 ``100``
    視為同一個 VLAN。範圍那一側本來就是數值比較，兩側判準不一致才是缺陷。
    """
    probe = re.sub(r"\s+", "", str(vid))
    if not _DIGITS_RE.match(probe):
        return False
    value = int(probe)

    for part in (text or "").split(","):
        part = re.sub(r"\s+", "", part)
        if not part:
            continue
        found = _RANGE_RE.match(part)
        if found:
            if int(found.group(1)) <= value <= int(found.group(2)):
                return True
        elif _DIGITS_RE.match(part) and int(part) == value:
            return True
    return False


def strip_tags(text):
    """去掉 token 尾端的 u/t 標記：``1u,100t`` → ``1,100``。

    只剝 token 尾端的標記，範圍寫法 ``200-203t`` 會變成 ``200-203`` 而不被拆開。
    """
    return re.sub(r"[ut](?=,|$)", "", text or "")


# ── port 分類 ─────────────────────────────────────────────────────────


def is_guest_iface(name):
    """PVE 動態產生的 guest 介面（tap/veth/fwbr/fwpr/fwln）。"""
    return _GUEST_IFACE_RE.match(name or "") is not None


def port_kind(name, is_bridge=False):
    """分類 bridge port。

    is_bridge 由呼叫端提供（SysfsReader.is_bridge），這個模組不去碰 sysfs 路徑
    ——否則單元測試就得同時準備假 sysfs 與假 bridge 輸出。
    """
    if is_guest_iface(name):
        return PORT_GUEST
    if is_bridge:
        return PORT_BRIDGE
    return PORT_UPLINK


# ── bridge vlan show 解析 ─────────────────────────────────────────────


def parse_vlan_show(text):
    """解析 ``bridge vlan show`` 的縮排格式，回 {port: {vlans, pvid}}。

    該輸出是「首行帶 port 名，續行只有 VLAN」的格式，同一個 port 的 VLAN 會跨多行::

        port              vlan-id
        vmbr0             1 PVID Egress Untagged
                          100
                          200-203

    ★ 兩道防線都是必要的，且必須用「數字開頭的介面名」才區分得出來：

      防線一：port 名獨佔一行（VLAN 全在續行）時，rest MUST 清空。
      防線二：VLAN 欄位必須以數字開頭。

    介面名以字母開頭時防線二就擋掉了，兩道無從區分；只有 ``10gbe0`` 這種名字會讓
    防線一單獨現形——實測移除防線一時，字母開頭的樣本輸出完全不變。
    """
    ports = {}
    port = None
    vlans = []
    pvid = "-"
    first = True

    for line in (text or "").splitlines():
        if first:
            first = False
            if line.split()[:1] == ["port"]:
                continue

        if not line.strip():
            continue

        if not line[:1].isspace():
            if port is not None:
                ports[port] = {"vlans": ",".join(vlans), "pvid": pvid}
            fields = line.split()
            port = fields[0]
            vlans = []
            pvid = "-"
            # 沒有第二欄時 rest MUST 清空，否則 port 名會被當成 VLAN ID 收進清單
            head = re.match(r"^\S+\s+", line)
            rest = line[head.end():] if head else ""
        else:
            rest = line.strip()

        if not rest.strip():
            continue

        vid = rest.split()[0]
        if not _LEADING_DIGIT_RE.match(vid):
            continue
        if "PVID" in rest:
            pvid = vid
        vlans.append(vid + (TAG_UNTAGGED if "Untagged" in rest else TAG_TAGGED))

    if port is not None:
        ports[port] = {"vlans": ",".join(vlans), "pvid": pvid}
    return ports


class BridgeReader:
    """讀 ``bridge vlan show``；run_fn 可替換，避免測試依賴主機是否安裝 iproute2。"""

    def __init__(self, run_fn=None):
        self.run_fn = run_fn if run_fn is not None else default_run
        self._command_cache = {}
        self._parsed_cache = None

    def _command(self, argv):
        key = tuple(argv)
        if key not in self._command_cache:
            self._command_cache[key] = run_command(self.run_fn, argv)
        return self._command_cache[key]

    def vlan_show(self):
        """★ 解析結果也要快取，不能只快取指令輸出。

        每個 port 都會問一次 port_vlans()，若每次都重新解析，2-4090 的規模下就是
        逐 port 重跑一次上千行的解析。bash 版 v02.000.000 正是在這裡踩過——當時
        以為加了快取，實際上 $( ) 的 subshell 讓寫入不回傳，ethtool 仍被呼叫 6 次。
        所以本模組的測試 MUST 數 run_fn 的呼叫次數，而不是只看結果對不對。
        """
        if self._parsed_cache is None:
            self._parsed_cache = parsed_result(
                self._command(["bridge", "vlan", "show"]), parse_vlan_show)
        return self._parsed_cache

    def ports(self):
        result = self.vlan_show()
        return list(result["data"].keys()) if result["data"] else []

    def _entry(self, port):
        data = self.vlan_show()["data"] or {}
        return data.get(port)

    def port_vlans(self, port):
        """顯示用：保留 u/t 標記並壓成範圍。port 不存在時回 None。"""
        entry = self._entry(port)
        if entry is None:
            return None
        return compress_vlan_list(entry["vlans"])

    def port_pvid(self, port):
        entry = self._entry(port)
        if entry is None:
            return None
        return entry["pvid"]

    def allowed_vlans(self, port):
        """對帳用：先去標記再壓縮，讓 1u,2t 這種相鄰但標記不同的也能併成 1-2。"""
        entry = self._entry(port)
        if entry is None:
            return None
        return compress_vlan_list(strip_tags(entry["vlans"]))

    def vlan_allowed(self, port, vid):
        """★ port 不存在時回 False——「這個 port 沒有放行任何 VLAN」與「查不到這個
        port」在對帳語意上都不該算放行。要區分請先用 allowed_vlans() 判 None。
        """
        allowed = self.allowed_vlans(port)
        if allowed is None:
            return False
        return vlan_in_list(vid, allowed)

    def available(self):
        return self.vlan_show()["status"] == STATUS_OK
