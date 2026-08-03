# [CHANGE] 2026-08-02 新增：Open vSwitch 輸出區段（選單第 7 項，待辦 #16）。
"""OVS Bridge、Port 明細與 OVS Bond 狀態。

規格真值＝bash `render_ovs`（`old/pve-network-audit.sh:1109-1173`）。

★ 「沒有 OVS」有**三種**，它們給使用者的下一步完全不同，MUST NOT 合併：
    not_installed      去裝 openvswitch-switch
    ovsdb_unreachable  裝了但服務沒跑，去看 systemctl status
    no_bridges         都正常，只是這台沒建 OVS Bridge
  分辨的依據是 `collect.ovs` 的 `reason` 欄，而那一欄的判準是**結構性**的
  （指令跑不跑得起來），不是比對錯誤訊息字串——理由見 collect/__init__.py
  的 FAILURE_* 常數註解，那裡記了一次實測到的假陽性。
"""

from ..i18n import t
from ..width import disp_width, pad
# [CHANGE] 2026-08-03 bond 的窄版資料標題改走共用 block_title。
from .base import (BLOCK_RULE_WIDTH, Section, blank, block_rule, block_title, kv,
                   kv_coloured, note, subsection, thin_hr)

__all__ = ["OvsSection", "PORT_COLUMN_WIDTHS"]

KEY_WIDTH = 16

# bash：pad "  Port" 22; pad "VLAN Tag" 10; pad "VLAN 模式" 12; pad "成員介面" 40
# ★ 這四個數字是 bash 寫死的欄寬，這裡當成**下界**而不是定值：英文表頭
#   （"Member interfaces" 17 欄）比中文寬，若直接照抄固定值，某個語言的表頭
#   就會把下一欄推歪。實際欄寬取 max(bash 值, 表頭寬+1)。
PORT_COLUMN_WIDTHS = (22, 10, 12, 40)
PORT_RULE_WIDTH = 84


class OvsSection(Section):
    """Open vSwitch。"""

    def __init__(self, ovs_reader, sysfs_reader, ip_reader):
        self.ovs = ovs_reader
        self.sysfs = sysfs_reader
        self.ip = ip_reader

    def build(self):
        probe = self.ovs.probe()
        if probe["reason"] is not None:
            return {"reason": probe["reason"], "bridges": [], "bonds": []}

        bridges = []
        for name in self.ovs.bridges():
            ports = []
            for port in self.ovs.ports(name):
                info = self.ovs.port_info(port)
                ports.append({
                    "port": port,
                    # ★ 顯示層才把缺值變成 "-"。供料層保留 None，否則無從分辨
                    #   「查不到」與「值真的是字串 -」。
                    "tag": info["tag"] or "-",
                    "vlan_mode": info["vlan_mode"] or "-",
                    "ifaces": info["ifaces"] or port,
                })
            bridges.append({
                "name": name,
                "mtu": self.sysfs.mtu(name),
                "ipv4": self.ip.address_text(name, 4),
                "ipv6": self.ip.address_text(name, 6),
                "ports": ports,
            })

        bonds = [(name, self.ovs.bond_show(name)) for name in self.ovs.bonds()]
        return {"reason": None, "bridges": bridges, "bonds": bonds}

    def is_empty(self, data):
        return data["reason"] is not None

    def empty_lines(self, data, ctx):
        reason = data["reason"]
        if reason == "not_installed":
            return [note(t("ovs.not_installed"), ctx.palette),
                    t("ovs.not_installed_hint")]
        if reason == "ovsdb_unreachable":
            return [note(t("ovs.unreachable"), ctx.palette),
                    t("ovs.unreachable_hint")]
        return [note(t("ovs.no_bridges"), ctx.palette)]

    def table(self, data, ctx):
        return None

    def blocks(self, data, ctx):
        lines = []
        for bridge in data["bridges"]:
            lines.append(block_rule(BLOCK_RULE_WIDTH))
            lines.append(kv_coloured(t("ovs.label"), bridge["name"], ctx.palette,
                                     key_colour="bold", value_colour="cyan",
                                     key_width=KEY_WIDTH))
            lines.append(kv(t("nic.mtu"), bridge["mtu"], key_width=KEY_WIDTH))
            lines.append(kv(t("net.ipv4"), bridge["ipv4"], key_width=KEY_WIDTH))
            lines.append(kv(t("net.ipv6"), bridge["ipv6"], key_width=KEY_WIDTH))
            lines.append(blank())
            lines.append(t("ovs.ports_title"))
            lines.extend(self._port_table(bridge["ports"]))
            lines.append(blank())
        lines.append(block_rule(BLOCK_RULE_WIDTH))

        if data["bonds"]:
            lines.append(blank())
            lines.extend(subsection(t("ovs.bond_title"), ctx.palette))
            for name, output in data["bonds"]:
                lines.append(blank())
                lines.append(block_title(name, ctx.palette))
                if output:
                    lines.extend(output.splitlines())
        return lines

    @staticmethod
    def _port_table(ports):
        headers = (t("ovs.port"), t("ovs.tag"), t("ovs.vlan_mode"),
                   t("ovs.members"))
        widths = _column_widths(headers)
        lines = ["  " + _row(headers, widths)]
        lines.append(thin_hr(PORT_RULE_WIDTH))
        for entry in ports:
            lines.append("  " + _row(
                (entry["port"], entry["tag"], entry["vlan_mode"],
                 entry["ifaces"]), widths))
        return lines


def _column_widths(headers):
    """bash 的固定欄寬當下界，表頭比它寬時以表頭為準（見 PORT_COLUMN_WIDTHS）。"""
    # 第一欄 bash 是 pad "  $port" 22（含兩格縮排），這裡縮排另外加，故減 2。
    base = (PORT_COLUMN_WIDTHS[0] - 2,) + PORT_COLUMN_WIDTHS[1:]
    return tuple(max(width, disp_width(header) + 1)
                 for width, header in zip(base, headers))


def _row(cells, widths):
    return "".join(pad(str(cell), width)
                   for cell, width in zip(cells, widths)).rstrip()
