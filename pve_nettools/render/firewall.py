# [CHANGE] 2026-08-02 新增：PVE 防火牆輸出區段（選單第 15 項，待辦 #17）。
"""pve-firewall 狀態與各層 .fw 設定原文。

規格真值＝bash `render_firewall`（`old/pve-network-audit.sh:1885-1911`）。

★★ 待辦 #17 把本項標成「有供料只缺 i18n key」，**實測後供料並不完整**：
   `collect/firewall.py` 有 `parse_fw()`，回傳的是**結構**（options dict 與
   sections 清單），而 bash 這一頁印的是**原文行**（`grep -Ev '^\\s*(#|$)'`）。
   從結構重建原文是有損的——section 標頭、options 的原始順序都回不來。
   故本項改走 `collect/textconf.py` 的 `read_lines()`。
   ★ 這與上一棒第 3 項踩到的是同一個形狀（`_parse_eeprom` 在解析階段就把
     bash 要的欄位丟掉了）。**解析得越完整，越容易讓人以為原文也還在。**
"""

import os

from ..collect import FAILURE_NOT_EXECUTABLE, STATUS_OK, STATUS_UNAVAILABLE
from ..i18n import t
from .base import Section, blank, note, subsection

__all__ = ["FirewallSection"]

FIREWALL_DIR = "firewall"
LOCAL_HOST_FW = ("local", "host.fw")
FW_SUFFIX = ".fw"


class FirewallSection(Section):
    """PVE 防火牆。"""

    def __init__(self, firewall_reader, textconf_reader):
        self.firewall = firewall_reader
        self.conf = textconf_reader

    def build(self):
        status = self.firewall.status()
        files = []
        # bash：`for f in "$fw_dir"/*.fw` ⇒ 依 shell 的 glob 排序，且**不限**
        # 數字 VMID。FirewallReader.guest_ids() 只認純數字檔名，射程比 bash 窄，
        # 故這裡直接列目錄——這一頁要的是「這座主機上所有 .fw 的內容」。
        for path in self.conf.list_files(self.conf.path(FIREWALL_DIR),
                                         suffix=FW_SUFFIX):
            files.append((path, self.conf.read_lines(path)))

        host_path = self.conf.path(*LOCAL_HOST_FW)
        host = (self.conf.read_lines(host_path)
                if os.path.isfile(host_path) else None)
        return {"status": status, "files": files, "host": host,
                "host_path": host_path}

    def is_empty(self, data):
        # ★ 只有「pve-firewall 這支指令根本不存在」才整段收掉。有指令但拿不到
        #   狀態時 bash 仍會印小標題與 .fw 內容——那些內容與指令能不能跑無關。
        return (data["status"]["status"] == STATUS_UNAVAILABLE
                and data["status"].get("failure") == FAILURE_NOT_EXECUTABLE)

    def empty_lines(self, data, ctx):
        return [note(t("firewall.not_found"), ctx.palette)]

    def table(self, data, ctx):
        return None

    def blocks(self, data, ctx):
        lines = subsection(t("firewall.status_title"), ctx.palette) + [blank()]
        status = data["status"]
        if status["status"] == STATUS_OK:
            lines.extend(status["stdout"].splitlines())
        else:
            lines.append(note(t("firewall.status_failed"), ctx.palette))

        for path, result in data["files"]:
            lines.append(blank())
            lines.extend(subsection(t("firewall.file_title", path=path),
                                    ctx.palette))
            lines.extend(result["lines"] or [])

        if data["host"] is not None:
            lines.append(blank())
            lines.extend(subsection(t("firewall.host_title"), ctx.palette))
            lines.extend(data["host"]["lines"] or [])
        return lines
