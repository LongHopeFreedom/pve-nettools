# [CHANGE] 2026-08-02 新增：Linux Bridge 輸出區段（選單第 6 項，待辦 #16）。
"""逐座 Linux Bridge 的設定與狀態。

規格真值＝bash `render_bridges`（`old/pve-network-audit.sh:1063-1105`）。
欄位、順序、鍵欄寬皆逐欄對齊，差異一律具名。

★ 本區段**沒有表格版**，`table()` 回 None。bash 這一段只有逐座區塊，沒有
  `render_bridges_table`——造一個表格出來就不是「畫面一樣」了。
"""

from ..i18n import t
from .base import (BLOCK_RULE_WIDTH, Section, block_rule, kv, kv_coloured,
                   note)

__all__ = ["BridgeSection", "vlan_protocol_key"]

# bash 的 kv() 是 pad(key, 16)。
KEY_WIDTH = 16

# bash vlan_protocol_name()（1055-1061 行）：只認這兩種，其餘原樣印出。
# ★ 大小寫兩種寫法都要認——bash 的 case 明寫 `0x88a8|0x88A8`，而 sysfs 實際
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

    def __init__(self, sysfs_reader, ip_reader):
        self.sysfs = sysfs_reader
        self.ip = ip_reader

    def build(self):
        rows = []
        for name in self.sysfs.bridges():
            ports = self.sysfs.bridge_ports(name)
            rows.append({
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
            })
        return rows

    def table(self, data, ctx):
        return None

    def blocks(self, data, ctx):
        lines = []
        for row in data:
            lines.append(block_rule(BLOCK_RULE_WIDTH))
            lines.append(kv_coloured(t("bridge.label"), row["name"], ctx.palette,
                                     key_colour="bold", value_colour="cyan",
                                     key_width=KEY_WIDTH))
            # bash：${ports:-無}——空字串才退成「無」，這是 kv 的預設值語意。
            lines.append(kv(t("bridge.ports"), row["ports"] or t("app.none"),
                            key_width=KEY_WIDTH))
            # ★ IPv4／IPv6／MTU／狀態四個標籤在 bash 的 render_bonds、
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

            # ★ bash 對 STP 用的是「啟用／停用」而非「是／否」，兩者在 i18n 是
            #   不同的 key。照抄成 app.yes/app.no 會讓畫面與 bash 不同。
            lines.append(kv(t("bridge.stp"),
                            t("app.enabled") if row["stp"] else t("app.disabled"),
                            key_width=KEY_WIDTH))
            lines.append("")
        lines.append(block_rule(BLOCK_RULE_WIDTH))
        return lines

    @staticmethod
    def _protocol_text(raw):
        key = vlan_protocol_key(raw)
        if key is not None:
            return t(key)
        # bash：`*) echo "${1:-N/A}"` ⇒ 未知值原樣印，空值才是 N/A。
        return raw if raw else t("app.na")

    def empty_lines(self, data, ctx):
        return [note(t("bridge.none"), ctx.palette)]
