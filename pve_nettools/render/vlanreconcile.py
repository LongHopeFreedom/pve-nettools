# [CHANGE] 2026-08-02 新增：VLAN 對帳輸出區段（選單第 11 項，待辦 #18）。
"""Guest 使用的 VLAN 對上 Bridge Uplink 放行的 VLAN。

規格真值＝bash `render_vlan_reconcile`（`old/pve-network-audit.sh:1635-1747`）。

★ 這是整份工具**唯一會下判定**的區段（相符／需檢查），其餘都是呈現現況。
  所以它的錯誤方向有不對稱的代價：把「不通」判成「相符」會讓人去查別的地方，
  而反過來只是多看一眼。bash 的取法是——查無此 VLAN 就算未放行，這裡照做。

★ 對帳的兩個原語都已在 collect 層：
    collect.bridge.BridgeReader.allowed_vlans(port)  去標記後壓成範圍的放行清單
    collect.bridge.vlan_in_list(vid, list)           範圍比對，不展開成逐個值
  MUST NOT 在這一層自己再寫一套比對。bash 的註解記過為什麼不展開：`2-4090`
  展開要 171 ms、建 4090 個鍵再花 586 ms，而對帳只需查 guest 用到的那幾個。
"""

from ..collect import STATUS_OK, STATUS_UNAVAILABLE
from ..collect.bridge import is_guest_iface, vlan_in_list
from ..i18n import t
# [CHANGE] 2026-08-03 窄版標題改走共用 helper，逐值重用表格 colorizer。
from .base import (DecoratedTable, Section, blank, block_title, note,
                   subsection)

__all__ = ["VlanReconcileSection"]


