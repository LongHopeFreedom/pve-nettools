# [CHANGE] 2026-08-01 新增：實體網卡與健康指標輸出區段（待辦 #8）。
"""實體網卡與健康指標的表格／區塊版輸出。"""

# [CHANGE] 2026-08-02 待辦 #26：STATUS_UNAVAILABLE 隨 _netconf_unavailable 一起移除。
# [CHANGE] 2026-08-03 待辦 #35：NIC 訊息必須依結構性成因分流，不能把所有
#          unavailable 都說成「未安裝」。
from ..collect import (FAILURE_EXIT_CODE, FAILURE_NOT_EXECUTABLE,
                       FAILURE_TIMEOUT, FAILURE_UNKNOWN)
from ..collect import STATUS_OK
from ..collect import ethtool as ethtool_collect
from ..collect.sysfs import sample_traffic
from ..i18n import t
from ..width import Table, pad
# [CHANGE] 2026-08-02 _TrailingTable 移到 base.py 並更名 DecoratedTable（多了
# leading）。本檔保留別名，因為 guest.py／netconf.py 原本就從這裡取用它——
# 一次改三個檔的 import 與「把元件放回版面層」是兩件事，別名讓兩者可以分開驗。
from .base import DecoratedTable as _TrailingTable
# [CHANGE] 2026-08-03 窄版標題改走共用 block_title，資料值則重用各 section 的
#          colorizer，讓寬窄版不再各自維護顏色判準。
from .base import DecoratedTable, Section, block_title, error, kv, note

__all__ = ["HealthSection", "NicSection", "link_state"]

# [CHANGE] 2026-08-01 媒介常數與翻譯鍵並非一對一；AUI/MII 明確降級成未知，
# 不以字串拼接產生不存在的 i18n key。
MEDIA_KEYS = {
    ethtool_collect.MEDIUM_RJ45: "media.rj45",
    ethtool_collect.MEDIUM_BACKPLANE: "media.backplane",
    ethtool_collect.MEDIUM_AUI: "media.unknown",
    ethtool_collect.MEDIUM_MII: "media.unknown",
    ethtool_collect.MEDIUM_DAC: "media.dac",
    ethtool_collect.MEDIUM_AOC: "media.aoc",
    ethtool_collect.MEDIUM_FIBER: "media.fiber",
}


def _value(value):
    return t("app.na") if value is None else str(value)


def _result_value(result, key):
    if not result or result.get("status") != STATUS_OK:
        return t("app.na")
    return _value((result.get("data") or {}).get(key))


def _medium_text(result):
    if not result or result.get("status") != STATUS_OK:
        return t("media.unknown")
    key = MEDIA_KEYS.get(result.get("medium"), "media.unknown")
    return t(key)


# [CHANGE] 2026-08-03 待辦 #41：受影響的欄位群。四句成因訊息原本各自把四個欄位
#          （速率／Duplex／媒介／驅動）一次全列為 N/A，而一次查詢失敗只證明它自己
#          那一組欄位取不到：
#            `ethtool <nic>`    → 速率、Duplex
#            `ethtool -i <nic>` → 驅動、匯流排位址
#          兩道是**獨立**指令，link 失敗時 driver 可能整組都拿得到，反之亦然。
#          ★ 上面刻意不逐字複製那句舊訊息：註解裡的複本會被日後的殘留掃描讀成
#            「還沒改乾淨」——修補的證據被當成缺陷，本專案已記過這條。
#          ★ **媒介刻意不在承諾之列**，而此前把它寫進去是逐字錯誤，兩個各自獨立的理由：
#            ① medium() 在 link 失敗時會改走 EEPROM（見 collect/ethtool.py 的優先序），
#               仍可能判出媒介——link 掛掉不等於媒介欄空白；
#            ② 媒介取不到值時顯示的是 media.unknown（「未知」），根本不是 N/A。
SCOPE_LINK = "nic.ethtool_scope_link"
SCOPE_DRIVER = "nic.ethtool_scope_driver"
SCOPE_ORDER = (SCOPE_LINK, SCOPE_DRIVER)


