# [CHANGE] 2026-07-31 新增：guest conf 解析（待辦 #4），並補上 link_down / rate / model
#          三個 bash 版沒有的欄位（i18n 的 guest.linkdown / guest.rate / guest.model 已備）。
"""從 /etc/pve 讀 VM / CT 的網卡設定。

PVE 的 guest 介面命名：VM = ``tap<vmid>i<n>``、CT = ``veth<vmid>i<n>``。啟用
firewall=1 時實際接上 bridge 的是 ``fwpr<vmid>p<n>``，guest 端接 ``fwbr<vmid>i<n>``。

★ 這個模組最容易寫錯的三件事，每一件的共通點都是「在真實資料上永遠是對的」：

1. **快照區段 MUST 截斷。** conf 檔在第一個 ``[<快照名>]`` 之後是快照當下的設定
   副本，不是目前設定。不截斷的話，一台開過快照的 guest 會多出好幾筆網卡，bridge
   與 tag 都是舊值——它讀起來完全像一筆正常資料，報告上沒有任何跡象說它是歷史。
   判準是**行首的 ``[``**，不是字面的 ``[snapshot]``：區段標頭寫的是快照名稱
   （``[before-upgrade]``），字面比對只在快照剛好取名 snapshot 時才生效。

2. **guest 名稱 MUST 先掃完整份 body 再取。** PVE 產生的 conf 是照 key 字母排序，
   ``name`` / ``hostname`` 都排在 ``net0`` 前面，所以「邊掃邊填」在真機上永遠正確；
   一旦有人手動編輯把 name 移到後面，名稱就整欄變空。這裡刻意分兩趟。

3. **型號那一組 k=v。** VM 的 MAC 藏在「型號當 key」的位置（``virtio=BC:24:11:…``），
   CT 則是固定的 ``hwaddr=``。bash 版用型號白名單（virtio|e1000|vmxnet3|…）比對，
   那是拿「形態列舉」代替「性質」：PVE 之後多一種型號，MAC 與型號就會整欄變空，而
   白名單自己不會有任何測試變紅。這裡改問性質——**value 是不是一個 MAC**——那麼它的
   key 就是型號。KNOWN_PARAM_KEYS 只用來排除已知的非型號參數，MUST NOT 反過來寫成
   型號白名單。

★ 刻意不做快取：guest conf 是幾十個小檔，重讀便宜，而盤查期間 guest 可能被改。
  bridge.py 那種雙層快取在這裡只會讓「某一層失效」變得沒有任何觀測量會變。
"""

import os
import re

from . import STATUS_EMPTY, STATUS_OK, STATUS_UNAVAILABLE

DEFAULT_ROOT = "/etc/pve"

KIND_VM = "VM"
KIND_CT = "CT"

# (子目錄, 類型, 介面前綴)。這只是列舉順序，最終輸出一律重新排序。
SOURCES = (
    ("qemu-server", KIND_VM, "tap"),
    ("lxc", KIND_CT, "veth"),
)

CONF_SUFFIX = ".conf"

# 「全為 ASCII 數字」。MUST NOT 用 str.isdigit() 代替：它對上標與全形數字也回 True
# （"²".isdigit() 是 True 而 int("²") 直接拋 ValueError），排序與檔名過濾都會炸。
_DIGITS_RE = re.compile(r"^[0-9]+$")
_SECTION_RE = re.compile(r"^\[")
_NET_RE = re.compile(r"^(net[0-9]+)\s*:(.*)$")
_NAME_RE = re.compile(r"^(?:name|hostname)\s*:(.*)$")
_NETID_NUM_RE = re.compile(r"^net([0-9]+)$")
_MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}$")

# 明確以 MAC 為值的 key。CT 用 hwaddr，macaddr 是部分 PVE 版本的別名。
MAC_KEYS = frozenset(("hwaddr", "macaddr"))

# 已知的網卡參數 key——它們絕不是型號。這份表只用來「排除」（理由見模組說明）。
KNOWN_PARAM_KEYS = frozenset((
    "bridge", "tag", "trunks", "firewall", "link_down", "rate", "queues",
    "mtu", "name", "type", "ip", "ip6", "gw", "gw6",
)) | MAC_KEYS


# ── 文字解析 ──────────────────────────────────────────────────────────


def strip_snapshots(text):
    """只留下第一個區段標頭之前的內容，也就是 guest 目前的設定。

    沒有區段標頭時原樣回傳。回傳字串而非行陣列，是為了讓這一層可以單獨被測。
    """
    kept = []
    for line in (text or "").splitlines():
        if _SECTION_RE.match(line):
            break
        kept.append(line)
    return "\n".join(kept)


