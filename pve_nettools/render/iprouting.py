# [CHANGE] 2026-08-02 新增：IP／路由／DNS／hosts／鄰居輸出區段（選單第 12 項，待辦 #16）。
"""介面位址、路由表、DNS、hosts 與鄰居表。

規格真值＝bash `render_ip_routing`（`old/pve-network-audit.sh:1831-1881`）。

★ 本區段是 `LIST_LIMIT` 的**唯一使用者**。上一棒（待辦 #24）把 `LIST_LIMIT` 從
  `--help` 移除，理由是「說明文件承諾了零實作的功能」——那個判斷在當時完全正確，
  bash 有實作而 Python 沒有。本項實作之後它就**不再是謊話**，故一併加回 usage。
  ★ 加回去不是選擇性的：usage 對帳守門員是**雙向**差集，程式一旦讀了
    `LIST_LIMIT` 而 usage 沒列，那道測試就會紅。護欄在這裡是驅動力而不只是防線。
"""

from ..collect import STATUS_UNAVAILABLE
from ..i18n import t
from .base import Section, blank, limited, note, subsection

__all__ = ["DEFAULT_LIST_LIMIT", "HOSTS_PATH", "IpRoutingSection", "RESOLV_PATH"]

# bash：LIST_LIMIT="${LIST_LIMIT:-50}"
DEFAULT_LIST_LIMIT = 50

RESOLV_PATH = "/etc/resolv.conf"
HOSTS_PATH = "/etc/hosts"


class IpRoutingSection(Section):
    """IP／路由／DNS／hosts／鄰居。

    ★ bash 這一段沒有表格版，是一連串「小標題＋原始輸出」，故 `table()` 回 None。
      這些輸出（`ip -br addr`、`ip route`）本身已經是對齊過的欄位，再套一層表格
      只會把它們的對齊打散。
    """

    # ★ 兩個檔案路徑做成參數而不是模組常數：bash 直接寫死 /etc/resolv.conf 與
    #   /etc/hosts，那在 shell 裡沒得選；Python 這邊若也寫死，測試就只能去真的
    #   讀開發機的 /etc——那不但驗不到「檔案不存在」那條分支，還會讓測試結果
    #   隨執行的機器改變。
    def __init__(self, ip_reader, textconf_reader, list_limit=None,
                 resolv_path=RESOLV_PATH, hosts_path=HOSTS_PATH):
        self.ip = ip_reader
        self.conf = textconf_reader
        self.list_limit = (DEFAULT_LIST_LIMIT if list_limit is None
                           else list_limit)
        self.resolv_path = resolv_path
        self.hosts_path = hosts_path

    def build(self):
        # ★ 先問 available()：bash 的第一件事就是 `command_exists ip`，沒有 ip
        #   時整段不印任何小標題，只印一句提示。
        if not self.ip.available():
            return {"available": False}
        return {
            "available": True,
            "addr4": self.ip.brief_addresses(4),
            "addr6": self.ip.brief_addresses(6),
            "route4": self.ip.routes(4),
            "route6": self.ip.routes(6),
            "resolv": self.conf.read_lines(self.resolv_path),
            "hosts": self.conf.read_lines(self.hosts_path),
            "neigh": self.ip.neighbours(),
        }

    def is_empty(self, data):
        # ★ 只有「沒有 ip 指令」才算空。其餘情形即使每一段都查無資料，bash 仍
        #   會把**七個**小標題印出來——「查過了，這台沒有 IPv6 路由」本身就是
        #   盤查結論，把它折疊掉會讓讀報告的人以為工具沒查。
        # [CHANGE] 2026-08-02 原本寫「六個」。實作是七段（IPv4 位址／IPv6 位址／
        #   IPv4 路由／IPv6 路由／DNS／hosts／鄰居），bash 1837-1877 也是七段；
        #   數字是我在委派規格裡寫錯的，受託方複核時指出。★ 註解裡的數字沒有
        #   任何東西在守，錯了只會誤導下一個人去「補上少掉的那一段」。
        return not data["available"]

    def empty_lines(self, data, ctx):
        return [note(t("net.no_ip_command"), ctx.palette)]

    def table(self, data, ctx):
        return None

    def blocks(self, data, ctx):
        lines = []
        lines.extend(self._part(t("iprouting.addr4"), data["addr4"], ctx))
        lines.extend(self._part(t("iprouting.addr6"), data["addr6"], ctx))
        lines.extend(self._part(t("iprouting.route4"), data["route4"], ctx))
        # bash 只對 IPv6 路由與鄰居套 print_limited——IPv4 路由沒有。
        # ★ 逐字沿用，不「順手」把 IPv4 也加上：那是規格差異不是改善，
        #   而且 IPv4 路由表通常短，加了只是讓兩邊畫面不同。
        lines.extend(self._part(t("iprouting.route6"), data["route6"], ctx,
                                unit=t("unit.routes")))
        lines.extend(self._part(t("iprouting.dns"), data["resolv"], ctx,
                                missing=t("iprouting.no_resolv")))
        lines.extend(self._part(t("iprouting.hosts"), data["hosts"], ctx,
                                missing=t("iprouting.no_hosts")))
        lines.extend(self._part(t("iprouting.neigh"), data["neigh"], ctx,
                                unit=t("unit.neighbours")))
        lines.append(blank())
        # bash 的註腳是兩行（第二行縮排四格對齊），故 i18n 也拆成兩個 key——
        # 一個含 \n 的 key 在這裡要再 split 一次，而那層轉換沒有人守。
        lines.append(t("iprouting.neigh_note1"))
        lines.append(t("iprouting.neigh_note2"))
        return lines

    def _part(self, title, result, ctx, unit=None, missing=None):
        """一個小標題＋它的內容。

        ★ bash 的版面是 `echo; subsection …; echo` ⇒ 標題前後各一行空白。
          第一段之前那個 `echo` 在 bash 是靠 view() 印的抬頭墊出來的，這裡由
          Section 的呼叫端負責，故本函式只在**標題前**留白。
        """
        lines = [blank()] + subsection(title, ctx.palette) + [blank()]
        if result["status"] == STATUS_UNAVAILABLE and missing is not None:
            lines.append(note(missing, ctx.palette))
            return lines
        body = result["lines"] or []
        if unit is not None:
            body = limited(body, self.list_limit, unit, ctx.palette)
        lines.extend(body)
        return lines