def _scope_text(scopes):
    """依固定順序列出受影響的欄位群。

    ★ 順序取自 SCOPE_ORDER 而不是 set 的迭代順序：set 不保證順序，同一份輸入可能
      印出兩種排列，而這份輸出是要拿去跨機器比對的。
    """
    return t("nic.ethtool_scope_sep").join(
        t(key) for key in SCOPE_ORDER if key in scopes)


# [CHANGE] 2026-08-03 待辦 #35 補正：彙整多次 ethtool 查詢的失敗成因。
# [CHANGE] 2026-08-03 待辦 #41：回「成因 → 受影響欄位群」的對映而非單純的成因集合。
def _ethtool_failures(link_info=None, driver_info=None):
    """回 {成因: {受影響欄位群 key}}；查詢成功者不貢獻成因，成因缺漏者計為 unknown。

    ★ **回 set 而不是單一值**：同一張網卡的 `ethtool <nic>` 與 `ethtool -i <nic>`
      是兩道獨立指令，可能各自以不同原因失敗。壓成一個值就會讓其中一種原因
      永遠不被說出來——那正是待辦 #35 本身要修的病（把多種失敗壓成一種）。

    ★ `status` 非 unavailable 即視為這一次查詢沒有失敗，不看它的 failure 欄：
      成功的查詢即使帶著殘留的 failure 值也不該貢獻成因。

    ★★ **`medium()` 刻意不納入**，這是判斷不是遺漏。code review 曾建議把
      `ethtool -m` 也算進來，理由是「它同樣可能單獨失敗」——那句話對，但漏了
      一件事：`module_eeprom()` 的 docstring 逐字寫著「EEPROM **無模組**或權限
      不足很常見」。**空的 SFP 槽讀不到 EEPROM 是正常狀態**，而 `ethtool -m`
      對「沒插模組」與「有模組但沒權限」都回非零離開碼（同樣是 EXIT_CODE），
      成因欄分不出來。
      ⇒ 納入的話，**每一張沒插模組的網卡都會報「ethtool 執行失敗」**。
      那是假陽性，而假陽性會讓使用者學會忽略這三句話——本專案已經記過這條
      因果鏈：假陽性 → 沒人信 → 判準等同不存在。
    """
    causes = {}
    for result, scope in ((link_info, SCOPE_LINK),
                          (driver_info, SCOPE_DRIVER)):
        if not result:
            continue
        if result.get("status") != ethtool_collect.STATUS_UNAVAILABLE:
            continue
        cause = result.get("failure") or FAILURE_UNKNOWN
        causes.setdefault(cause, set()).add(scope)
    return causes


# [CHANGE] 2026-08-03 新增：NIC 區段與 LED picker 共用唯一的 link 文字／顏色判定，
#          避免兩個畫面對同一張卡顯示不同狀態或顏色。
def link_state(link):
    """回傳 link 三態的翻譯文字與語意顏色。"""
    if link is True:
        return t("link.up"), "green"
    if link is False:
        return t("link.down"), "red"
    return t("link.unknown"), "yellow"


# [CHANGE] 2026-08-02 待辦 #26：移除 _netconf_unavailable／_autostart_text／
# _comment_text 三個只服務 nic.autostart／nic.comment 的輔助函式。
# 移除的理由與那兩欄相同（見 NicSection.HEADERS 的註解）：bash 版的
# render_physical_nics 從不讀 /etc/network/interfaces。
# ★ 第 24 項 AutostartSection 有它自己的三態判斷（render/netconf.py），
#   不受此處影響——突變條目 Z、H 守的是那一邊。


def _pair(left_key, left_value, right_key, right_value, key_width=8):
    """組成兩組鍵值；只有左值補白，行尾右值不補白。"""
    # [CHANGE] 2026-08-02 分隔符改走 i18n（見 i18n.py 的 app.kv_sep）。
    sep = t("app.kv_sep")
    return "%s%s%s  %s%s%s" % (
        pad(left_key, key_width), sep, pad(str(left_value), 9),
        right_key, sep, right_value)


