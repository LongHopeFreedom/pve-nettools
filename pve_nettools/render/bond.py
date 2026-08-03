# [CHANGE] 2026-08-02 新增：Bond 設定與成員狀態輸出區段（選單第 5 項，待辦 #16）。
"""Bond 介面與其成員的狀態。

規格真值＝bash `render_bonds`（`old/pve-network-audit.sh:934-1019`）。
本區段沒有表格版（bash 也沒有），`table()` 回 None。
"""

from ..collect import STATUS_OK
from ..collect.bond import slave_names_text
from ..i18n import t
from .base import (BLOCK_RULE_WIDTH, Section, block_rule, blank, kv,
                   kv_coloured, note)

__all__ = ["BondSection"]

KEY_WIDTH = 16
# bash 成員區塊：`echo "    Permanent MAC：…"`，最長的鍵是 13 欄，四格縮排在外。
SLAVE_KEY_WIDTH = 13
SLAVE_INDENT = "    "


def _value(value):
    """缺值一律 N/A。

    bash 寫法是 `${mode:-N/A}`，故空字串與未設定都是 N/A。供料層回 None，
    這裡把兩者收斂到同一個顯示值。
    """
    return t("app.na") if value is None or value == "" else str(value)


class BondSection(Section):
    """Bond 介面清單。"""

    def __init__(self, bond_reader, sysfs_reader, ip_reader):
        self.bond = bond_reader
        self.sysfs = sysfs_reader
        self.ip = ip_reader

    def build(self):
        rows = []
        for name in self.bond.bonds():
            result = self.bond.read(name)
            if result["status"] != STATUS_OK:
                # ★ 讀不到就整個略過這座 bond，與 bash 的 `[[ -f ]] || continue`
                #   同一個立場：procfs 檔在 bond 被拆掉的瞬間會消失，那不是錯誤。
                continue
            data = result["data"]
            rows.append({
                "name": name,
                "data": data,
                "slaves_text": slave_names_text(data),
                "lacp_rate": self.bond.lacp_rate(name),
                "min_links": self.bond.min_links(name),
                "mtu": self.sysfs.mtu(name),
                "ipv4": self.ip.address_text(name, 4),
                "ipv6": self.ip.address_text(name, 6),
            })
        return rows

    def table(self, data, ctx):
        return None

    def blocks(self, data, ctx):
        lines = []
        for row in data:
            info = row["data"]
            lines.append(block_rule(BLOCK_RULE_WIDTH))
            lines.append(kv_coloured(t("bond.label"), row["name"], ctx.palette,
                                     key_colour="bold", value_colour="cyan",
                                     key_width=KEY_WIDTH))
            lines.append(kv(t("bond.mode"), _value(info.get("mode")),
                            key_width=KEY_WIDTH))
            lines.append(kv(t("bond.slaves"), _value(row["slaves_text"]),
                            key_width=KEY_WIDTH))
            lines.append(kv(t("bond.hash_policy"), _value(info.get("hash_policy")),
                            key_width=KEY_WIDTH))
            lines.append(kv(t("bond.active"), _value(info.get("active_slave")),
                            key_width=KEY_WIDTH))
            lines.append(kv(t("bond.primary"), _value(info.get("primary_slave")),
                            key_width=KEY_WIDTH))
            lines.append(kv(t("bond.lacp_rate"), _value(row["lacp_rate"]),
                            key_width=KEY_WIDTH))
            lines.append(kv(t("bond.min_links"), _value(row["min_links"]),
                            key_width=KEY_WIDTH))
            lines.append(kv(t("nic.mtu"), row["mtu"], key_width=KEY_WIDTH))
            lines.append(kv(t("net.ipv4"), row["ipv4"], key_width=KEY_WIDTH))
            lines.append(kv(t("net.ipv6"), row["ipv6"], key_width=KEY_WIDTH))

            text, colour = self._state(info.get("status"))
            lines.append(kv_coloured(t("bond.link"), text, ctx.palette,
                                     value_colour=colour, key_width=KEY_WIDTH))

            lines.append(blank())
            lines.append(t("bond.member_states"))
            for slave in info.get("slaves") or []:
                lines.extend(self._slave_lines(slave, ctx))
            lines.append(blank())
        lines.append(block_rule(BLOCK_RULE_WIDTH))
        return lines

    def _slave_lines(self, slave, ctx):
        text, colour = self._state(slave.get("status"))
        lines = [
            "%s%s" % (SLAVE_INDENT[:2],
                      ctx.paint(slave.get("name") or t("app.na"), "bold")),
            self._slave_kv(t("bond.slave_link"), text, ctx, colour),
            self._slave_kv(t("bond.slave_speed"), _value(slave.get("speed")), ctx),
            self._slave_kv(t("bond.slave_mac"),
                           _value(slave.get("permanent_mac")), ctx),
        ]
        # ★ Aggregator ID 只在**有值**時才印——bash 是
        #   `[[ -n "$aggregator_id" ]] && echo …`。非 802.3ad 的 bond 沒有這個
        #   欄位，硬印成 N/A 會讓人以為讀取失敗。
        if slave.get("aggregator_id"):
            lines.append(self._slave_kv(t("bond.slave_agg"),
                                        slave["aggregator_id"], ctx))
        return lines

    @staticmethod
    def _slave_kv(key, value, ctx, colour=None):
        return SLAVE_INDENT + kv_coloured(key, value, ctx.palette,
                                          value_colour=colour,
                                          key_width=SLAVE_KEY_WIDTH)

    @staticmethod
    def _state(status):
        """bash 的三分支：up→綠正常、down→紅異常、其餘→黃色原值（空值印未知）。"""
        if status == "up":
            return t("bond.up"), "green"
        if status == "down":
            return t("bond.down"), "red"
        return (status or t("app.unknown")), "yellow"

    def empty_lines(self, data, ctx):
        return [note(t("bond.none"), ctx.palette)]
