# [CHANGE] 2026-08-02 新增：傳統 VLAN 子介面輸出區段（選單第 8 項，待辦 #16）。
"""傳統 VLAN 子介面（`eno1.100` 這種）的清單。

規格真值＝bash `render_vlan_subinterfaces`（`old/pve-network-audit.sh:1218-1261`）。

★ 這一段與 Bridge VLAN Filter（選單 9）是**兩種不同的 VLAN 建置方式**，不是同一
  份資料的兩個視角：這裡是「每個 VLAN 一個子介面」，第 9 項是「一座 VLAN-aware
  Bridge 上以 tag 區分」。bash 的說明散文也是這樣分的（見 render_vlan_reconcile
  的結尾），所以兩個區段都要保留。
"""

from ..collect import STATUS_UNAVAILABLE
from ..i18n import t
# [CHANGE] 2026-08-03 九個窄版資料標題統一由 block_title 呈現粗體框線與青色名稱。
from .base import DecoratedTable, Section, block_title, kv, note, subsection

__all__ = ["IFTYPE_KEYS", "VlanSubSection"]

# collect.sysfs.interface_type() 的回傳鍵 → i18n key。
# ★ 用查表而不是字串拼接（`"iftype." + kind`）：拼接會在 collect 多回一種類別時
#   產生一個不存在的 i18n key，而 t() 對缺 key 的處理是回傳 key 本身——畫面上
#   出現 `iftype.macvlan` 這種字串，測試卻不會紅。同樣的理由見 render/nic.py
#   的 MEDIA_KEYS。
IFTYPE_KEYS = {
    "bond": "iftype.bond",
    "bridge": "iftype.bridge",
    "physical": "iftype.physical",
    "unknown": "iftype.unknown",
    "other": "iftype.other",
}


class VlanSubSection(Section):
    """傳統 VLAN 子介面。"""

    HEADERS = ("vlansub.iface", "vlansub.vid", "vlansub.parent",
               "vlansub.parent_type", "nic.mtu", "net.state", "net.ipv4")

    def __init__(self, ip_reader, sysfs_reader):
        self.ip = ip_reader
        self.sysfs = sysfs_reader

    def build(self):
        result = self.ip.vlan_interfaces()
        # ★ 三態在這裡有畫面上的差別，MUST NOT 壓成一個「沒有」：
        #   unavailable ⇒ 沒裝 iproute2，bash 印「找不到 ip 指令」且**不印標題**；
        #   empty       ⇒ 裝了但沒有 VLAN 子介面，bash **會印標題**再說沒有。
        #   兩者的下一步不同（去裝套件 vs 這台本來就沒用子介面）。
        if result["status"] == STATUS_UNAVAILABLE:
            return {"available": False, "rows": []}

        rows = []
        for vlan in (result["data"] or []):
            parent = self.ip.vlan_parent(vlan)
            kind = self.sysfs.interface_type(parent) if parent else "unknown"
            rows.append([
                vlan,
                self.ip.vlan_id(vlan) or t("app.na"),
                parent or t("app.na"),
                t(IFTYPE_KEYS.get(kind, "iftype.unknown")),
                self.sysfs.mtu(vlan),
                self.sysfs.operstate(vlan),
                self.ip.address_text(vlan, 4),
            ])
        return {"available": True, "rows": rows}

    def is_empty(self, data):
        return not data["rows"]

    def empty_lines(self, data, ctx):
        if not data["available"]:
            return [note(t("net.no_ip_command"), ctx.palette)]
        # bash 在「裝了但沒有子介面」時仍先印標題與空行，再印提示。
        return (subsection(t("vlansub.title"), ctx.palette) + [""]
                + [note(t("vlansub.none"), ctx.palette)])

    def table(self, data, ctx):
        table = DecoratedTable(
            [t(key) for key in self.HEADERS],
            leading=subsection(t("vlansub.title"), ctx.palette) + [""])
        for row in data["rows"]:
            table.add(row)
        return table

    def blocks(self, data, ctx):
        """窄終端的退路。

        ★ bash 這一段**只有表格版**，沒有 render_vlan_subinterfaces_blocks。
          區塊版是 Python 版多出來的，理由見 render/base.py：表格放不下時
          bash 會整列爆版而讀不出對應關係。這不是與 bash 的欄位差異——欄位
          與順序完全相同，只是換一種排法。
        """
        lines = subsection(t("vlansub.title"), ctx.palette) + [""]
        headers = [t(key) for key in self.HEADERS]
        for row in data["rows"]:
            lines.append(block_title(row[0], ctx.palette))
            for index in range(1, len(headers)):
                lines.append(kv(headers[index], row[index], key_width=12))
            lines.append("")
        return lines
