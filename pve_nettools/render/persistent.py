# [CHANGE] 2026-08-02 新增：持久化設定輸出區段（選單第 17 項，待辦 #17）。
"""`/etc/network/interfaces` 與 `interfaces.d/` 的原文。

規格真值＝bash `render_persistent_config`（`old/pve-network-audit.sh:1977-2000`）。

★★ 與選單 15 同一件事：待辦 #17 標「有供料只缺 key」，但 `collect/netconf.py`
   的 `parse_interfaces()` 回傳的是 **stanza 結構**，而 bash 這一頁印的是
   **原文行**。用結構重建原文會丟掉續行的原始換行位置與縮排，而這一頁的用途
   正是「拿去和真正的檔案逐行對照」。故走 `collect/textconf.py`。
   ★ `NetconfReader` 仍在用——`.new` 的偵測由它負責（見 pending_change()），
     那是它已經做對的部分。
"""

from ..collect import STATUS_UNAVAILABLE
from ..i18n import t
from .base import Section, blank, note, subsection

__all__ = ["PersistentSection"]


class PersistentSection(Section):
    """持久化網路設定。"""

    def __init__(self, textconf_reader, netconf_reader):
        self.conf = textconf_reader
        self.netconf = netconf_reader

    # ★ 路徑向 NetconfReader 取，不另開參數。它已經處理過 NET_CONF_FILE／
    #   NET_CONF_DIR 兩個環境變數覆寫；再傳一份進來就有兩個真值來源，而測試
    #   只會餵其中一個。
    @property
    def conf_file(self):
        return self.netconf.conf_file

    @property
    def conf_dir(self):
        return self.netconf.conf_dir

    def build(self):
        main = self.conf.read_lines(self.conf_file)
        extras = []
        for path in self.conf.list_files(self.conf_dir):
            extras.append((path, self.conf.read_lines(path)))
        return {
            "main": main,
            "extras": extras,
            # ★ 沿用 NetconfReader 既有的 pending_change()，不自己再判一次
            #   `<檔名>.new` 存不存在。兩份實作會漂移，而這個判定的後果是
            #   「設定改了但沒套用」這種很容易被忽略的狀態。
            "pending": self.netconf.pending_change(),
        }

    # [CHANGE] 2026-08-02 判準由「主檔沒有實質內容」改成「主檔不存在」。
    #
    # ★ 缺陷是委派方寫測試時抓到的（我寫的是 `not data["main"]["lines"]`）。
    #   bash 的條件是 `[[ ! -f "$NET_CONF_FILE" ]]`——**檔案存不存在**，不是
    #   有沒有實質內容。一份整份都是註解的 interfaces 是合法狀態（例如全部設定
    #   都放在 interfaces.d），而舊判準會對它印「找不到 /etc/network/interfaces」。
    # ★★ 更嚴重的是**連帶效果**：走 empty_lines 就整段結束，於是 interfaces.d
    #   底下的設定與「.new 尚未套用」那行警告**一起消失**。使用者看到的是一句
    #   「找不到」，而真正的設定就在隔壁目錄裡。
    # ★ 這一條是「三態被壓成兩態」的又一次：empty（有檔沒內容）與 unavailable
    #   （沒有檔）在 collect 層分得好好的，是我在 render 層把它們合併掉了。
    def is_empty(self, data):
        return data["main"]["status"] == STATUS_UNAVAILABLE

    def empty_lines(self, data, ctx):
        return [note(t("persistent.not_found", path=self.conf_file), ctx.palette)]

    def table(self, data, ctx):
        return None

    def blocks(self, data, ctx):
        lines = subsection(t("persistent.file_title", path=self.conf_file),
                           ctx.palette)
        lines.extend(data["main"]["lines"] or [])

        for path, result in data["extras"]:
            lines.append(blank())
            lines.extend(subsection(t("persistent.file_title", path=path),
                                    ctx.palette))
            lines.extend(result["lines"] or [])

        if data["pending"]:
            lines.append(blank())
            lines.append(note(t("persistent.pending", path=self.conf_file),
                              ctx.palette))
        return lines
