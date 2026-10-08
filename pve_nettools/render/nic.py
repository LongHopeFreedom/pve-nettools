# [CHANGE] 2026-08-01 新增：實體網卡與健康指標輸出區段。
"""實體網卡與健康指標的表格／區塊版輸出。"""

# [CHANGE] 2026-08-02：STATUS_UNAVAILABLE 隨 _netconf_unavailable 一起移除。
# [CHANGE] 2026-08-03：NIC 訊息必須依結構性成因分流，不能把所有
#          unavailable 都說成「未安裝」。
from ..collect import (FAILURE_EXIT_CODE, FAILURE_NOT_EXECUTABLE,
                       FAILURE_TIMEOUT, FAILURE_UNKNOWN)
from ..collect import STATUS_OK, STATUS_UNAVAILABLE
from ..collect import ethtool as ethtool_collect
# [CHANGE] 2026-10-06 v03.018.000：型號字串的組法在 collect/lspci.py，這裡只取用。
from ..collect import lspci as lspci_collect
# [CHANGE] 2026-08-25 探測略過成因：呈現層要對「已啟用」「被接管」「探測關閉」
#          說不同的話，故取用命名常數而不是比對字串。
from ..collect.linkprobe import SKIP_DISABLED, SKIP_ENSLAVED
from ..collect import bond as bond_collect
# [CHANGE] 2026-10-08 v03.021.000：選單 1 分區（客體機介面不列、改摘要）所需。
from ..collect.bridge import is_guest_iface, physical_uplinks
from ..collect.pve import guest_nic_counts
from ..collect.sysfs import (DEFAULT_SAMPLE_SECONDS, bond_traffic_conflicts,
                             sample_traffic)
from ..i18n import t
from ..width import Table, pad
# [CHANGE] 2026-08-02 _TrailingTable 移到 base.py 並更名 DecoratedTable（多了
# leading）。本檔保留別名，因為 guest.py／netconf.py 原本就從這裡取用它——
# 一次改三個檔的 import 與「把元件放回版面層」是兩件事，別名讓兩者可以分開驗。
from .base import DecoratedTable as _TrailingTable
# [CHANGE] 2026-08-03 窄版標題改走共用 block_title，資料值則重用各 section 的
#          colorizer，讓寬窄版不再各自維護顏色判準。
from .base import (DecoratedTable, Section, block_title, error, kv, note,
                   subsection)

__all__ = ["HealthSection", "NicSection", "link_state"]