class NicSection(Section):
    """實體網卡基本狀態。"""

    # [CHANGE] 2026-08-02 待辦 #26：欄位回到與 bash 版逐欄等價的 11 欄。
    #
    # ★ 原本多出 nic.autostart／nic.comment 兩欄。它們的來歷見本檔上方註解：
    #   委派規格的 scope 表列了 NetconfReader 而欄位清單沒有任何欄位用它，
    #   受託方據此判「依賴多餘」，當時我判「欄位漏了」而補上這兩欄。
    #   ★★ 以「Python 版 MUST 與 bash 版等價」為準，**受託方當時是對的**：
    #   bash 的 render_physical_nics 從不讀 /etc/network/interfaces，這兩欄
    #   是 Python 版憑空多出來的。使用者 2026-08-02 裁決回歸等價，故移除，
    #   NicSection 也不再依賴 NetconfReader。
    # ★ 附帶效果正是使用者回報的症狀：13 欄的表格在一般寬度的終端放不下而
    #   整個降級成逐張區塊，看起來就與 bash 版「完全不一樣」。
    HEADERS = (
        "nic.iface", "nic.mac", "nic.link", "nic.speed", "nic.duplex",
        "nic.mtu", "nic.media", "nic.rx", "nic.tx", "nic.driver", "nic.pci",
    )

    def __init__(self, sysfs_reader, ethtool_reader,
                 sample_seconds=3, sleep_fn=None, traffic=None):
        self.sysfs = sysfs_reader
        self.ethtool = ethtool_reader
        self.sample_seconds = sample_seconds
        self.sleep_fn = sleep_fn
        self.traffic = traffic

    def build(self):
        nics = self.sysfs.physical_nics()
        traffic = self.traffic
        if traffic is None and nics:
            traffic = sample_traffic(
                self.sysfs, nics, seconds=self.sample_seconds,
                sleep_fn=self.sleep_fn)
        traffic = traffic or {}

        rows = []

        for iface in nics:
            link = self.sysfs.carrier(iface)
            link_text, _link_colour = link_state(link)
            link_info = self.ethtool.link_info(iface)
            driver_info = self.ethtool.driver_info(iface)
            # [CHANGE] 2026-08-03 待辦 #35：成因缺漏時採保守的 unknown，避免對使用者
            #          做出「未安裝」這個無證據的斷言。
            # [CHANGE] 2026-08-03 待辦 #35 補正：成因 MUST 彙整**每一次 ethtool 查詢**。
            # ★ 原本只取 link_info 的成因。但這一列實際會跑兩道**獨立**指令：
            #   `ethtool <nic>` 與 `ethtool -i <nic>`——不同 argv、不同快取鍵、
            #   各自的離開碼，任何一個都可能單獨失敗。
            #   ⇒ `ethtool -i` 單獨失敗時，Driver／PCI 欄顯示 N/A，而**一句警示
            #   都不會出現**：使用者看到空欄位卻拿不到任何線索。
            ethtool_failures = _ethtool_failures(link_info, driver_info)
            delta = traffic.get(iface, (0, 0))
            rx_active = bool(delta[0])
            tx_active = bool(delta[1])
            rows.append({
                "cells": [
                    iface, _value(self.sysfs.mac(iface)), link_text,
                    _result_value(link_info, "speed"),
                    _result_value(link_info, "duplex"),
                    _value(self.sysfs.mtu(iface)),
                    _medium_text(self.ethtool.medium(iface)),
                    t("traffic.yes") if rx_active else t("traffic.no"),
                    t("traffic.yes") if tx_active else t("traffic.no"),
                    _result_value(driver_info, "driver"),
                    _result_value(driver_info, "bus_info"),
                ],
                "link": link,
                "rx_active": rx_active,
                "tx_active": tx_active,
                "ethtool_failures": ethtool_failures,
            })
        return rows

    def _notes(self, data, ctx):
        # [CHANGE] 2026-08-03 待辦 #35：三種成因三句話，**每一句的斷言強度都要與
        #          手上的證據相符**：
        #            not_executable → 「未安裝」（run_command 拋 OSError 才會有）
        #            exit_code      → 「已安裝但執行失敗」（跑得起來才會有離開碼）
        #            其餘／unknown  → 只說讀取失敗，**不斷言安裝與否**
        #
        # ★ 最後一類原本併進 exit_code 那句，而那句逐字說「ethtool 已安裝」——
        #   成因未知時說「已安裝」與說「未安裝」一樣是沒有證據的斷言，正是本待辦
        #   要修的病。修一個方向的說謊時，MUST NOT 在另一個方向再犯一次。
        # ★ 三者可並存（多張網卡成因不同，或**同一張網卡的不同查詢**各自以不同
        #   原因失敗），故用三個獨立的 if 而非 elif。
        # [CHANGE] 2026-08-03 待辦 #41：彙整成 {成因: {受影響欄位群}}，兩層都要合併。
        failures = {}
        for row in data:
            for cause, scopes in row["ethtool_failures"].items():
                failures.setdefault(cause, set()).update(scopes)
        lines = []
        if FAILURE_NOT_EXECUTABLE in failures:
            lines.append(error(t("nic.ethtool_missing"), ctx.palette))
        if FAILURE_EXIT_CODE in failures:
            lines.append(error(t("nic.ethtool_failed"), ctx.palette))
        # [CHANGE] 2026-08-03 待辦 #48：逾時獨立一句。
        if FAILURE_TIMEOUT in failures:
            lines.append(error(t("nic.ethtool_timeout"), ctx.palette))
        if set(failures) - {FAILURE_NOT_EXECUTABLE, FAILURE_EXIT_CODE,
                            FAILURE_TIMEOUT}:
            lines.append(error(t("nic.ethtool_unknown"), ctx.palette))
        # [CHANGE] 2026-08-03 待辦 #41：受影響的欄位改由**實際失敗的那幾次查詢**決定，
        #          而不是四句話各自寫死一份清單。寫死的那份會在只有一邊失敗時說謊。
        if failures:
            affected = set()
            for scopes in failures.values():
                affected |= scopes
            lines.append(note(t("nic.ethtool_affected",
                                fields=_scope_text(affected)), ctx.palette))
        lines.append(note(t("nic.traffic_note", sec=self.sample_seconds),
                          ctx.palette))
        return lines

    def table(self, data, ctx):
        table = DecoratedTable([t(key) for key in self.HEADERS],
                               trailing=self._notes(data, ctx))
        for row in data:
            table.add(row["cells"])
        return table

    def blocks(self, data, ctx):
        lines = []
        paint = self.colorizer(data, ctx)
        for row_index, row in enumerate(data):
            cells = row["cells"]
            lines.append(block_title(cells[0], ctx.palette))
            lines.append(_pair(t("nic.mac"), paint(row_index, 1, cells[1]),
                               t("nic.link"), paint(row_index, 2, cells[2])))
            lines.append(_pair(t("nic.duplex"), paint(row_index, 4, cells[4]),
                               t("nic.speed"), paint(row_index, 3, cells[3])))
            lines.append(_pair(t("nic.mtu"), paint(row_index, 5, cells[5]),
                               t("nic.media"), paint(row_index, 6, cells[6])))
            lines.append(kv("%s/%s" % (t("nic.rx"), t("nic.tx")),
                            "%s / %s" % (paint(row_index, 7, cells[7]),
                                          paint(row_index, 8, cells[8])),
                            key_width=8))
            lines.append(_pair(t("nic.driver"), paint(row_index, 9, cells[9]),
                               t("nic.pci"), paint(row_index, 10, cells[10])))
            lines.append("")
        return lines + self._notes(data, ctx)

    def colorizer(self, data, ctx):
        def paint(row_index, col_index, text):
            row = data[row_index]
            if col_index == 2:
                _link_text, link_colour = link_state(row["link"])
                return ctx.paint(text, link_colour)
            if col_index == 7 and row["rx_active"]:
                return ctx.paint(text, "green")
            if col_index == 8 and row["tx_active"]:
                return ctx.paint(text, "green")
            return text
        return paint

    def empty_lines(self, data, ctx):
        return [error(t("nic.none_found"), ctx.palette)]