class VlanReconcileSection(Section):
    """VLAN 對帳。"""

    HEADERS = ("vlanrec.bridge", "vlanrec.uplink", "vlanrec.used",
               "vlanrec.missing", "vlanrec.verdict")

    def __init__(self, bridge_reader, sysfs_reader, guest_reader):
        self.bridge = bridge_reader
        self.sysfs = sysfs_reader
        self.guest = guest_reader

    def build(self):
        show = self.bridge.vlan_show()
        # ★ 三種「沒得對帳」在 bash 是三段不同的文字，MUST 分辨：
        #   unavailable ⇒ 沒有 bridge 指令
        #   empty       ⇒ 有指令但沒有 VLAN-aware bridge
        #   有資料但無 uplink ⇒ 第三種（下面 reason="no_uplink"）
        if show["status"] == STATUS_UNAVAILABLE:
            return {"reason": "no_bridge_cmd", "rows": []}
        if show["status"] != STATUS_OK:
            return {"reason": "no_vlan_aware", "rows": []}

        uplinks = self._uplinks()
        if not uplinks:
            return {"reason": "no_uplink", "rows": []}

        nics = self.guest.nics()["nics"]
        if not nics:
            return {"reason": "no_guest", "rows": []}

        used_by = self._guest_vlans(nics)
        rows = []
        for bridge in sorted(uplinks):
            ports, allowed = uplinks[bridge]
            used = []
            missing = []
            for tag in sorted(used_by.get(bridge, {}), key=_tag_key):
                used.append(tag)
                if not vlan_in_list(tag, allowed):
                    missing.append(t("vlanrec.missing_item", vid=tag,
                                     vmids=" ".join(used_by[bridge][tag])))
            rows.append({
                "bridge": bridge,
                "uplink": ",".join(ports),
                "used": ",".join(used) if used else "-",
                "missing": ",".join(missing) if missing else "-",
                "ok": not missing,
            })
        return {"reason": None, "rows": rows}

    def _uplinks(self):
        """{bridge: (uplink port 清單, 放行 VLAN 清單串接)}。

        ★ 「uplink」的定義沿用 bash：這座 bridge 的 brif 成員中，**不是** guest
          動態介面（tap/veth/fwbr/fwpr/fwln）、也不是 bridge 自己、且在
          `bridge vlan show` 裡查得到放行清單的 port。
        """
        found = {}
        for bridge in self.sysfs.bridges():
            if not self.sysfs.vlan_filtering(bridge):
                continue
            ports = []
            allowed = []
            for port in self.sysfs.bridge_ports(bridge):
                if is_guest_iface(port) or port == bridge:
                    continue
                vlans = self.bridge.allowed_vlans(port)
                if not vlans:
                    continue
                ports.append(port)
                allowed.append(vlans)
            if ports:
                found[bridge] = (ports, ",".join(allowed))
        return found

    @staticmethod
    def _guest_vlans(nics):
        """{bridge: {tag: [vmid, ...]}}。

        ★ 這裡要的是**每個 (bridge, tag) 各由哪些 VM 使用**，而
          `GuestConfReader.guest_vlans()` 只回 {bridge: [tag]}——少了 vmid 就印
          不出 bash 的「20(VM 101 102)」。故在此就地組合，而不是去改那個原語：
          它另有呼叫端，改它的回傳形狀會波及不相干的地方。
        """
        table = {}
        for nic in nics:
            bridge = nic.get("bridge")
            tag = nic.get("tag")
            if not bridge or not tag:
                continue
            by_tag = table.setdefault(bridge, {})
            vmids = by_tag.setdefault(str(tag), [])
            vmid = str(nic.get("vmid"))
            if vmid not in vmids:
                vmids.append(vmid)
        return table

    def is_empty(self, data):
        return not data["rows"]

    def empty_lines(self, data, ctx):
        head = subsection(t("vlanrec.title"), ctx.palette) + [blank()]
        reason = data["reason"]
        if reason == "no_bridge_cmd":
            # bash 這一段的提示在標題之後——`subsection` 是函式的第一件事。
            return head + [note(t("vlanrec.no_bridge_cmd"), ctx.palette)]
        if reason == "no_vlan_aware":
            return head + [note(t("vlanrec.no_vlan_aware"), ctx.palette),
                           t("vlanrec.no_vlan_aware_hint")]
        if reason == "no_uplink":
            return head + [note(t("vlanrec.no_uplink"), ctx.palette)]
        return head + [note(t("vlanrec.no_guest"), ctx.palette)]

    def table(self, data, ctx):
        table = DecoratedTable(
            [t(key) for key in self.HEADERS],
            leading=subsection(t("vlanrec.title"), ctx.palette) + [blank()],
            trailing=[blank(), t("vlanrec.note1"), t("vlanrec.note2"),
                      t("vlanrec.note3")])
        for row in data["rows"]:
            table.add([row["bridge"], row["uplink"], row["used"],
                       row["missing"], self._verdict(row)])
        return table

    def colorizer(self, data, ctx):
        def paint(row_index, col_index, text):
            if col_index == 4:
                return ctx.paint(
                    text, "green" if data["rows"][row_index]["ok"] else "red")
            return text
        return paint

    @staticmethod
    def _verdict(row):
        return t("vlanrec.match") if row["ok"] else t("vlanrec.check")

    def blocks(self, data, ctx):
        lines = subsection(t("vlanrec.title"), ctx.palette) + [blank()]
        headers = [t(key) for key in self.HEADERS]
        paint = self.colorizer(data, ctx)
        for row_index, row in enumerate(data["rows"]):
            lines.append(block_title(row["bridge"], ctx.palette))
            values = [row["uplink"], row["used"], row["missing"],
                      self._verdict(row)]
            for index, value in enumerate(values, start=1):
                lines.append("%s%s%s" % (
                    headers[index], t("app.kv_sep"),
                    paint(row_index, index, value)))
            lines.append(blank())
        lines.extend([t("vlanrec.note1"), t("vlanrec.note2"),
                      t("vlanrec.note3")])
        return lines


def _tag_key(tag):
    """數字在前依數值排、非數字在後依字面排（與 collect.pve.guest_vlans 同規則）。"""
    return (0, int(tag), "") if str(tag).isdigit() else (1, 0, str(tag))
