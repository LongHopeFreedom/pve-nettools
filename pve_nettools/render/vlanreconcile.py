# [CHANGE] 2026-08-02 新增：VLAN 對帳輸出區段（選單第 11 項，待辦 #18）。
"""Guest 使用的 VLAN 對上 Bridge Uplink 放行的 VLAN。

規格真值＝bash `render_vlan_reconcile`（`old/pve-network-audit.sh:1635-1747`）。

★ 這是整份工具**唯一會下判定**的區段（相符／需檢查），其餘都是呈現現況。
  所以它的錯誤方向有不對稱的代價：把「不通」判成「相符」會讓人去查別的地方，
  而反過來只是多看一眼。bash 的取法是——查無此 VLAN 就算未放行，這裡照做。

★ 對帳的原語全都已在 collect 層：
    collect.bridge.BridgeReader.allowed_vlans(port)  去標記後壓成範圍的放行清單
    collect.bridge.vlan_in_list(vid, list)           範圍比對，不展開成逐個值
    collect.pve.GuestConfReader.guest_vlans(nics)    {bridge: {tag: [vmid]}}
    collect.pve.vlan_tag_key(tag)                    tag 排序鍵
  MUST NOT 在這一層自己再寫一套——**比對、分組、排序都算**。
  [CHANGE] 2026-08-05 待辦 #61／#66：原本這條只寫了「比對」，於是分組與排序
  各被就地重寫一份；其中排序那份用 str.isdigit()，遇到上標數字（tag="²"）
  int() 會拋 ValueError 炸穿整個區段，而 764 條測試全綠——沒有 fixture 用過它。
  bash 的註解記過為什麼不展開範圍：`2-4090` 展開要 171 ms、建 4090 個鍵再花
  586 ms，而對帳只需查 guest 用到的那幾個。
"""

from ..collect import STATUS_UNAVAILABLE
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
        #   沒有 vlan_filtering=1 的 bridge ⇒ 沒有 VLAN-aware bridge
        #   有 VLAN-aware bridge 但無 uplink ⇒ 第三種（下面 reason="no_uplink"）
        if show["status"] == STATUS_UNAVAILABLE:
            return {"reason": "no_bridge_cmd", "rows": []}

        # [CHANGE] 2026-08-06 待辦 #76：no_vlan_aware 改由 sysfs 判，與挑 uplink
        # 共用同一份清單。
        # WHY: 原本這裡判 `show["status"] != STATUS_OK`（＝`bridge vlan show`
        #   有沒有可解析的輸出），而 `_uplinks()` 判的是
        #   `/sys/class/net/<br>/bridge/vlan_filtering`——**同一件事兩個資料
        #   來源**。`bridge vlan show` 對 vlan_filtering=0 的 bridge 仍會列出
        #   port，於是「有 bridge 但一座都沒開 VLAN aware」（PVE 未勾 VLAN
        #   aware 的常態）落到 no_uplink，印出一句**預設了「有 VLAN-aware
        #   Bridge」**的訊息，而實際成因是一座都沒有。兩者指向的排查方向不同，
        #   而這是整份工具唯一會下判定的區段（見檔頭）。
        # WHAT: 先算出 vlan-aware bridge 清單，空 ⇒ no_vlan_aware；非空才挑
        #   uplink。清單只讀一次 vlan_filtering，兩個判定共用 ⇒ **結構上不可能
        #   再分歧**，不是讓兩份判準碰巧一致。
        # ★ 這個修法的正當性不依賴「vlan_filtering=0 時 bridge vlan show 有沒有
        #   輸出」這個未在真機實測的前提：「VLAN-aware」的定義就在
        #   vlan_filtering，用它判至少不會比用指令輸出差。有輸出 ⇒ 修正誤判；
        #   沒輸出 ⇒ 兩種判準結論相同、行為零變化。
        # ★ 依賴具名：sysfs 讀不到 /sys/class/net 時 bridges() 回空 ⇒ 判
        #   no_vlan_aware。該情境要求「bridge 指令可用且有輸出」而「/sys 讀不
        #   到」同時成立，在 Linux 上兩者同源；**本棒未實測其可達性**。
        vlan_aware = self._vlan_aware_bridges()
        if not vlan_aware:
            return {"reason": "no_vlan_aware", "rows": []}

        uplinks = self._uplinks(vlan_aware)
        if not uplinks:
            return {"reason": "no_uplink", "rows": []}

        nics = self.guest.nics()["nics"]
        if not nics:
            return {"reason": "no_guest", "rows": []}

        # [CHANGE] 2026-08-05 待辦 #61：改用 collect 層的原語，不再就地重組。
        used_by = self.guest.guest_vlans(nics)
        rows = []
        for bridge in sorted(uplinks):
            ports, allowed = uplinks[bridge]
            used = []
            missing = []
            # guest_vlans() 已依 vlan_tag_key 排好序且 dict 保序，此處不再自己排。
            for tag in used_by.get(bridge, {}):
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

    # [CHANGE] 2026-08-06 待辦 #76：抽出來的唯一一處 vlan_filtering 讀取點。
    # ★ 它同時是 no_vlan_aware 的判準與 uplink 的候選集合。抽出來之前這兩件事
    #   各有各的資料來源，而**只有其中一條分支會被寫進測試**。
    def _vlan_aware_bridges(self):
        """開了 vlan_filtering 的 bridge 清單（＝「VLAN-aware」的定義所在）。"""
        return [bridge for bridge in self.sysfs.bridges()
                if self.sysfs.vlan_filtering(bridge)]

    def _uplinks(self, bridges):
        """{bridge: (uplink port 清單, 放行 VLAN 清單串接)}。

        ★ 「uplink」的定義沿用 bash：這座 bridge 的 brif 成員中，**不是** guest
          動態介面（tap/veth/fwbr/fwpr/fwln）、也不是 bridge 自己、且在
          `bridge vlan show` 裡查得到放行清單的 port。

        [CHANGE] 2026-08-06 待辦 #76：候選 bridge 由呼叫端傳入，此處不再自己
        讀 vlan_filtering——同一份清單餵給兩個判定，才不會再分歧。
        """
        found = {}
        for bridge in bridges:
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

    # [CHANGE] 2026-08-05 待辦 #61：移除 _guest_vlans()。它與
    # collect.pve.GuestConfReader.guest_vlans() 做同一件事（掃 nics 依 bridge
    # 分組 tag），差別只在有沒有帶 vmid；已把 vmid 加進那個原語，此處直接用。
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


# [CHANGE] 2026-08-05 待辦 #66：移除 _tag_key()。它的 docstring 宣稱「與
# collect.pve.guest_vlans 同規則」，實際上用 str.isdigit() 而那邊用 _DIGITS_RE
# （^[0-9]+$）。實測 tag="２"（全形）兩份排序位置不同、tag="²"（上標）這一份
# int() 直接拋 ValueError。排序鍵現已是 collect.pve.vlan_tag_key 一份。
# ★ 宣稱「與 X 同規則」的註解本身沒有守衛——它讀起來完全正確。
