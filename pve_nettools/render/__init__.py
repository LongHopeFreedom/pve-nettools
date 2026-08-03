# [CHANGE] 2026-08-01 新增：render 子套件入口（待辦 #8 骨架）。
"""輸出層：把 collect 層的資料變成一份可讀的盤查報告。

分工：
  theme.py  顏色與終端寬度——「用哪一種版面」由這裡決定
  base.py   版面元件與 Section 基底——「同一份取值餵給兩種版面」由這裡保證

★ 本層**不做任何 I/O**：所有東西回傳 `list[str]`，由呼叫端決定要印到終端、交給
  pager 還是寫進報告檔。同一份輸出有三個去處，而報告檔的內容 MUST 與終端一致。

★ [CHANGE] 2026-08-02 上一段原文寫「本層不涵蓋 Bond／OVS／IP 路由／SDN／
  corosync／LLDP／VLAN 子介面，因為 collect 層沒有供料」。**七項連同其餘四項
  已全部實作**（待辦 #16／#17／#18），選單 5～17 不再有未實作項。
  ★ 這一段其實**有**人守（`test_U2`），而它守的是「docstring 有沒有具名那
    七項未涵蓋」——項目做完之後，那條判準所描述的世界就不存在了，於是它會
    紅在一個「已經修好」的事實上。判準跟著改成守仍然成立的性質（每個 bash
    盤查區段都有對應的 Section），而不是把 docstring 改回謊話讓它變綠。
"""

from .base import (
    RenderContext,
    Section,
    blank,
    header,
    kv,
    note,
    section,
    subsection,
    thin_hr,
)
from .theme import FALLBACK_WIDTH, REPORT_WIDTH, Palette, term_width
from .bridgevlan import BridgeVlanSection
from .guest import GuestSection
from .netconf import AutostartSection
from .nic import HealthSection, NicSection
# [CHANGE] 2026-08-02 待辦 #17：MUST 排在 .nic 之後——module 從 nic 取用
# 共用的媒介文字轉換，順序顛倒會是循環匯入。
from .module import ModuleSection
from .sysctl import ConntrackSection, NeighSection, SysctlSection
# [CHANGE] 2026-08-02 選單 5～17 十一項（待辦 #16／#17／#18）。
from .bond import BondSection
from .bridge import BridgeSection
from .corosync import CorosyncSection
from .firewall import FirewallSection
from .iprouting import IpRoutingSection
from .lldp import LldpSection
from .ovs import OvsSection
from .persistent import PersistentSection
from .sdn import SdnSection
from .vlanreconcile import VlanReconcileSection
from .vlansub import VlanSubSection

__all__ = [
    "AutostartSection",
    "BondSection",
    "BridgeSection",
    "BridgeVlanSection",
    "ConntrackSection",
    "CorosyncSection",
    "FirewallSection",
    "GuestSection",
    "HealthSection",
    "IpRoutingSection",
    "LldpSection",
    "ModuleSection",
    "NeighSection",
    "NicSection",
    "OvsSection",
    "PersistentSection",
    "SdnSection",
    "SysctlSection",
    "VlanReconcileSection",
    "VlanSubSection",
    "FALLBACK_WIDTH",
    "Palette",
    "REPORT_WIDTH",
    "RenderContext",
    "Section",
    "blank",
    "header",
    "kv",
    "note",
    "section",
    "subsection",
    "term_width",
    "thin_hr",
]
