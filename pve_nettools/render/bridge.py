# [CHANGE] 2026-08-02 新增：Linux Bridge 輸出區段（選單第 6 項）。
"""逐座 Linux Bridge 的設定與狀態。

規格真值＝bash `render_bridges`（`old/pve-network-audit.sh:1063-1105`）。
欄位、順序、鍵欄寬皆逐欄對齊，差異一律註明。

本區段**沒有表格版**，`table()` 回 None。bash 這一段只有逐座區塊，沒有
  `render_bridges_table`——造一個表格出來就不是「畫面一樣」了。

# [CHANGE] 2026-10-08 v03.022.000：互動選單（zoned=True）每座橋接分上下兩段——上段「虛擬網卡資訊」
#   （橋接自身資訊＋非客體機成員）、下段「客體機資訊」（VM 區／LXC 區）。完整報告走預設的舊版面。
# [CHANGE] 2026-10-08 v03.022.001：互動畫面（zoned=True）不列「客體機管線橋接」（fwbrNNNiM，PVE 為開防火牆
#   的客體機網卡動態建立）；判斷沿用 is_guest_iface。隱藏不靜默：末尾印「已隱藏 N 座」，N=0 不印；
#   隱藏後無橋接可列時，畫面改印 bridge.only_hidden（與 bridge.none 不同）。完整報告（zoned=False）照列不動。
"""

from ..collect import STATUS_UNAVAILABLE
from ..collect.bridge import is_guest_iface
from ..i18n import t
from .base import (BLOCK_RULE_WIDTH, Section, block_rule, kv, kv_coloured,
                   note, subsection)
from .guest import GuestSection

__all__ = ["BridgeSection", "vlan_protocol_key"]

# bash 的 kv() 是 pad(key, 16)。
KEY_WIDTH = 16

# bash vlan_protocol_name()（1055-1061 行）：只認這兩種，其餘原樣印出。
# 大小寫兩種寫法都要認——bash 的 case 明寫 `0x88a8|0x88A8`，而 sysfs 實際
#   輸出哪一種取決於核心版本。只認一種會讓 QinQ 環境印出原始的十六進位值。
_PROTOCOL_KEYS = {
    "0x8100": "bridge.proto_dot1q",
    "0x88a8": "bridge.proto_qinq",
    "0x88A8": "bridge.proto_qinq",
}


def vlan_protocol_key(raw):
    """把 sysfs 的 vlan_protocol 值轉成 i18n key；未知值回 None（由呼叫端原樣印）。"""
    return _PROTOCOL_KEYS.get(raw)