def parse_kv(params):
    """把 ``virtio=BC:24:11:…,bridge=vmbr0,tag=100`` 拆成 [(key, value), …]。

    保留順序與重複的 key：要取哪一個由呼叫端決定（bash 版取後者，這裡照舊），
    拆解這一層不該先幫它決定。

    與 bash 版的差異（刻意）：這裡對 key 與 value 都做 strip()。bash 的
    ``${params# }`` 只去掉一個前導空白，``net0:  virtio=…``（兩個空白）會讓 key
    變成 " virtio" 而整條 case 比對失效，MAC 與型號同時變空。PVE 自己產生的 conf
    一律是單一空白，所以那個缺陷只有手動編輯過的檔才踩得到。
    """
    pairs = []
    for item in (params or "").split(","):
        item = item.strip()
        if not item:
            continue
        if "=" in item:
            key, value = item.split("=", 1)
            pairs.append((key.strip(), value.strip()))
        else:
            pairs.append((item, ""))
    return pairs


def is_mac(value):
    """六組冒號分隔的十六進位數對。用來認出「型號＝MAC」的那一組 k=v。"""
    return _MAC_RE.match(value or "") is not None


def parse_net_value(params):
    """解析 ``net<N>:`` 後面的參數字串，回傳這張網卡的欄位。

    沒出現的欄位一律 None（旗標則為 False），不用空字串——「conf 裡沒寫」與
    「寫了空值」在報告上都顯示成 ``-``，但只有 None 能讓測試分辨解析器有沒有做事。
    """
    nic = {
        "model": None,
        "mac": None,
        "bridge": None,
        "tag": None,
        "mtu": None,
        "rate": None,
        "firewall": False,
        "link_down": False,
    }
    for key, value in parse_kv(params):
        if key == "bridge":
            nic["bridge"] = value or None
        elif key == "tag":
            nic["tag"] = value or None
        elif key == "mtu":
            nic["mtu"] = value or None
        elif key == "rate":
            nic["rate"] = value or None
        elif key == "firewall":
            nic["firewall"] = value == "1"
        elif key == "link_down":
            nic["link_down"] = value == "1"
        elif key in MAC_KEYS:
            nic["mac"] = value or None
        elif key not in KNOWN_PARAM_KEYS and is_mac(value):
            nic["model"] = key
            nic["mac"] = value
    return nic


def guest_name(lines):
    """VM 取 ``name:``、CT 取 ``hostname:``，以先出現者為準；都沒有則 None。

    值用 split(":", 1) 取，不用 bash 的 ``-F': *'``——後者把每一個 ``: `` 都當
    分隔符，名稱裡含冒號時會被截掉後半。
    """
    for line in lines:
        found = _NAME_RE.match(line)
        if found:
            return found.group(1).strip() or None
    return None


def netid_index(netid):
    """``net10`` → 10。排序用；認不出來的排在最前面，讓它在報告上顯眼。"""
    found = _NETID_NUM_RE.match(netid or "")
    return int(found.group(1)) if found else -1


def guest_iface(prefix, vmid, netid):
    """``tap`` + 100 + ``net0`` → ``tap100i0``。

    前導零照 bash 版保留（``net007`` → ``…i007``）：那是 conf 寫成什麼就是什麼，
    正規化過的名字反而對不上 sysfs 裡真正存在的介面。
    """
    return "%s%si%s" % (prefix, vmid, netid[len("net"):])


def parse_guest_conf(text, vmid, kind, prefix):
    """解析一份 guest conf，回傳它的網卡清單（未排序）。"""
    lines = strip_snapshots(text).splitlines()
    name = guest_name(lines)

    nics = []
    for line in lines:
        found = _NET_RE.match(line)
        if not found:
            continue
        netid = found.group(1)
        nic = parse_net_value(found.group(2))
        nic["vmid"] = vmid
        nic["kind"] = kind
        nic["name"] = name
        nic["netid"] = netid
        nic["iface"] = guest_iface(prefix, vmid, netid)
        nics.append(nic)
    return nics


def sort_nics(nics):
    """依 vmid 數值、再依 net 編號數值排序（bash 的 ``sort -k1,1n -k4,4V``）。

    第三個判準 kind 是 bash 沒有的：VM 與 CT 的 vmid 在 PVE 是全域唯一，撞號本來
    就不該發生，但真撞上時兩筆的前兩個 key 會完全相同，輸出順序就變成看檔案列舉
    順序——那會讓同一台主機跑兩次得到不同報告。寧可決定性地排。
    """
    return sorted(nics, key=lambda n: (n["vmid"], netid_index(n["netid"]), n["kind"]))


# ── 檔案來源 ──────────────────────────────────────────────────────────


