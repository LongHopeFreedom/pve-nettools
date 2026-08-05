# [CHANGE] 2026-08-02 以單一目錄承載選單射程，避免互動檢視與報告各自維護清單而漂移。
"""應用層的區段目錄、共用 Reader 組與輸出環境。"""

import os

from .collect.bond import BondReader
from .collect.bridge import BridgeReader
from .collect.cluster import ClusterReader
from .collect.ethtool import EthtoolReader
from .collect.firewall import FirewallReader
from .collect.ip import IpReader
from .collect.lldp import LldpReader
from .collect.netconf import NetconfReader
from .collect.ovs import OvsReader
from .collect.pve import GuestConfReader
from .collect.sdn import SdnReader
from .collect.sysctl import SysctlReader
from .collect.sysfs import SysfsReader
from .collect.textconf import TextConfReader
from .render import (AutostartSection, BondSection, BridgeSection,
                     BridgeVlanSection, ConntrackSection, CorosyncSection,
                     FirewallSection, GuestSection, HealthSection,
                     IpRoutingSection, LldpSection, ModuleSection,
                     NeighSection, NicSection, OvsSection, Palette,
                     PersistentSection, REPORT_WIDTH, RenderContext,
                     RingOffloadSection, SdnSection, SysctlSection,
                     VlanReconcileSection,
                     VlanSubSection, term_width)
from .render.iprouting import DEFAULT_LIST_LIMIT
from .util import positive_int


class MenuEntry(object):
    """目錄裡的一項；factory 為 None 表示未實作。"""

    def __init__(self, number, group, title_key, todo, factory):
        self.number = number
        self.group = group
        self.title_key = title_key
        self.todo = todo
        self.factory = factory


def _action(_readers):
    """讓已實作的互動動作可依 factory 判準留在目錄中。"""
    return None


# [CHANGE] 2026-08-02 未完成項也留在 SSOT，因為靜默刪除會把「沒做」偽裝成「已涵蓋」。
MENU_ENTRIES = (
    MenuEntry(0, None, "menu.exit", None, _action),
    # [CHANGE] 2026-08-02 待辦 #26：不再傳 r.netconf——NicSection 回到與 bash 版
    # 等價的 11 欄後，不需要讀 /etc/network/interfaces。r.netconf 仍由第 24 項
    # AutostartSection 使用，Readers 不必改。
    MenuEntry(1, "phys", "menu.nic_status", None,
              lambda r: NicSection(r.sysfs, r.ethtool,
                                   sample_seconds=r.sample_seconds)),
    MenuEntry(2, "phys", "menu.nic_health", None,
              lambda r: HealthSection(r.sysfs, r.ethtool)),
    # [CHANGE] 2026-08-02 待辦 #17：第 3 項實作完成，todo 欄轉為 None。
    MenuEntry(3, "phys", "menu.nic_modules", None,
              lambda r: ModuleSection(r.sysfs, r.ethtool)),
    MenuEntry(4, "phys", "menu.nic_led", None, _action),
    # [CHANGE] 2026-08-02 待辦 #16／#17／#18：選單 5～17 十一項實作完成，
    # todo 欄一併轉為 None。規格真值＝bash 版對應的 render_* 函式。
    MenuEntry(5, "l2", "menu.bond", None,
              lambda r: BondSection(r.bond, r.sysfs, r.ip)),
    MenuEntry(6, "l2", "menu.bridge", None,
              lambda r: BridgeSection(r.sysfs, r.ip)),
    MenuEntry(7, "l2", "menu.ovs", None,
              lambda r: OvsSection(r.ovs, r.sysfs, r.ip)),
    MenuEntry(8, "l2", "menu.vlan_sub", None,
              lambda r: VlanSubSection(r.ip, r.sysfs)),
    MenuEntry(9, "l2", "menu.bridge_vlan", None,
              lambda r: BridgeVlanSection(r.bridge, r.sysfs)),
    MenuEntry(10, "l2", "menu.guest_nics", None,
              lambda r: GuestSection(r.guest, r.sysfs)),
    MenuEntry(11, "l2", "menu.vlan_reconcile", None,
              lambda r: VlanReconcileSection(r.bridge, r.sysfs, r.guest)),
    MenuEntry(12, "l3", "menu.ip_routing", None,
              lambda r: IpRoutingSection(r.ip, r.textconf,
                                         list_limit=r.list_limit)),
    MenuEntry(13, "l3", "menu.sdn", None, lambda r: SdnSection(r.sdn)),
    MenuEntry(14, "l3", "menu.corosync", None,
              lambda r: CorosyncSection(r.cluster)),
    MenuEntry(15, "l3", "menu.firewall", None,
              lambda r: FirewallSection(r.firewall, r.pveconf)),
    MenuEntry(16, "l3", "menu.lldp", None, lambda r: LldpSection(r.lldp)),
    MenuEntry(17, "l3", "menu.persistent", None,
              lambda r: PersistentSection(r.textconf, r.netconf)),
    MenuEntry(18, "overall", "menu.view_all", None, _action),
    MenuEntry(19, "overall", "menu.full_report", None, _action),
    MenuEntry(20, "overall", "menu.self_test", None, _action),
    MenuEntry(21, "added", "menu.sysctl", None,
              lambda r: SysctlSection(r.sysctl)),
    MenuEntry(22, "added", "menu.conntrack", None,
              lambda r: ConntrackSection(r.sysctl)),
    MenuEntry(23, "added", "menu.neigh", None,
              lambda r: NeighSection(r.sysctl)),
    MenuEntry(24, "added", "menu.autostart", None,
              lambda r: AutostartSection(r.netconf, r.sysfs)),
    # [CHANGE] 2026-08-04 待辦 #13：編號 25，不是 26。既有編號是 0..24（共 25 個
    #          條目），所以新項目**是第 26 個條目、編號 25**。委派規格誤寫成 26，
    #          結果選單缺號、從 24 直接跳 26——那是使用者看得到的。
    MenuEntry(25, "added", "menu.ring_offload", None,
              lambda r: RingOffloadSection(r.sysfs, r.ethtool)),
)

