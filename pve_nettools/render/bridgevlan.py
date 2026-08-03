# [CHANGE] 2026-08-01 新增：Bridge VLAN Filter 輸出區段（待辦 #8）。
"""逐 Port 顯示 bridge VLAN 放行清單。"""

from ..collect.bridge import PORT_BRIDGE, PORT_GUEST, PORT_UPLINK, port_kind
from ..i18n import t
from ..width import Table, disp_width, wrap_csv
# [CHANGE] 2026-08-03 九個窄版資料標題統一由 block_title 呈現粗體框線與青色名稱。
from .base import Section, block_title, kv, note

__all__ = ["BridgeVlanSection"]

TYPE_KEYS = {
    PORT_UPLINK: "bridgevlan.uplink",
    PORT_GUEST: "bridgevlan.guest",
    PORT_BRIDGE: "bridgevlan.self",
}


class BridgeVlanSection(Section):
    HEADERS = ("bridgevlan.port", "bridgevlan.type", "bridgevlan.pvid",
               "bridgevlan.allowed")

    def __init__(self, bridge_reader, sysfs_reader):
        self.reader = bridge_reader
        self.sysfs = sysfs_reader

    # [CHANGE] 2026-08-01 改由 SysfsReader 供 self 判定，並移除原本的名稱猜測。
    #
    # 原實作在 reader 沒有 is_bridge 時退回 `port.startswith("vmbr")`。委派規格把
    # 本區段的依賴限定成 BridgeReader，而它**沒有** is_bridge——所以正式路徑一定
    # 走那條猜測，實測 `lan-core`（自訂名稱的 bridge）被判成 Uplink。測試注入的
    # fake 有 is_bridge，於是猜測分支在測試中從未被執行：驗過的路徑與正式環境走
    # 的路徑不是同一條。
    #
    # ★ 資料源本來就指明了：`collect.bridge.port_kind()` 的 docstring 寫「is_bridge
    #   由呼叫端提供（SysfsReader.is_bridge）」。錯的是規格的依賴清單。
    def _is_bridge(self, port):
        return self.sysfs.is_bridge(port)

    def build(self):
        available = self.reader.available()
        rows = []
        if available:
            for port in self.reader.ports():
                kind = port_kind(port, is_bridge=self._is_bridge(port))
                rows.append({
                    "port": port,
                    "kind": t(TYPE_KEYS.get(kind, "bridgevlan.uplink")),
                    "pvid": self.reader.port_pvid(port),
                    "allowed": self.reader.port_vlans(port),
                })
        return {"available": available, "rows": rows}

    def is_empty(self, data):
        return not data["available"] or not data["rows"]

    # [CHANGE] 2026-08-01 基底的 empty_lines 改收 data 後，這裡不再需要把 data 從
    #          build() 用 instance 屬性偷渡出來，也不必覆寫 render()——覆寫等於把
    #          「build 恰好一次」那條契約複製一份，兩份會各自漂移。
    def empty_lines(self, data, ctx):
        if not data["available"]:
            return [note("%s bridge" % t("app.not_found"), ctx.palette)]
        return [note(t("app.none"), ctx.palette)]

    def table(self, data, ctx):
        headers = [t(key) for key in self.HEADERS]
        table = Table(headers)
        first_three = []
        for index in range(3):
            values = [headers[index]]
            if index == 0:
                values.extend(row["port"] for row in data["rows"])
            elif index == 1:
                values.extend(row["kind"] for row in data["rows"])
            else:
                values.extend(t("app.na") if row["pvid"] is None else str(row["pvid"])
                              for row in data["rows"])
            first_three.append(max(disp_width(value) for value in values))
        # [CHANGE] 2026-08-01 欄距原本寫死成 6。gap 是 Table 的屬性，改掉它就會靜默
        #          算錯——向物件取值，不要重打一次它的預設值。
        fixed = sum(first_three) + table.gap * (len(headers) - 1)
        allowed_width = max(disp_width(headers[3]), ctx.width - fixed)

        for row in data["rows"]:
            pvid = t("app.na") if row["pvid"] is None else str(row["pvid"])
            allowed = t("app.na") if row["allowed"] is None else str(row["allowed"])
            wrapped = wrap_csv(allowed, allowed_width) or [allowed]
            table.add([row["port"], row["kind"], pvid, wrapped[0]])
            for continuation in wrapped[1:]:
                table.add(["", "", "", continuation])
        return table

    def blocks(self, data, ctx):
        lines = []
        for row in data["rows"]:
            lines.append(block_title(row["port"], ctx.palette))
            lines.append(kv(t("bridgevlan.type"), row["kind"], key_width=8))
            lines.append(kv(t("bridgevlan.pvid"),
                            t("app.na") if row["pvid"] is None else str(row["pvid"]),
                            key_width=8))
            lines.append(kv(t("bridgevlan.allowed"),
                            t("app.na") if row["allowed"] is None else str(row["allowed"]),
                            key_width=8))
            lines.append("")
        return lines