class GuestConfReader(object):
    """讀 /etc/pve 下的 guest 設定。root 可替換，讓測試指向 fixture。"""

    def __init__(self, root=None):
        self.root = root or os.environ.get("PVE_CONF_ROOT") or DEFAULT_ROOT

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    def is_pve_host(self):
        """qemu-server 與 lxc 兩個目錄一個都沒有，就不是 PVE 主機。

        用 any() 而非 all()：只跑 CT 的主機不會有 qemu-server 目錄，反之亦然。
        """
        return any(os.path.isdir(self.path(sub)) for sub, _, _ in SOURCES)

    def conf_files(self):
        """列出 (路徑, vmid, 類型, 介面前綴)。

        檔名的 vmid MUST 全為數字：``/etc/pve/qemu-server`` 底下還會有備份與暫存
        （``100.conf.tmp.1234``、編輯中的 ``.100.conf.swp``），把它們一起解析會憑空
        生出不存在的 guest。
        """
        found = []
        for sub, kind, prefix in SOURCES:
            directory = self.path(sub)
            try:
                entries = sorted(os.listdir(directory))
            except OSError:
                continue
            for entry in entries:
                if not entry.endswith(CONF_SUFFIX):
                    continue
                vmid = entry[:-len(CONF_SUFFIX)]
                if not _DIGITS_RE.match(vmid):
                    continue
                full = os.path.join(directory, entry)
                if not os.path.isfile(full):
                    continue
                found.append((full, int(vmid), kind, prefix))
        return found

    def read_conf(self, path):
        """讀一份 conf。errors="replace"：guest 名稱可能是任何編碼的位元組，
        一台名字壞掉的 VM 不該讓整份盤查中斷。"""
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()

    def nics(self):
        """回傳 {status, nics, unreadable, error}。

        status 的分界（沿用 collect 的三態，MUST NOT 合併）：

          ok          有讀到網卡
          empty       目錄在、檔也讀得到，但沒有任何已設定網卡的 guest
          unavailable 不是 PVE 主機，或該讀的 conf 一份都讀不到

        ★ 最後那一條是重點：讀不到的 conf 若只是靜默跳過，「全部讀不到」會長得跟
          「這台主機沒有 guest」一模一樣——一份漏掉整個機房的報告，通篇沒有一個字
          說它漏了。所以讀失敗的檔一律進 unreadable，而且在 nics 為空時把狀態升成
          unavailable。

        ★ nics 非空、unreadable 也非空＝部分成功。此時 status 是 ok，**render 層
          MUST 把 unreadable 揭露出來**，否則使用者會把一份殘缺的表當成全集。

        error 放的是事實（路徑、OS 錯誤原文），不是報告措辭；要給使用者看的句子
        由 render 以 i18n 產生（guest.none 等）。
        """
        if not self.is_pve_host():
            return {
                "status": STATUS_UNAVAILABLE,
                "nics": [],
                "unreadable": [],
                "error": "%s 下沒有 qemu-server 或 lxc" % self.root,
            }

        nics = []
        unreadable = []
        for path, vmid, kind, prefix in self.conf_files():
            try:
                text = self.read_conf(path)
            except OSError as exc:
                unreadable.append({"path": path, "error": str(exc)})
                continue
            nics.extend(parse_guest_conf(text, vmid, kind, prefix))

        nics = sort_nics(nics)
        if nics:
            status = STATUS_OK
        elif unreadable:
            status = STATUS_UNAVAILABLE
        else:
            status = STATUS_EMPTY

        error = None
        if unreadable and not nics:
            error = "；".join("%s：%s" % (u["path"], u["error"]) for u in unreadable)

        return {
            "status": status,
            "nics": nics,
            "unreadable": unreadable,
            "error": error,
        }

    # ── 對帳原語（待辦 #4 之後由 bridge.py 組合成 VLAN 對帳）──────────

    def guest_vlans(self, nics=None):
        """回傳 {bridge 名稱: 已排序的 VLAN 清單}，只算真的設了 tag 的網卡。

        給「7. VLAN 對帳」用：guest 要求的 VLAN 是否落在 bridge 的 allowed 清單裡。
        tag 非數字時原樣留著——bridge.vlan_allowed() 對非數字回 False，那正是對帳
        該給的答案（設定有問題），在這裡先丟掉反而讓它從報告上消失。

        nics 可傳入既有的清單，避免呼叫端已經拿過一次還要再讀一輪磁碟。
        """
        if nics is None:
            nics = self.nics()["nics"]

        table = {}
        for nic in nics:
            if not nic["bridge"] or not nic["tag"]:
                continue
            table.setdefault(nic["bridge"], [])
            if nic["tag"] not in table[nic["bridge"]]:
                table[nic["bridge"]].append(nic["tag"])
        # 數字在前依數值排、非數字在後依字面排。兩組的 key 型別各自一致，
        # 不會出現 int 與 str 相比的 TypeError。
        for bridge in table:
            table[bridge].sort(
                key=lambda t: (0, int(t), "") if _DIGITS_RE.match(t) else (1, 0, t))
        return table