INTERACTIVE_NUMBERS = frozenset((4,))
ACTION_NUMBERS = frozenset((0, 18, 19, 20))


def entry_by_number(number):
    for entry in MENU_ENTRIES:
        if entry.number == number:
            return entry
    return None


def implemented_entries():
    return tuple(entry for entry in MENU_ENTRIES if entry.factory is not None)


def unimplemented_entries():
    return tuple(entry for entry in MENU_ENTRIES if entry.factory is None)


def report_entries():
    """從即時目錄推導報告項，讓後續新增的非互動區段自動納入。"""
    return tuple(entry for entry in MENU_ENTRIES
                 if entry.factory is not None
                 and entry.number not in INTERACTIVE_NUMBERS
                 and entry.number not in ACTION_NUMBERS)


class Readers(object):
    """一次建好並共用所有 Reader；回主選單時可整組重建以清除快取。"""

    def __init__(self, env=None):
        self.env = os.environ if env is None else env
        configured = positive_int(self.env.get("SAMPLE_SECONDS"))
        self.sample_seconds = 3 if configured is None else configured
        # [CHANGE] 2026-08-02 選單第 12 項：LIST_LIMIT（路由／鄰居清單上限）。
        # ★ 上一棒（待辦 #24）把 LIST_LIMIT 從 `--help` 拿掉，因為當時全套件
        #   零實作——說明文件承諾了不存在的功能，只會以「使用者設了沒反應」現身。
        #   本項實作之後它不再是謊話，故一併加回 usage；usage 對帳守門員是**雙向**
        #   差集，這裡一讀而 usage 不列，那道測試就會紅。
        limit = positive_int(self.env.get("LIST_LIMIT"))
        self.list_limit = DEFAULT_LIST_LIMIT if limit is None else limit
        self.reset_caches()

    def reset_caches(self):
        """重建 Reader，避免現場狀態變化被上一輪快取遮蔽。"""
        self.sysfs = SysfsReader()
        self.ethtool = EthtoolReader()
        self.netconf = NetconfReader()
        self.guest = GuestConfReader()
        self.sysctl = SysctlReader()
        self.bridge = BridgeReader()
        # [CHANGE] 2026-08-02 選單 5～17 十一項的供料。
        self.ip = IpReader()
        self.bond = BondReader(sysfs_reader=self.sysfs)
        self.ovs = OvsReader()
        self.lldp = LldpReader()
        self.firewall = FirewallReader()
        self.cluster = ClusterReader()
        self.sdn = SdnReader()
        # ★ 兩個 TextConfReader 是刻意的，不是複本：
        #     pveconf  根為 PVE_CONF_ROOT，給要用 path() 組相對路徑的（選單 15）
        #     textconf 只讀絕對路徑（/etc/resolv.conf、/etc/hosts、interfaces）
        #   共用一個實例也能跑（read_lines 吃絕對路徑時不看 root），但那會讓
        #   「這個 reader 的根是什麼」在呼叫端變成需要推理的事。
        self.pveconf = TextConfReader()
        self.textconf = TextConfReader()


def build_context(env=None, report_mode=False):
    """建立終端或固定、無色的報告輸出環境。"""
    if report_mode:
        return RenderContext(REPORT_WIDTH, Palette(enabled=False))
    return RenderContext(term_width(env=env), Palette.auto())
