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


# [CHANGE] 2026-08-05 待辦 #15：抽成函式讓 is_empty() 與 build() 共用同一個判斷。
#   兩處各寫一次的話，其中一處被改動就會漂移，而症狀是「明知跑不到還是跑了
#   兩次 subprocess」——那不會有任何測試變紅。
def _not_executable(status):
    """pve-firewall 這支指令本身不存在（不是「跑了但失敗」）。"""
    return (status["status"] == STATUS_UNAVAILABLE
            and status.get("failure") == FAILURE_NOT_EXECUTABLE)


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
        # [CHANGE] 2026-08-05 待辦 #15：GUI 看不到的兩件事，見 collect 側註解。
        # ★ pve-firewall 這支指令都不存在時，兩個子指令一定也拿不到 ⇒ 不要白跑。
        #   理由**不是速度**：實測開發機上一次失敗的 subprocess 只花 4ms。
        #   理由是「明知拿不到還發動系統呼叫」——盤查工具在別人的機器上跑，
        #   每一次 exec 都會進 audit log，製造與問題無關的噪音。
        # ★ 我第一版把這裡寫成「讓全套測試由 3.6 秒變成 17.3 秒」，那個歸因
        #   **實測不成立**（4ms × 呼叫次數遠達不到；那是 PYTHONDONTWRITEBYTECODE
        #   之下每次重新編譯全部模組的波動）。改動正確、理由錯誤——留著一個錯的
        #   理由會誤導下一個人，所以照實改掉。
        skip = _not_executable(status)
        return {"status": status, "files": files, "host": host,
                "host_path": host_path,
                "compile": None if skip else self.firewall.compile_rules(),
                "localnet": None if skip else self.firewall.localnet()}

    def is_empty(self, data):
        # ★ 只有「pve-firewall 這支指令根本不存在」才整段收掉。有指令但拿不到
        #   狀態時 bash 仍會印小標題與 .fw 內容——那些內容與指令能不能跑無關。
        # ★ 與 build() 的短路共用 _not_executable()，兩處不會漂移。
        return _not_executable(data["status"])

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

        # [CHANGE] 2026-08-05 待辦 #15：設定看完之後才是「這份設定實際變成什麼」。
        # ★ 排在最後是刻意的：先設定、後生效，與人排查的順序一致，
        #   而且不動到既有三段的相對位置。
        # ★ **不截斷**。輸出可能很長，但截斷門檻要有真機樣本才定得出來，而
        #   「靜默截斷」比長輸出更糟——這座專案已有一條自檢在守那件事（AP）。
        #   輸出長度是否需要處理，列為真機驗證的確認項。
        # ★★ 契約（2026-08-05 第 2 輪 code review 補寫）：這兩個值在 build() 短路時
        #   是 `None`，而這裡**不做 None 檢查**——因為短路條件與 is_empty() 是
        #   `_not_executable()` **同一個判斷**，短路時 render() 走的是 empty_lines()，
        #   結構上到不了這裡。刻意不加防禦式檢查：那會是一條測不到的分支。
        #   ⇒ **改 is_empty() 的條件時 MUST 一併看這裡**，兩者是同一個契約的兩端。
        for key, title_key, failed_key in (
                ("compile", "firewall.compile_title", "firewall.compile_failed"),
                ("localnet", "firewall.localnet_title",
                 "firewall.localnet_failed")):
            result = data[key]
            lines.append(blank())
            lines.extend(subsection(t(title_key), ctx.palette))
            if result["status"] == STATUS_OK and result.get("stdout"):
                lines.extend(result["stdout"].splitlines())
            else:
                lines.append(note(t(failed_key), ctx.palette))
        return lines