class BridgeSection(Section):
    """Linux Bridge 清單。"""

    # [CHANGE] 2026-10-08 v03.022.000：zoned=True ＝ 互動選單的上下兩段版面：
    #   上段「虛擬網卡資訊」＝橋接自身資訊＋非客體機成員；
    #   下段「客體機資訊」＝掛在這座橋接上的客體機（VM 區／LXC 區，口徑同選單 10）。
    # 預設 False ＝ 與舊版逐位元相同；完整報告走預設（已決定這一版報告輸出不動），
    #   只有互動選單的工廠傳 True（比照 v03.021.000 的選單 1／10）。
    def __init__(self, sysfs_reader, ip_reader, guest_reader=None, zoned=False):
        self.sysfs = sysfs_reader
        self.ip = ip_reader
        self.guest = guest_reader
        self.zoned = zoned
        # 下段的列建構、排序、欄位、分區與窄版區塊版全部借用選單 10 的實作，不另寫一份。
        self._guest_view = GuestSection(guest_reader, sysfs_reader, zoned=True)

    def build(self):
        """回 {"rows": 要列的橋接, "hidden": 被隱藏的客體機管線橋接數}。

        hidden 與 rows 在同一個迴圈裡數，所以「說明行的 N」與「實際被濾掉的橋接數」不可能不同；
          非 zoned（完整報告）hidden 恆為 0、rows 含全部橋接，輸出與舊版逐位元相同。
        """
        guest = self._guest_data() if self.zoned else None
        rows = []
        hidden = 0
        for name in self.sysfs.bridges():
            # [CHANGE] 2026-10-08 v03.022.001：互動畫面隱藏客體機管線橋接（fwbr），只計數、不丟棄訊息。
            if self.zoned and is_guest_iface(name):
                hidden += 1
                continue
            ports = self.sysfs.bridge_ports(name)
            if self.zoned:
                # 客體機管線介面（tap／veth／fwpr／fwln／fwbr）不進上段；判斷與選單 1 同一個函式。
                ports = [port for port in ports if not is_guest_iface(port)]
            row = {
                "name": name,
                # bash：find brif | sort -V | paste -sd ',' ⇒ 純逗號，無空白。
                "ports": ",".join(ports),
                "ipv4": self.ip.address_text(name, 4),
                "ipv6": self.ip.address_text(name, 6),
                "mtu": self.sysfs.mtu(name),
                "state": self.sysfs.operstate(name),
                "vlan_aware": self.sysfs.vlan_filtering(name),
                "vlan_protocol": self.sysfs.vlan_protocol(name),
                "default_pvid": self.sysfs.default_pvid(name),
                "stp": self.sysfs.stp_enabled(name),
            }
            if guest is not None:
                row["guest"] = {
                    "readable": guest["readable"],
                    "unreadable": guest["unreadable"],
                    "rows": [nic for nic in guest["rows"] if nic["bridge"] == name],
                }
            rows.append(row)
        return {"rows": rows, "hidden": hidden}

    def _guest_data(self):
        """讀一次設定檔，供所有橋接共用。

        readable=False（不是 PVE 主機，或設定檔一份都讀不到）與「讀到了但這座橋接沒有客體機」
          在畫面上必須不同——兩者都不能印成「0」或空白（比照選單 1 的客體網卡摘要）。
        """
        if self.guest is None:
            return {"readable": False, "unreadable": 0, "rows": []}
        result = self.guest.nics()
        if result.get("status") == STATUS_UNAVAILABLE:
            return {"readable": False, "unreadable": 0, "rows": []}
        data = self._guest_view.build_from(result)
        return {"readable": True, "unreadable": len(data["unreadable"]),
                "rows": data["rows"]}

    def table(self, data, ctx):
        return None

    def is_empty(self, data):
        # 只看 rows：「全被隱藏」也要走 empty_lines，才能印出與「沒有橋接」不同的畫面。
        return not data["rows"]

    def blocks(self, data, ctx):
        lines = []
        for row in data["rows"]:
            lines.append(block_rule(BLOCK_RULE_WIDTH))
            # [CHANGE] 2026-10-08 v03.022.000：互動版面在橋接自身資訊前加上段標題。
            if self.zoned:
                lines.extend(subsection(t("bridge.zone_virtual"), ctx.palette))
            lines.append(kv_coloured(t("bridge.label"), row["name"], ctx.palette,
                                     key_colour="bold", value_colour="cyan",
                                     key_width=KEY_WIDTH))
            # bash：${ports:-無}——空字串才退成「無」，這是 kv 的預設值語意。
            lines.append(kv(t("bridge.ports"), row["ports"] or t("app.none"),
                            key_width=KEY_WIDTH))
            # IPv4／IPv6／MTU／狀態四個標籤在 bash 的 render_bonds、
            #   render_bridges、render_ovs、render_vlan_subinterfaces 各重複一次。
            #   bash 每個函式各寫一份字面值，Python 這邊取共用 key——同一個標籤
            #   四份翻譯必然漂移，而漂移了不會有任何東西變紅。
            lines.append(kv(t("net.ipv4"), row["ipv4"], key_width=KEY_WIDTH))
            lines.append(kv(t("net.ipv6"), row["ipv6"], key_width=KEY_WIDTH))
            lines.append(kv(t("nic.mtu"), row["mtu"], key_width=KEY_WIDTH))
            lines.append(kv(t("net.state"), row["state"], key_width=KEY_WIDTH))

            if row["vlan_aware"]:
                lines.append(kv_coloured(t("bridge.vlan_aware"), t("app.yes"),
                                         ctx.palette, value_colour="green",
                                         key_width=KEY_WIDTH))
                lines.append(kv(t("bridge.vlan_proto"),
                                self._protocol_text(row["vlan_protocol"]),
                                key_width=KEY_WIDTH))
                # bash：read_sysfs 的預設值是 "N/A"，故讀不到時印 N/A 而非空白。
                lines.append(kv(t("bridge.default_pvid"),
                                row["default_pvid"] or t("app.na"),
                                key_width=KEY_WIDTH))
            else:
                lines.append(kv_coloured(t("bridge.vlan_aware"), t("app.no"),
                                         ctx.palette, value_colour="yellow",
                                         key_width=KEY_WIDTH))

            # bash 對 STP 用的是「啟用／停用」而非「是／否」，兩者在 i18n 是
            #   不同的 key。照抄成 app.yes/app.no 會讓畫面與 bash 不同。
            lines.append(kv(t("bridge.stp"),
                            t("app.enabled") if row["stp"] else t("app.disabled"),
                            key_width=KEY_WIDTH))
            lines.append("")
            # [CHANGE] 2026-10-08 v03.022.000：下段＝掛在這座橋接上的客體機。
            if self.zoned:
                lines.extend(subsection(t("bridge.zone_guest"), ctx.palette))
                lines.extend(self._guest_lines(row["guest"], ctx))
                lines.append("")
        lines.append(block_rule(BLOCK_RULE_WIDTH))
        # [CHANGE] 2026-10-08 v03.022.001：隱藏數 N>0 才印說明；N=0 完全不印。
        if data["hidden"]:
            lines.append(note(t("bridge.hidden_note", count=data["hidden"]), ctx.palette))
        return lines

    def _guest_lines(self, guest, ctx):
        """下段：這座橋接上的客體機。

        四種畫面互不相同：讀不到／無（含部分讀不到的附註）／只有一區／兩區。
        """
        if not guest["readable"]:
            return [note(t("bridge.guest_unreadable"), ctx.palette)]
        rows = guest["rows"]
        lines = []
        if not rows:
            lines.append(t("app.none"))
        else:
            for title_key, _none_key, zone_rows in GuestSection._zones({"rows": rows}):
                if lines:
                    lines.append("")
                lines.extend(subsection(t(title_key), ctx.palette))
                if zone_rows:
                    lines.extend(self._guest_view._zone_lines(
                        {"rows": zone_rows, "unreadable": []}, ctx))
                else:
                    lines.append(t("app.none"))
        if guest["unreadable"]:
            lines.append(note(t("bridge.guest_partial", count=guest["unreadable"]),
                              ctx.palette))
        return lines

    @staticmethod
    def _protocol_text(raw):
        key = vlan_protocol_key(raw)
        if key is not None:
            return t(key)
        # bash：`*) echo "${1:-N/A}"` ⇒ 未知值原樣印，空值才是 N/A。
        return raw if raw else t("app.na")

    def empty_lines(self, data, ctx):
        # [CHANGE] 2026-10-08 v03.022.001：只有被隱藏的橋接 ≠ 沒有橋接，兩種畫面必須不同。
        if data["hidden"]:
            return [note(t("bridge.only_hidden", count=data["hidden"]), ctx.palette)]
        return [note(t("bridge.none"), ctx.palette)]