class HealthSection(Section):
    """實體網卡健康計數器。"""

    HEADERS = (
        "nic.iface", "health.state", "health.carrier_changes", "health.autoneg",
        "health.rx_err", "health.rx_drop", "health.tx_err", "health.tx_drop",
        "health.crc", "health.numa", "health.firmware",
    )

    def __init__(self, sysfs_reader, ethtool_reader):
        self.sysfs = sysfs_reader
        self.ethtool = ethtool_reader

    def build(self):
        rows = []
        for iface in self.sysfs.physical_nics():
            link_info = self.ethtool.link_info(iface)
            driver_info = self.ethtool.driver_info(iface)
            counters = self.sysfs.error_counters(iface)
            raw = [
                self.sysfs.operstate(iface), self.sysfs.carrier_changes(iface),
                ((link_info.get("data") or {}).get("auto_negotiation")
                 if link_info.get("status") == STATUS_OK else None),
                counters.get("rx_errors"), counters.get("rx_dropped"),
                counters.get("tx_errors"), counters.get("tx_dropped"),
                counters.get("rx_crc_errors"), self.sysfs.numa_node(iface),
                ((driver_info.get("data") or {}).get("firmware_version")
                 if driver_info.get("status") == STATUS_OK else None),
            ]
            rows.append({
                "cells": [iface] + [_value(value) for value in raw],
                "flapping": self.sysfs.is_flapping(iface),
                "counters": raw[3:8],
            })
        return rows

    def _notes(self, ctx):
        return [note(t("health.note_flap"), ctx.palette),
                note(t("health.note_crc"), ctx.palette)]

    def table(self, data, ctx):
        table = _TrailingTable([t(key) for key in self.HEADERS], self._notes(ctx))
        for row in data:
            table.add(row["cells"])
        return table

    def blocks(self, data, ctx):
        lines = []
        paint = self.colorizer(data, ctx)
        for row_index, row in enumerate(data):
            cells = row["cells"]
            lines.append(block_title(cells[0], ctx.palette))
            lines.append(_pair(t("health.state"), paint(row_index, 1, cells[1]),
                               t("health.carrier_changes"),
                               paint(row_index, 2, cells[2])))
            lines.append(kv(t("health.autoneg"), paint(row_index, 3, cells[3]),
                            key_width=8))
            lines.append(_pair(t("health.rx_err"), paint(row_index, 4, cells[4]),
                               t("health.rx_drop"), paint(row_index, 5, cells[5])))
            lines.append(_pair(t("health.tx_err"), paint(row_index, 6, cells[6]),
                               t("health.tx_drop"), paint(row_index, 7, cells[7])))
            lines.append(_pair(t("health.crc"), paint(row_index, 8, cells[8]),
                               t("health.numa"), paint(row_index, 9, cells[9])))
            lines.append(kv(t("health.firmware"), paint(row_index, 10, cells[10]),
                            key_width=8))
            lines.append("")
        return lines + self._notes(ctx)

    def colorizer(self, data, ctx):
        def paint(row_index, col_index, text):
            row = data[row_index]
            if col_index == 2 and row["flapping"]:
                return ctx.paint(text, "yellow")
            if 4 <= col_index <= 7:
                value = row["counters"][col_index - 4]
                if value is not None and value > 0:
                    return ctx.paint(text, "yellow")
            if col_index == 8:
                value = row["counters"][4]
                if value is not None and value > 0:
                    return ctx.paint(text, "red")
            return text
        return paint

    def empty_lines(self, data, ctx):
        return [note(t("nic.none_found"), ctx.palette)]