# [CHANGE] 2026-08-04：每個已辨識媒介都有自己的翻譯鍵；仍用顯式對照，
# 不以字串拼接產生可能不存在的 i18n key。
MEDIA_KEYS = {
    ethtool_collect.MEDIUM_RJ45: "media.rj45",
    ethtool_collect.MEDIUM_BACKPLANE: "media.backplane",
    ethtool_collect.MEDIUM_AUI: "media.aui",
    ethtool_collect.MEDIUM_MII: "media.mii",
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


# [CHANGE] 2026-10-07 v03.020.000：速率／Duplex 的三態顯示。
def _is_unknown_token(value):
    """ethtool 對「沒有協商出值」印的是 `Unknown!`（速率）與 `Unknown! (255)`（Duplex）。"""
    return str(value).strip().lower().startswith("unknown")


def _link_attr_value(result, key, link):
    """速率／Duplex 欄：把 ethtool 的 `Unknown!` 依 Link 狀態換成誠實的字樣。

    三態（前兩種為 2026-10-07 指定的顯示，其餘組合為實作時的保守選擇）：
        N/A   查詢失敗或欄位不存在（維持原義）
        —     確定未接線（link is False）且 ethtool 回 Unknown：沒有 link 就沒有
              協商值，「不適用」；英文 `-`
        未知  其餘 Unknown（已接線、或 Link 本身未知）：ethtool 說不出來
    Link 本身未知（None）時採「未知」而不採「—」：「—」等於斷言未接線，
    而手上沒有這個證據。
    非 Unknown 的值（例如未接線卻有真值）原樣顯示，不因 Link 狀態隱藏證據。
    """
    usable = bool(result) and result.get("status") == STATUS_OK
    value = (result.get("data") or {}).get(key) if usable else None
    if value is None:
        return t("app.na")
    if _is_unknown_token(value):
        return t("app.dash") if link is False else t("app.unknown")
    return str(value)


def _medium_text(result):
    if not result or result.get("status") != STATUS_OK:
        return t("media.unknown")
    key = MEDIA_KEYS.get(result.get("medium"), "media.unknown")
    return t(key)


# [CHANGE] 2026-08-03：受影響的欄位群。四句成因訊息原本各自把四個欄位
#          （速率／Duplex／媒介／驅動）一次全列為 N/A，而一次查詢失敗只證明它自己
#          那一組欄位取不到：
#            `ethtool <nic>`    → 速率、Duplex
#            `ethtool -i <nic>` → 驅動、匯流排位址
#          兩道是**獨立**指令，link 失敗時 driver 可能整組都拿得到，反之亦然。
#          上面刻意不逐字複製那句舊訊息：註解裡的複本會被日後的殘留掃描讀成
#            「還沒改乾淨」——修補的證據被當成缺陷，本專案已記過這條。
#          **媒介刻意不在承諾之列**，而此前把它寫進去是逐字錯誤，兩個各自獨立的理由：
#            ① medium() 在 link 失敗時會改走 EEPROM（見 collect/ethtool.py 的優先序），
#               仍可能判出媒介——link 掛掉不等於媒介欄空白；
#            ② 媒介取不到值時顯示的是 media.unknown（「未知」），根本不是 N/A。
SCOPE_LINK = "nic.ethtool_scope_link"
SCOPE_DRIVER = "nic.ethtool_scope_driver"
SCOPE_ORDER = (SCOPE_LINK, SCOPE_DRIVER)


def _scope_text(scopes):
    """依固定順序列出受影響的欄位群。

    順序取自 SCOPE_ORDER 而不是 set 的迭代順序：set 不保證順序，同一份輸入可能
      印出兩種排列，而這份輸出是要拿去跨機器比對的。
    """
    return t("nic.ethtool_scope_sep").join(
        t(key) for key in SCOPE_ORDER if key in scopes)


# [CHANGE] 2026-08-03 補正：彙整多次 ethtool 查詢的失敗成因。
# [CHANGE] 2026-08-03：回「成因 → 受影響欄位群」的對映而非單純的成因集合。
def _ethtool_failures(link_info=None, driver_info=None):
    """回 {成因: {受影響欄位群 key}}；查詢成功者不貢獻成因，成因缺漏者計為 unknown。

    **回 set 而不是單一值**：同一張網卡的 `ethtool <nic>` 與 `ethtool -i <nic>`
      是兩道獨立指令，可能各自以不同原因失敗。壓成一個值就會讓其中一種原因
      永遠不被說出來——那正是這個修正本身要修的病（把多種失敗壓成一種）。

    `status` 非 unavailable 即視為這一次查詢沒有失敗，不看它的 failure 欄：
      成功的查詢即使帶著殘留的 failure 值也不該貢獻成因。

    **`medium()` 刻意不納入**，這是判斷不是遺漏。code review 曾建議把
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


# [CHANGE] 2026-08-02：移除 _netconf_unavailable／_autostart_text／
# _comment_text 三個只服務 nic.autostart／nic.comment 的輔助函式。
# 移除的理由與那兩欄相同（見 NicSection.HEADERS 的註解）：bash 版的
# render_physical_nics 從不讀 /etc/network/interfaces。
# 第 24 項 AutostartSection 有它自己的三態判斷（render/netconf.py），
#   不受此處影響——突變條目 Z、H 守的是那一邊。


# [CHANGE] 2026-08-25 探測結果的彙整與連接。
#
# 從 NicSection._probe_notes() 抽出：加了探測訊息之後那個方法到了 68 行，
#   超過單一函式 ≤50 行的上限。抽出的是**收集**這一半，留在方法裡的是
#   **措辭**——兩者的變動理由不同（前者隨探測結構走，後者隨 i18n 走）。
def _join(names):
    """網卡名之間的分隔。走 i18n 而不是寫死「、」：英文語系用逗號加空格。"""
    return t("nic.ethtool_scope_sep").join(names)


# [CHANGE] 2026-10-06 v03.018.000：型號列與型號取不到的成因說明。
#
# 型號放在 row["model"]，**不放進 cells**：HEADERS 維持 11 欄是 2026-08-02 決定的
#   （13 欄在一般終端放不下，整張表會降級成區塊）。表格版把相同型號的網卡合併
#   成表下方一行，區塊版則是每張實體卡一行 key/value。
# row["model"] 為 None ＝「不查、不顯示」（虛擬介面，或沒給 lspci reader）；
#   為 N/A 字串＝「查了但取不到」。兩者不得合併：前者不該出現在型號列，
#   後者要讓使用者看見「這張卡沒查到」。
MODEL_NO_ADDRESS = "no_address"   # 取不到 PCI 位址，根本沒跑 lspci
MODEL_EMPTY = "empty"             # lspci 跑了、離開碼 0，但沒有可辨識的型號

_LSPCI_FAILURE_KEYS = (
    (FAILURE_NOT_EXECUTABLE, "nic.lspci_missing"),
    (FAILURE_EXIT_CODE, "nic.lspci_failed"),
    (FAILURE_TIMEOUT, "nic.lspci_timeout"),
)


def _model_lines(data):
    """表格版的型號列：相同型號合併成一行，順序依網卡首次出現順序。"""
    groups = []
    for row in data:
        model = row.get("model")
        if model is None:
            continue
        for entry in groups:
            if entry[0] == model:
                entry[1].append(row["cells"][0])
                break
        else:
            groups.append((model, [row["cells"][0]]))
    return [t("nic.model_line", nics=_join(names), model=model)
            for model, names in groups]


def _model_notes(data, ctx):
    """型號取不到的成因：每種成因**只說一句**，不是每張卡一句。

    「lspci 未安裝」與「有裝但失敗」分開說，與 ethtool 那組同一個立論：給錯了，
      使用者會去裝一個已經裝好的套件。
    """
    causes = {}
    for row in data:
        cause = row.get("model_failure")
        if cause is not None:
            causes.setdefault(cause, []).append(row["cells"][0])
    lines = []
    for cause, key in _LSPCI_FAILURE_KEYS:
        if cause in causes:
            lines.append(error(t(key), ctx.palette))
    known = set(cause for cause, _key in _LSPCI_FAILURE_KEYS)
    known.update((MODEL_NO_ADDRESS, MODEL_EMPTY))
    if set(causes) - known:
        lines.append(error(t("nic.lspci_unknown"), ctx.palette))
    if MODEL_EMPTY in causes:
        lines.append(note(t("nic.lspci_empty",
                            nics=_join(causes[MODEL_EMPTY])), ctx.palette))
    if MODEL_NO_ADDRESS in causes:
        lines.append(note(t("nic.lspci_no_address",
                            nics=_join(causes[MODEL_NO_ADDRESS])), ctx.palette))
    return lines


def _probe_state(data):
    """把每一列的探測結果彙整成七種成因的網卡清單。

    七個獨立的清單而不是一個「有沒有問題」的旗標：一台主機上同時出現
      「兩張探測成功、一張權限不足、一張被 bond 接管」是正常的，合成單一狀態
      就說不出這三件事。
    """
    state = {
        "probed": [], "unrestored": [], "denied": [], "unavailable": [],
        "timed_out": [], "enslaved": [], "disabled": False,
    }
    for row in data:
        probe = row.get("probe")
        if not probe:
            continue
        nic = probe["nic"]
        skipped = probe["skipped"]
        if skipped == SKIP_DISABLED:
            state["disabled"] = True
        elif skipped == SKIP_ENSLAVED:
            state["enslaved"].append("%s → %s" % (nic, probe["master"]))
        elif probe["status"] == STATUS_UNAVAILABLE:
            # 成因分流：離開碼代表 `ip` 跑起來了但被拒絕（幾乎都是非 root）；
            #   其餘不斷言原因，只說沒做成——與 ethtool 那組訊息同一個判準。
            key = ("denied" if probe["failure"] == FAILURE_EXIT_CODE
                   else "unavailable")
            state[key].append(nic)
        elif probe["probed"]:
            state["probed"].append(nic)
            if probe["restored"] is False:
                state["unrestored"].append(nic)
            if probe["timed_out"]:
                state["timed_out"].append(nic)
    return state


# [CHANGE] 2026-10-06 v03.017.000：RX/TX 欄在「有流量」之後附上取樣期間增加的
#          位元組數。
# WHY: 只有「有／無」兩種值時，取樣窗內 1 個封包與 1 GB 在畫面上完全同形，
#      稀疏流量的介面也無從與閒置介面區分。
_BYTE_UNITS = ("KB", "MB", "GB", "TB")


def format_bytes(count):
    """位元組數轉成人讀的字串；1 KB＝1024 B，未滿 1 KB 顯示精確值。"""
    if count < 1024:
        return "%d B" % count
    value = float(count)
    unit = _BYTE_UNITS[0]
    for unit in _BYTE_UNITS:
        value /= 1024.0
        # 以四捨五入後的值判斷要不要再進一級，免得印出「1024.0 KB」。
        if round(value, 1) < 1024 or unit == _BYTE_UNITS[-1]:
            break
    return "%.1f %s" % (value, unit)


def _traffic_text(active, delta):
    """RX／TX 欄的文字。

    有無流量仍由呼叫端的 rx_active／tx_active 決定，這裡只負責附上數值——
      著色也看那兩個旗標，文字與顏色因此不會各說各話。
    無流量不附「0 B」：那一格要說的是「計數器沒動」，多一個 0 只是加寬表格。
    """
    if not active:
        return t("traffic.no")
    return "%s %s" % (t("traffic.yes"), format_bytes(delta))


# [CHANGE] 2026-10-06 v03.019.000 新增：bond 與成員取樣結果矛盾的說明列。
def _seconds_text(value):
    return t("app.na") if value is None else "%.3f" % value


def _conflict_notes(data, ctx):
    """每個矛盾（bond × 方向）一行；沒有矛盾時回空 list，完全不印。"""
    lines = []
    for row in data:
        for item in row["traffic_conflicts"]:
            lines.append(note(t(
                "nic.traffic_conflict", bond=item["bond"],
                direction=t("nic.%s" % item["direction"]),
                members=", ".join(item["members"]),
                bond_bytes=format_bytes(item["bond_delta"]),
                member_bytes=format_bytes(item["members_delta"]),
                first=_seconds_text(item["first"]),
                second=_seconds_text(item["second"])), ctx.palette))
    return lines


# [CHANGE] 2026-10-08 v03.021.000：選單 1 分區與橋接關係副列。
#
# 橋接關係放 row["relation"]，**不放進 cells**（理由同型號列：HEADERS 維持 11 欄，
#   2026-08-02 決定，13 欄曾使整張表降級成區塊）。
#   row 沒有 "relation" 鍵（舊版建構、報告）或為 None ＝ 不顯示副列。
ZONE_PHYSICAL = "physical"
ZONE_VIRTUAL = "virtual"
REL_BELONGS = "belongs"
REL_MEMBERS = "members"


def _relation_text(relation):
    """("belongs", master) → 「屬於 vmbr0」；("members", [..]) → 「成員：a, b」（空＝破折號）。"""
    kind, value = relation
    if kind == REL_BELONGS:
        return t("nic.rel_belongs", master=value)
    return t("nic.rel_members", members=_join(value) if value else t("app.dash"))


def _relation_lines(rows):
    """表格版的橋接副列：每個有關係的介面一行，順序依列順序。"""
    return [t("nic.rel_line", nic=row["cells"][0],
              relation=_relation_text(row["relation"]))
            for row in rows if row.get("relation") is not None]


# [CHANGE] 2026-10-08 v03.023.000：虛擬介面表的「實體網卡」。
#
# 只在互動畫面（zoned=True）的虛擬介面列上有 row["uplinks"]（實體網卡名稱清單，可為空）；
# 沒有這個鍵（實體卡、舊版建構、完整報告）一律不顯示。欄位插在「媒介」之後；HEADERS 與
# row["cells"] 維持 11 欄，加欄只發生在畫面組表的那一刻。
UPLINK_COLUMN_INDEX = 7      # 插在媒介（索引 6）之後
UPLINK_SEP = ", "


def _uplink_text(names):
    return UPLINK_SEP.join(names) if names else t("app.dash")


def _uplink_lines(rows):
    """十一欄表格版的表下行：放不下新欄時，把同一份資訊放在表下。"""
    return [t("nic.uplink_line", nic=row["cells"][0],
              uplinks=_uplink_text(row["uplinks"]))
            for row in rows if row.get("uplinks") is not None]


def _pair(left_key, left_value, right_key, right_value, key_width=8):
    """組成兩組鍵值；只有左值補白，行尾右值不補白。"""
    # [CHANGE] 2026-08-02 分隔符改走 i18n（見 i18n.py 的 app.kv_sep）。
    sep = t("app.kv_sep")
    return "%s%s%s  %s%s%s" % (
        pad(left_key, key_width), sep, pad(str(left_value), 9),
        right_key, sep, right_value)


class NicSection(Section):
    """實體網卡基本狀態。"""

    # [CHANGE] 2026-08-02：欄位回到與 bash 版逐欄等價的 11 欄。
    #
    # 原本多出 nic.autostart／nic.comment 兩欄。它們的來歷見本檔上方註解：
    #   規格的 scope 表列了 NetconfReader 而欄位清單沒有任何欄位用它，
    #   實作據此判「依賴多餘」，當時判成「欄位漏了」而補上這兩欄。
    #   以「Python 版必須與 bash 版等價」為準，**「依賴多餘」的判斷是對的**：
    #   bash 的 render_physical_nics 從不讀 /etc/network/interfaces，這兩欄
    #   是 Python 版憑空多出來的。2026-08-02 決定回歸等價，故移除，
    #   NicSection 也不再依賴 NetconfReader。
    # 附帶效果正是使用者回報的症狀：13 欄的表格在一般寬度的終端放不下而
    #   整個降級成逐張區塊，看起來就與 bash 版「完全不一樣」。
    HEADERS = (
        "nic.iface", "nic.mac", "nic.link", "nic.speed", "nic.duplex",
        "nic.mtu", "nic.media", "nic.rx", "nic.tx", "nic.driver", "nic.pci",
    )

    # [CHANGE] 2026-08-25 新增 prober：admin-down 的網卡讀不到 carrier，要先
    #          短暫啟用才判得出有沒有接線。prober 為 None 時退回原本的純讀行為，
    #          既有測試因此不必全部改寫，也讓「不要碰主機」永遠是一個可選路徑。
    def __init__(self, sysfs_reader, ethtool_reader,
                 sample_seconds=DEFAULT_SAMPLE_SECONDS, sleep_fn=None,
                 traffic=None, prober=None, lspci_reader=None,
                 bond_reader=None, clock=None, guest_reader=None, zoned=False,
                 ip_reader=None):
        self.sysfs = sysfs_reader
        self.ethtool = ethtool_reader
        # [CHANGE] 2026-10-06 v03.018.000：lspci_reader 為 None ⇒ 不查、不顯示型號列，
        #          既有測試以舊簽章建構 NicSection 因此不必改寫。
        self.lspci = lspci_reader
        # [CHANGE] 2026-10-06 v03.019.000：bond_reader 為 None ⇒ 不知道成員，讀取順序
        #          維持原樣、也不做矛盾註記，既有測試以舊簽章建構因此不必改寫。
        self.bond = bond_reader
        self.clock = clock
        self.sample_seconds = sample_seconds
        self.sleep_fn = sleep_fn
        self.traffic = traffic
        self.prober = prober
        # [CHANGE] 2026-10-08 v03.021.000：zoned=True ＝ 選單 1 的「實體／虛擬」分區版面：
        #          客體機介面（tap／veth／fwbr／fwpr／fwln）不列，改在表下加一行摘要；
        #          橋接關係以副列呈現。預設 False ＝ 與舊版逐位元相同（完整報告走預設，
        #          已決定這一版報告輸出不動）。guest_reader 只供摘要行使用。
        self.guest = guest_reader
        self.zoned = zoned
        # [CHANGE] 2026-10-08 v03.023.000：ip_reader 只供 VLAN 子介面查底層介面；
        #          為 None ⇒ VLAN 的「實體網卡」顯示破折號，其餘不受影響。
        self.ip = ip_reader

    def build(self):
        # [CHANGE] 2026-08-27 母體擴為 traffic_nics()：納入 bond／vmbr／VLAN。
        nics = self.sysfs.traffic_nics()
        # [CHANGE] 2026-10-08 v03.021.000：顯示層過濾，**只動 nics（顯示與取樣母體）**。
        # 下方探測母體仍是 physical_nics()，與此處過濾無關——兩者不得合併
        #    （理由見下方 probe 註解：探測會把介面 admin-up）。
        if self.zoned:
            nics = self._without_guest_ifaces(nics)
        # [CHANGE] 2026-08-25 探測必須排在流量取樣**之前**。
        #
        # 順序在這裡有語意：取樣是「等 N 秒看計數器有沒有動」，而探測會把卡
        #   up 起來。先取樣的話，admin-down 的卡在取樣期間還沒被啟用，RX/TX 必然
        #   為 0——那個 0 會被讀成「這張卡沒有流量」，但它其實是「這張卡當時還
        #   關著」。兩者在畫面上完全同形。
        # 反過來說，探測完**還原成 down** 之後那張卡一樣不會有流量，所以本
        #   順序並不能讓 admin-down 的卡量到真實流量——它只是讓「沒有流量」這件事
        #   對所有卡有一致的成因。真要量 admin-down 卡的流量得讓它保持啟用，
        #   那超出本次修法的射程，留待日後處理。
        # [CHANGE] 2026-08-27 探測母體**釘死在實體卡**，不隨 nics 擴大。
        # 這是安全關鍵，不是最佳化：probe 會把介面 admin-up 再還原。
        #   對 vmbr0 或 bond0 做這件事會**斷掉 host 的網路**——而那正是
        #   使用者跑這支工具時唯一的連線。母體一擴大就順手把它一起餵進去，
        #   是這次變更最容易犯、後果也最嚴重的一步。
        # 而且探測對虛擬介面本來就無意義：它們沒有實體線路可測。
        probes = (self.prober.probe_all(self.sysfs.physical_nics(),
                                        while_up=self._warm_ethtool)
                  if self.prober is not None else {})
        members = self._bond_members(nics)
        timing = {}
        traffic = self.traffic
        if traffic is None and nics:
            traffic = sample_traffic(
                self.sysfs, nics, seconds=self.sample_seconds,
                sleep_fn=self.sleep_fn, bond_members=members, timing=timing,
                clock=self.clock)
        traffic = traffic or {}

        rows = [self._row(iface, probes.get(iface), traffic.get(iface, (0, 0)))
                for iface in nics]
        # [CHANGE] 2026-10-06 v03.019.000：矛盾資料掛在該 bond 那一列上，說明列由
        #          _notes 從列資料取，寬窄版與報告共用同一份。
        for conflict in bond_traffic_conflicts(traffic, members):
            row = rows[nics.index(conflict["bond"])]
            row["traffic_conflicts"].append(
                dict(conflict, first=timing.get("first"),
                     second=timing.get("second")))
        if self.zoned:
            self._annotate_zones(rows, nics)
        return rows

    # [CHANGE] 2026-10-08 v03.021.000 新增：分區版面用的過濾與標註。
    def _without_guest_ifaces(self, nics):
        """濾掉 PVE 客體機介面。有 device 連結者（實體卡）一律保留，不以名稱排除。"""
        physical = set(self.sysfs.physical_nics())
        return [nic for nic in nics
                if nic in physical or not is_guest_iface(nic)]

    def _annotate_zones(self, rows, nics):
        """在每列加上 zone 與 relation（皆不進 cells）。

        區的歸屬與 _row 的分流用同一個判準（interface_type ∈ VIRTUAL_MEDIA_KEYS），
        所以 bond 即使有 device 連結也歸虛擬區。
        """
        for row, iface in zip(rows, nics):
            kind = self.sysfs.interface_type(iface)
            virtual = kind in self.VIRTUAL_MEDIA_KEYS
            row["zone"] = ZONE_VIRTUAL if virtual else ZONE_PHYSICAL
            # [CHANGE] 2026-10-08 v03.023.000：只有虛擬區的列帶 uplinks（實體區不加欄）。
            if virtual:
                row["uplinks"] = self._uplink_names(iface)
            if kind == "bridge":
                members = [port for port in self.sysfs.bridge_ports(iface)
                           if not is_guest_iface(port)]
                row["relation"] = (REL_MEMBERS, members)
                continue
            master = self.sysfs.master(iface)
            row["relation"] = (REL_BELONGS, master) if master else None

    # [CHANGE] 2026-10-08 v03.023.000 新增：虛擬介面往下解到實體網卡。
    def _uplink_names(self, iface):
        """回實體網卡名稱清單；解不到回 []。拓撲查詢全沿用既有讀取器，不新增收集。"""
        return physical_uplinks(iface, self.sysfs.interface_type,
                                self._lower_ifaces)

    def _lower_ifaces(self, name, kind):
        """下一層介面：橋接的成員、bond 的成員、VLAN 的底層；讀不到一律回空。"""
        if kind == "bridge":
            return self.sysfs.bridge_ports(name)
        if kind == "bond":
            if self.bond is None:
                return []
            result = self.bond.read(name)
            if result.get("status") != STATUS_OK:
                return []
            return bond_collect.slave_names(result.get("data"))
        if kind == "vlan":
            parent = self.ip.vlan_parent(name) if self.ip is not None else None
            return [parent] if parent else []
        return []

    # [CHANGE] 2026-10-06 v03.019.000 新增：bond 的成員名單，沿用選單 8 的 BondReader。
    def _bond_members(self, nics):
        """回 {bond: [成員名]}；沒有 bond_reader、讀不到或沒有成員的 bond 不列入。"""
        if self.bond is None:
            return {}
        out = {}
        for nic in nics:
            if not self.sysfs.is_bond(nic):
                continue
            result = self.bond.read(nic)
            if result.get("status") != STATUS_OK:
                continue
            names = bond_collect.slave_names(result.get("data"))
            if names:
                out[nic] = names
        return out

    # [CHANGE] 2026-08-25 從 build() 抽出：加入探測之後 build() 到了 69 行，超過
    #          單一函式 ≤50 行的上限。
    # 接縫選在「一列」上，因為那是這個方法裡唯一自足的單位——它不依賴迴圈外
    #   的任何可變狀態，三個入參就是它需要的全部。以「行數」為由亂切一刀反而會
    #   造出兩個必須一起讀才看得懂的半截函式。
    # [CHANGE] 2026-08-27 虛擬介面的類型放「媒介」欄，兩個各自獨立的理由：
    #   ① 媒介欄對虛擬介面本來就無意義（bridge 不會有 RJ45），那格是空的；
    #   ② 介面欄一旦摻進類型標記就不再能 grep、不再能跨機器 diff。
    # 而**不新增第 12 欄**是因為本檔上方逐字記載過：13 欄的表格在一般寬度
    #   的終端放不下、整個降級成逐張區塊，那是 2026-08-02 回退的。
    VIRTUAL_MEDIA_KEYS = {
        "bond": "media.bond",
        "bridge": "media.bridge",
        "vlan": "media.vlan",
    }

    def _row(self, iface, probe, delta):
        """組出一列。實體卡與虛擬介面走不同的取值路徑。"""
        # 探測結果**優先於**直接讀取：probe["link"] 在略過的情形下本來就是
        #   sysfs 讀來的同一個值（見 linkprobe.probe 的前三條分支），在探測
        #   成功的情形下才是新資訊。這裡不做 `or` 短路——False 是有效答案，
        #   `probe["link"] or self.sysfs.carrier(iface)` 會把「確定沒接線」
        #   悄悄換成第二次讀取的結果。
        link = probe["link"] if probe is not None else self.sysfs.carrier(iface)
        link_text, _link_colour = link_state(link)
        media_key = self.VIRTUAL_MEDIA_KEYS.get(
            self.sysfs.interface_type(iface))
        if media_key is not None:
            return self._virtual_row(iface, probe, delta, link, link_text,
                                     media_key)
        link_info = self.ethtool.link_info(iface)
        driver_info = self.ethtool.driver_info(iface)
        # [CHANGE] 2026-08-03：成因缺漏時採保守的 unknown，避免對使用者
        #          做出「未安裝」這個無證據的斷言。
        # [CHANGE] 2026-08-03 補正：成因必須彙整**每一次 ethtool 查詢**。
        # 原本只取 link_info 的成因。但這一列實際會跑兩道**獨立**指令：
        #   `ethtool <nic>` 與 `ethtool -i <nic>`——不同 argv、不同快取鍵、
        #   各自的離開碼，任何一個都可能單獨失敗。
        #   ⇒ `ethtool -i` 單獨失敗時，Driver／PCI 欄顯示 N/A，而**一句警示
        #   都不會出現**：使用者看到空欄位卻拿不到任何線索。
        ethtool_failures = _ethtool_failures(link_info, driver_info)
        rx_active = bool(delta[0])
        tx_active = bool(delta[1])
        model, model_failure = self._model(iface)
        return {
            "cells": [
                iface, _value(self.sysfs.mac(iface)), link_text,
                _link_attr_value(link_info, "speed", link),
                _link_attr_value(link_info, "duplex", link),
                _value(self.sysfs.mtu(iface)),
                _medium_text(self.ethtool.medium(iface)),
                _traffic_text(rx_active, delta[0]),
                _traffic_text(tx_active, delta[1]),
                _result_value(driver_info, "driver"),
                _result_value(driver_info, "bus_info"),
            ],
            "link": link,
            # [CHANGE] 2026-08-25 整份探測結果留在列上，供 _probe_notes 逐張點名
            #          揭露。只留 link 是不夠的：「還原失敗」與「權限不足」
            #          在 link 這一欄的投影完全相同（都是 None），把結構壓成
            #          一個三態值就等於把那兩件事的差別丟掉。
            "probe": probe,
            "rx_active": rx_active,
            "tx_active": tx_active,
            "ethtool_failures": ethtool_failures,
            "model": model,
            "model_failure": model_failure,
            "traffic_conflicts": [],
        }

    # [CHANGE] 2026-10-06 v03.018.000 新增：實體卡的型號。
    def _model(self, iface):
        """回 (型號字串或 None, 取不到的成因或 None)。

        只有實體卡會走到這裡（虛擬介面走 _virtual_row，不查 lspci）。
        查詢失敗時型號是 N/A 字串，成因另外回傳；呼叫端把成因彙整成「一種一句」。
        """
        if self.lspci is None:
            return None, None
        address = self.sysfs.pci_address(iface)
        if address is None:
            return t("app.na"), MODEL_NO_ADDRESS
        result = self.lspci.model(address)
        if result.get("status") == STATUS_OK:
            text = lspci_collect.format_model(result.get("data") or {})
            if text:
                return text, None
        if result.get("status") == STATUS_UNAVAILABLE:
            return t("app.na"), result.get("failure") or FAILURE_UNKNOWN
        return t("app.na"), MODEL_EMPTY

    # [CHANGE] 2026-08-27 新增：虛擬介面（bond／bridge／VLAN）的一列。
    def _virtual_row(self, iface, probe, delta, link, link_text, media_key):
        """虛擬介面**不查 ethtool**，速率／Duplex／驅動／PCI 一律 N/A。

        這不是效能考量。`ethtool vmbr0` 對純軟體的 bridge 會回一個**虛構
          的** Speed（現場常見 10000Mb/s），`ethtool bond0` 回的則是 slave 的
          聚合值——兩者都是「看起來像真的、語意卻不同」的數字，一旦進了表格
          就是一句沒有證據的斷言。
          N/A 表示「沒有這個資訊」，虛構的數字卻宣稱「知道，就是這
            個」。兩者在畫面上都只佔一格，但只有一個是誠實的。
        附帶效果同樣重要：不查就不會產生 ethtool 失敗成因。否則每一個虛擬
          介面都各貢獻一句警示，把實體卡真正的警示淹掉——PVE 上 vmbr 加 VLAN
          子介面十幾個是常態。
        """
        na = t("app.na")
        rx_active = bool(delta[0])
        tx_active = bool(delta[1])
        return {
            "cells": [
                iface, _value(self.sysfs.mac(iface)), link_text,
                na, na, _value(self.sysfs.mtu(iface)), t(media_key),
                _traffic_text(rx_active, delta[0]),
                _traffic_text(tx_active, delta[1]),
                na, na,
            ],
            "link": link,
            "probe": probe,
            "rx_active": rx_active,
            "tx_active": tx_active,
            "ethtool_failures": {},
            # [CHANGE] 2026-10-06 v03.018.000：虛擬介面不查 lspci、不列型號。
            "model": None,
            "model_failure": None,
            "traffic_conflicts": [],
        }

    # [CHANGE] 2026-08-25 新增：趁網卡還開著的時候把 ethtool 問完。
    def _warm_ethtool(self, nic):
        """在探測期間預先查 ethtool，讓速率與 Duplex 拿到的是啟用狀態下的值。

        為什麼非做不可：ethtool 對 admin-down 的網卡回 `Speed: Unknown!`／
          `Duplex: Unknown! (255)`。探測還原成 down 之後再問，拿到的仍是那個——
          於是畫面出現「Link：已接線／速率：Unknown!」這種**同一列自相矛盾**的
          結果。只修 Link 而不管這一欄，等於把困惑從一個欄位搬到另一個欄位。

        這裡不接回傳值：`EthtoolReader` 以 (nic, option) 為鍵快取，稍後
          `build()` 迴圈裡的查詢會命中同一筆。**依賴快取是刻意的**——改成
          回傳值再往下傳，NicSection 就多了一份與 ethtool 平行的狀態，
          而兩份會漂移。
        但這個依賴必須被守住：快取若哪天被拿掉，速率會靜默變回 Unknown!。
          守它的是 `tests/test_linkprobe.py::test_探測後Link與速率不得互相矛盾`，
          那條測試用的是**真的** EthtoolReader，不是替身。

        `medium()` 也要預熱：它內部同樣走 link_info，而光模組的 EEPROM
          （`ethtool -m`）在 admin-down 時多半讀不到。
        """
        self.ethtool.link_info(nic)
        self.ethtool.medium(nic)

    def _notes(self, data, ctx):
        # [CHANGE] 2026-08-03：三種成因三句話，**每一句的斷言強度都要與
        #          手上的證據相符**：
        #            not_executable → 「未安裝」（run_command 拋 OSError 才會有）
        #            exit_code      → 「已安裝但執行失敗」（跑得起來才會有離開碼）
        #            其餘／unknown  → 只說讀取失敗，**不斷言安裝與否**
        #
        # 最後一類原本併進 exit_code 那句，而那句逐字說「ethtool 已安裝」——
        #   成因未知時說「已安裝」與說「未安裝」一樣是沒有證據的斷言，正是本次修正
        #   要修的病。修一個方向的說謊時，不得在另一個方向再犯一次。
        # 三者可並存（多張網卡成因不同，或**同一張網卡的不同查詢**各自以不同
        #   原因失敗），故用三個獨立的 if 而非 elif。
        # [CHANGE] 2026-08-03：彙整成 {成因: {受影響欄位群}}，兩層都要合併。
        failures = {}
        for row in data:
            for cause, scopes in row["ethtool_failures"].items():
                failures.setdefault(cause, set()).update(scopes)
        lines = []
        if FAILURE_NOT_EXECUTABLE in failures:
            lines.append(error(t("nic.ethtool_missing"), ctx.palette))
        if FAILURE_EXIT_CODE in failures:
            lines.append(error(t("nic.ethtool_failed"), ctx.palette))
        # [CHANGE] 2026-08-03：逾時獨立一句。
        if FAILURE_TIMEOUT in failures:
            lines.append(error(t("nic.ethtool_timeout"), ctx.palette))
        if set(failures) - {FAILURE_NOT_EXECUTABLE, FAILURE_EXIT_CODE,
                            FAILURE_TIMEOUT}:
            lines.append(error(t("nic.ethtool_unknown"), ctx.palette))
        # [CHANGE] 2026-08-03：受影響的欄位改由**實際失敗的那幾次查詢**決定，
        #          而不是四句話各自寫死一份清單。寫死的那份會在只有一邊失敗時說謊。
        if failures:
            affected = set()
            for scopes in failures.values():
                affected |= scopes
            lines.append(note(t("nic.ethtool_affected",
                                fields=_scope_text(affected)), ctx.palette))
        # [CHANGE] 2026-10-06 v03.018.000：型號取不到的成因（每種一句）。
        lines.extend(_model_notes(data, ctx))
        # [CHANGE] 2026-08-25 探測的點名說明排在流量說明之前——它講的是「本工具對
        #          這台主機做了什麼」，比「這個欄位怎麼讀」優先。
        lines.extend(self._probe_notes(data, ctx))
        lines.extend(_conflict_notes(data, ctx))
        lines.append(note(t("nic.traffic_note", sec=self.sample_seconds),
                          ctx.palette))
        return lines

    # [CHANGE] 2026-08-25 新增：Link 探測的點名說明。
    def _probe_notes(self, data, ctx):
        """把探測做過什麼、有沒有做成、有沒有還原乾淨，逐項說出來。

        這幾句不得省。探測是本工具**唯一**會改變主機狀態的動作，
          使用者有權知道本工具動了哪幾張卡。

        還原失敗必須**逐張點名**。只說「部分網卡還原失敗」等於沒說——
          使用者無從得知要去把哪一張關回去，而那張卡此刻正處於本工具留下的啟用
          狀態。這與本檔上方 ethtool 成因分流的立論相同：彙總數字底下不同質。

        每一種成因各自一個 if 而非 elif：多張網卡的成因可以不同，一台主機上
          同時出現「兩張探測成功、一張權限不足、一張被 bond 接管」是正常的。
        """
        state = _probe_state(data)
        lines = []
        if state["unrestored"]:
            lines.append(error(t("nic.probe_restore_failed",
                                 nics=_join(state["unrestored"])), ctx.palette))
        if state["denied"]:
            lines.append(error(t("nic.probe_denied",
                                 nics=_join(state["denied"])), ctx.palette))
        if state["unavailable"]:
            lines.append(error(t("nic.probe_unavailable",
                                 nics=_join(state["unavailable"])), ctx.palette))
        if state["timed_out"]:
            lines.append(note(t("nic.probe_timeout",
                                nics=_join(state["timed_out"]),
                                sec=self._probe_wait()), ctx.palette))
        if state["enslaved"]:
            lines.append(note(t("nic.probe_enslaved",
                                pairs=_join(state["enslaved"])), ctx.palette))
        if state["disabled"]:
            lines.append(note(t("nic.probe_disabled"), ctx.palette))
        if state["probed"]:
            lines.append(note(t("nic.probe_done",
                                nics=_join(state["probed"])), ctx.palette))
        return lines

    def _probe_wait(self):
        """探測等待秒數，供逾時訊息引用。

        從 prober 取而不是自己再讀一次環境變數：同一個設定值有兩個來源，
          兩邊會漂移，而漂移後畫面上的秒數與實際等待時間不同——那種錯沒有任何
          裝置會發現。
        """
        return getattr(self.prober, "wait_seconds", 0)

    def table(self, data, ctx):
        # [CHANGE] 2026-10-06 v03.018.000：型號列在說明列**之前**。
        table = DecoratedTable([t(key) for key in self.HEADERS],
                               trailing=(_model_lines(data)
                                         + self._notes(data, ctx)))
        for row in data:
            table.add(row["cells"])
        return table

    def blocks(self, data, ctx):
        return self._block_lines(data, ctx) + self._notes(data, ctx)

    def _block_lines(self, data, ctx):
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
            # [CHANGE] 2026-10-06 v03.018.000：只有實體卡有型號，虛擬介面不加這行。
            if row.get("model") is not None:
                lines.append(kv(t("nic.model"), row["model"], key_width=8))
            # [CHANGE] 2026-10-08 v03.023.000：虛擬介面的實體網卡（區塊版）。
            if row.get("uplinks") is not None:
                lines.append(kv(t("nic.uplinks"), _uplink_text(row["uplinks"]),
                                key_width=8))
            # [CHANGE] 2026-10-08 v03.021.000：橋接關係副列（區塊版）。
            if row.get("relation") is not None:
                lines.append(kv(t("nic.relation"),
                                _relation_text(row["relation"]), key_width=8))
            lines.append("")
        return lines

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

    # [CHANGE] 2026-10-08 v03.021.000 新增：分區版面。
    def render(self, ctx):
        if not self.zoned:
            return Section.render(self, ctx)
        data = self.build()
        if self.is_empty(data):
            return self.empty_lines(data, ctx)
        physical = [row for row in data if row["zone"] == ZONE_PHYSICAL]
        virtual = [row for row in data if row["zone"] == ZONE_VIRTUAL]
        lines = subsection(t("nic.zone_physical"), ctx.palette)
        lines.extend(self._zone_lines(
            physical, ctx, error(t("nic.none_found"), ctx.palette)))
        lines.append("")
        lines.extend(subsection(t("nic.zone_virtual"), ctx.palette))
        lines.extend(self._zone_lines(
            virtual, ctx, note(t("nic.zone_virtual_none"), ctx.palette)))
        summary = self._guest_summary(ctx)
        if summary:
            lines.extend([""] + summary)
        return lines + self._notes(data, ctx)

    def _zone_lines(self, rows, ctx, empty_line):
        """一個區的表格（放不下則逐張區塊）；型號列與橋接副列接在表下。"""
        if not rows:
            return [empty_line]
        trailing = _model_lines(rows) + _relation_lines(rows)
        # [CHANGE] 2026-10-08 v03.023.000：虛擬介面區先試十二欄（媒介後加「實體網卡」）；
        #          放不下就退回原本的十一欄表，並把同一份資訊放到表下；再放不下才走區塊版。
        #          退回的十一欄表與施作前逐欄相同，所以原本放得下的寬度不會因加欄而降級。
        has_uplinks = any(row.get("uplinks") is not None for row in rows)
        if has_uplinks:
            wide = self._uplink_table(rows, trailing)
            if ctx.fits(wide.total_width()):
                return wide.render(self._uplink_colorizer(rows, ctx))
        table = DecoratedTable(
            [t(key) for key in self.HEADERS],
            trailing=trailing + (_uplink_lines(rows) if has_uplinks else []))
        for row in rows:
            table.add(row["cells"])
        if ctx.fits(table.total_width()):
            return table.render(self.colorizer(rows, ctx))
        # 區塊版每張卡後面都有一行空白；區與區之間的空白由呼叫端加，這裡去掉最後那一行。
        return self._block_lines(rows, ctx)[:-1]

    def _uplink_table(self, rows, trailing):
        """十二欄版：在「媒介」之後插入「實體網卡」。"""
        headers = [t(key) for key in self.HEADERS]
        headers.insert(UPLINK_COLUMN_INDEX, t("nic.uplinks"))
        table = DecoratedTable(headers, trailing=trailing)
        for row in rows:
            cells = list(row["cells"])
            cells.insert(UPLINK_COLUMN_INDEX, _uplink_text(row["uplinks"]))
            table.add(cells)
        return table

    def _uplink_colorizer(self, rows, ctx):
        """欄位插入後，原有欄的著色索引要往回對；新欄本身不著色。"""
        paint = self.colorizer(rows, ctx)

        def shifted(row_index, col_index, text):
            if col_index == UPLINK_COLUMN_INDEX:
                return text
            if col_index > UPLINK_COLUMN_INDEX:
                col_index -= 1
            return paint(row_index, col_index, text)
        return shifted

    def _guest_summary(self, ctx):
        """「客體網卡 N 個（執行中 M 個）」；N／M 的口徑同「VM/CT 網卡對應」選單。

        讀不到設定檔時**明說**，不印「0 個」：0 與「沒讀到」在畫面上同形。
        """
        if self.guest is None:
            return []
        result = self.guest.nics()
        if result.get("status") == STATUS_UNAVAILABLE:
            return [note(t("nic.guest_summary_unavailable"), ctx.palette)]
        total, running = guest_nic_counts(result.get("nics"), self.sysfs.exists)
        text = t("nic.guest_summary", total=total, running=running)
        unreadable = len(result.get("unreadable") or [])
        if unreadable:
            text += t("nic.guest_summary_unreadable", count=unreadable)
        return [text]


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
