"""雙語訊息表。

設計重點只有一個：**缺 key 必須吵**。

一個 i18n 機制最容易出的錯不是翻譯不好，而是「某個 key 只有中文沒有英文」——
英文使用者看到的是空字串或 key 名，而開發者用中文跑永遠不會發現。所以：

* 取不到 key 時回傳醒目的 ``⟪MISSING:key⟫`` 而非空字串，並記進 MISSING 供自檢查驗
* 兩語言的 key 集合必須完全相同，由 key_diff() 量出差集，自檢對它 fail-closed
* 每個 key 的翻譯都不得為空字串

語言選擇順序：PVE_AUDIT_LANG > LC_ALL/LC_MESSAGES/LANG > 預設 en。
預設 en 是因為這是公開工具，非中文環境的人不該看到看不懂的介面；中文使用者在
PVE 上（locale 常是 C 或 en_US）請設 PVE_AUDIT_LANG=zh。
"""

import os
import string  # [CHANGE] 2026-07-31 t() 需要判斷訊息本身要不要帶參數

__all__ = ["t", "set_lang", "current_lang", "available_langs",
           "next_lang", "lang_display_name",
           "key_diff", "empty_values", "missing_keys", "reset_missing"]

DEFAULT_LANG = "en"

# 語言代碼正規化：把 zh_TW.UTF-8 / zh-Hant / zh 這類都收斂到 'zh-TW'
_ALIASES = {
    "zh": "zh-TW", "zh-tw": "zh-TW", "zh_tw": "zh-TW",
    "zh-hant": "zh-TW", "zh_hant": "zh-TW", "tw": "zh-TW",
    "en": "en", "en-us": "en", "en_us": "en", "c": "en", "posix": "en",
}

MESSAGES = {
    "zh-TW": {
        # ── 通用 ──
        "app.title": "PVE 互動式網路盤查工具",
        "app.host": "主機名稱",
        "app.time": "執行時間",
        "app.need_root": "請使用 root 權限執行此腳本。",
        "app.press_enter": "按 Enter 返回主選單...",
        "app.invalid_choice": "無效選項。",
        "app.back": "返回",
        "app.exit": "已離開。",
        "app.not_found": "找不到",
        "app.none": "無",
        "app.na": "N/A",
        "app.yes": "是",
        "app.no": "否",
        "app.enabled": "啟用",
        "app.disabled": "停用",
        "app.unknown": "未知",
        # [CHANGE] 2026-08-02 版面的鍵值分隔符。原本在程式碼裡硬編碼成全形「：」，
        #          於是英文介面會印出 `Hostname：pve-node-01`——半形語境混一個
        #          全形標點。
        #          ★ 英文版取 `": "`（冒號＋空格）而不是 `":"`：**兩者的顯示寬度
        #          都是 2**，欄寬計算因此完全不受影響。若寫成單一個半形冒號，
        #          所有表格的值欄會整欄左移一格，而且不會有任何東西變紅
        #          （見 test_分隔符在各語言的顯示寬度必須相同）。
        "app.kv_sep": "：",

        # [CHANGE] 2026-08-02 選單、報告與 CLI 文案集中於雙語表，避免輸出路徑自行硬寫而漂移。
        # ── 主選單 ──
        "menu.prompt": "請選擇盤查項目：",
        "menu.input": "請輸入選項 [{range}]：",
        "menu.group_phys": "實體層",
        "menu.group_l2": "二層",
        "menu.group_l3": "三層與 PVE",
        "menu.group_overall": "整體",
        "menu.group_added": "Python 版新增（bash 版沒有的項目）",
        "menu.not_implemented": "尚未實作（待辦 #{todo}）",
        "menu.nic_status": "實體網卡狀態與 RX/TX",
        "menu.nic_health": "網卡健康：Link 抖動、錯誤與丟包、韌體",
        "menu.nic_modules": "SFP/QSFP 模組明細",
        "menu.nic_led": "實體網卡 LED 定位",
        "menu.bond": "Bond 設定與成員狀態",
        "menu.bridge": "Linux Bridge",
        "menu.ovs": "Open vSwitch",
        "menu.vlan_sub": "VLAN 子介面",
        "menu.bridge_vlan": "Bridge VLAN Filter（逐 Port 放行清單）",
        "menu.guest_nics": "VM/CT 網卡對應（tap/veth ←→ VMID）",
        "menu.vlan_reconcile": "VLAN 對帳（Guest VLAN vs Uplink 放行）",
        "menu.ip_routing": "IP / 路由 / DNS / hosts / 鄰居表",
        "menu.sdn": "PVE SDN",
        "menu.corosync": "叢集網路（corosync）",
        "menu.firewall": "PVE 防火牆",
        "menu.lldp": "LLDP 交換器與 Port",
        "menu.persistent": "/etc/network/interfaces 持久化設定",
        "menu.view_all": "依序檢視全部項目",
        "menu.full_report": "輸出完整盤查報告",
        "menu.self_test": "執行內建自檢",
        "menu.sysctl": "sysctl 網路參數",
        "menu.conntrack": "conntrack 連線追蹤容量",
        "menu.neigh": "鄰居表容量（ARP／NDP gc_thresh）",
        "menu.autostart": "開機自動啟用對帳（auto／hotplug）",
        "menu.exit": "離開",
        # [CHANGE] 2026-08-02 待辦 #25：選單內切換語系。
        # ★ native_name 用該語言自己的文字寫，且由各語系自行宣告——這樣新增
        #   語系時，顯示名和訊息一起進來，不會有第二個地方要記得改。
        "lang.native_name": "中文",
        "menu.switch_lang": "切換語言（{target}）",
        "menu.pick_nic": "請選擇要定位的網卡編號：",

        # ── 完整報告 ──
        "report.title": "PVE 網路完整盤查報告",
        "report.kernel": "核心版本",
        "report.pve_version": "PVE 版本",
        "report.generated_at": "產生時間",
        "report.tool_version": "工具版本",
        "report.generating": "產生中：{title}",
        "report.done": "完整盤查報告已寫入：{path}",
        "report.mkdir_failed": "無法建立報告目錄：{path}",
        "report.create_failed": "無法建立報告檔：{path}",

        # ── CLI ──
        "cli.unknown_option": "未知選項：{option}",
        "cli.usage_synopsis": "用法：\n  {prog}                 啟動互動選單\n  {prog} --report        非互動，直接輸出完整盤查報告（適合排 cron）\n  {prog} --self-test     只跑內建自檢，不讀取系統網路狀態\n  {prog} --version       顯示版本\n  {prog} --help          顯示本說明",
        # [CHANGE] 2026-08-02 待辦 #24：本段原本承諾了 LIST_LIMIT（「清單顯示上限」），
        #          但全套件零實作——使用者設了不會生效也不會報錯，是對使用者說謊，
        #          故移除並具名為待辦。同時補上四個「有實作卻沒列」的變數，其中
        #          PVE_AUDIT_LANG 最關鍵：PVE 的 locale 多為 C/en_US，推導不到中文，
        #          不設它真機上就是英文介面，而這件事本檔 docstring 寫了、使用者卻看不到。
        #          ★ 每一行的排版（兩格縮排＋名稱＋兩格以上空白＋說明）是
        #          tests/test_cli.py 的 usage 對帳判準所依賴的契約，改排版會讓它轉紅。
        # [CHANGE] 2026-08-02 LIST_LIMIT 加回。上一棒（待辦 #24）移除它是對的
        #          ——當時全套件零實作，說明文件承諾了不存在的功能。選單第 12 項
        #          實作之後它有了真正的呼叫端（app.Readers.list_limit ⇒
        #          render/iprouting.py 的 limited()），繼續不列反而會讓 usage
        #          對帳守門員的另一個方向轉紅。
        "cli.usage_env": "環境變數：\n  REPORT_DIR        報告輸出目錄（預設 /root）\n  LIST_LIMIT        路由／鄰居等清單的顯示上限（預設 50，超量會明說截掉幾筆）\n  SAMPLE_SECONDS    RX/TX 取樣秒數（預設 3）\n  BLINK_SECONDS     LED 定位閃爍秒數（預設 10）\n  COMMAND_TIMEOUT   外部指令逾時秒數（預設 15；逾時會明說是逾時，不會說成未安裝）\n  PVE_CONF_ROOT     PVE 設定根目錄（預設 /etc/pve）\n  PVE_AUDIT_LANG    介面語言 zh／en（PVE 的 locale 多為 C，不設會是英文）\n  NO_PAGER          設為 1 時不使用 less／more 分頁\n  TERM_WIDTH        強制指定版面寬度，最優先\n  COLUMNS           版面寬度來源之一（優先序次於上一項）\n  LC_ALL／LC_MESSAGES／LANG    標準 locale，語言推導的後備",
        "cli.usage_note": "注意：報告內含 corosync 叢集拓撲與節點 IP、防火牆規則與 /etc/hosts，\n      故以 0600 建立。若改用共用目錄存放，請自行確認目錄權限。",
        "cli.usage_deps": "依賴：\n  必要  iproute2（ip、bridge）\n  建議  ethtool（速率／Duplex／媒介／韌體／LED）\n        lldpd（交換器與 Port 對應）\n  選用  openvswitch-switch（僅 OVS 環境需要）",

        # ── 連線狀態 ──
        "link.up": "已接線",
        "link.down": "未接線",
        "link.unknown": "未知",
        "traffic.yes": "有流量",
        "traffic.no": "無流量",

        # ── 媒介類型 ──
        "media.rj45": "RJ45 電口",
        "media.fiber": "光纖",
        "media.dac": "DAC 銅纜",
        "media.aoc": "AOC 主動線纜",
        "media.backplane": "背板介面",
        "media.unknown": "未知",

        # ── 實體網卡表 ──
        "nic.iface": "介面",
        "nic.mac": "MAC Address",
        "nic.link": "Link",
        "nic.speed": "速率",
        "nic.duplex": "Duplex",
        "nic.mtu": "MTU",
        "nic.media": "媒介",
        "nic.rx": "RX",
        "nic.tx": "TX",
        "nic.driver": "驅動",
        "nic.pci": "PCI 位址",
        # [CHANGE] 2026-08-02 待辦 #17：SFP/QSFP 模組明細（選單第 3 項）。
        # 欄位與措辭逐項對齊 bash 的 render_nic_modules。
        "module.header": "── {nic} ── 判定媒介：{medium}",
        "module.vendor": "廠商",
        "module.pn": "料號",
        "module.sn": "序號",
        "module.connector": "接頭",
        "module.type": "模組型別",
        "module.cable_tech": "線纜技術",
        "module.length_copper": "銅纜長度",
        "module.temperature": "溫度",
        "module.voltage": "電壓",
        "module.tx_power": "光發射功率",
        "module.rx_power": "光接收功率",
        "module.none": "沒有偵測到可讀取的 SFP/QSFP 模組（純 RJ45 電口網卡屬正常）。",
        # [CHANGE] 2026-08-02 待辦 #26：移除 nic.autostart／nic.comment。
        # ★ 這兩個 key 的存在曾被當成「規格要這兩欄」的證據（見 render/nic.py
        #   舊註解），但 bash 版的 render_physical_nics 從不讀 interfaces。
        #   **i18n 有 key 不等於規格要它**——key 本身也可能是誤加的。
        "nic.none_found": "找不到實體網卡。",
        "nic.sampling": "正在取樣 RX/TX 流量 {sec} 秒...",
        "nic.traffic_note": "說明：RX/TX 表示在 {sec} 秒取樣期間計數器是否增加；無流量不代表網路異常。",
        # [CHANGE] 2026-08-03 待辦 #35 補正：原文逐字寫「未安裝 ethtool」，而
        #          `run_command()` 把**所有** OSError（含 PermissionError）歸成
        #          FAILURE_NOT_EXECUTABLE ⇒ 檔案存在但沒有執行權限時，這句話是假的。
        #          改成不斷言「有沒有裝」，只陳述「跑不起來」這件確定成立的事。
        #          ★ key 名保留（歷史名稱，非使用者可見），語意已放寬。
        # [CHANGE] 2026-08-03 待辦 #38：原文還列了「SubprocessError（含
        #          TimeoutExpired）」也歸在同一成因——那已經**不成立**（拆到
        #          FAILURE_UNKNOWN 去了，走的是 nic.ethtool_unknown 那句）。
        #          本句放寬的理由只剩 PermissionError，但理由少一個不影響結論。
        # [CHANGE] 2026-08-03 待辦 #41：四句話的尾巴原本都把四個欄位（速率／Duplex／
        #          媒介／驅動）一次全列為 N/A。那份清單寫死在訊息裡，而成因只來自某
        #          一次查詢——只有 `ethtool -i` 失敗時，速率與 Duplex 其實好端端地顯
        #          示著。受影響的欄位改由 nic.ethtool_affected 依實況列出。
        "nic.ethtool_missing": "無法執行 ethtool（可能未安裝，或檔案沒有執行權限）。",
        # [CHANGE] 2026-08-03 待辦 #35：非零離開碼與成因未知不得再誤報成未安裝。
        "nic.ethtool_failed": "ethtool 已安裝但執行失敗（可能是權限不足或驅動不支援）。",
        # [CHANGE] 2026-08-03 待辦 #35 補正：成因未知時**不得斷言安裝與否**。
        #          說「已安裝」與說「未安裝」一樣是沒有證據的斷言——那正是本待辦
        #          要修的病，不可在修它的過程中換個方向再犯一次。
        "nic.ethtool_unknown": "ethtool 資訊讀取失敗，成因不明。",
        # [CHANGE] 2026-08-03 待辦 #48：逾時要說成逾時。說「未安裝」會讓人去
        #          裝一個已經裝好的東西，說「成因不明」則丟掉了唯一有用的線索
        #          ——那台主機或那個驅動沒有在時限內回應。
        "nic.ethtool_timeout": "ethtool 執行逾時（主機或驅動未在時限內回應）。可用環境變數 COMMAND_TIMEOUT 調整秒數。",
        # [CHANGE] 2026-08-03 待辦 #41：受影響欄位由實際失敗的查詢決定。
        #          ★ 媒介不列在這裡是判斷不是遺漏：它在 link 失敗時會改走 EEPROM，
        #            而且取不到值時顯示的是「未知」，不是 N/A。
        "nic.ethtool_affected": "以下欄位將顯示 N/A：{fields}。",
        "nic.ethtool_scope_link": "速率與 Duplex",
        "nic.ethtool_scope_driver": "驅動資訊",
        "nic.ethtool_scope_sep": "、",

        # ── 網卡健康 ──
        "health.state": "狀態",
        "health.carrier_changes": "Link 變動",
        "health.autoneg": "自動協商",
        "health.rx_err": "RX 錯誤",
        "health.rx_drop": "RX 丟包",
        "health.tx_err": "TX 錯誤",
        "health.tx_drop": "TX 丟包",
        "health.crc": "CRC 錯誤",
        "health.numa": "NUMA",
        "health.firmware": "韌體版本",
        "health.note_flap": "說明：Link 變動＝carrier_changes，開機後正常為 1～2；持續增加代表線路或模組抖動。",
        "health.note_crc": "      CRC 錯誤非 0 幾乎必為實體層問題（線材、模組、對端 Port）。",

        # ── Autostart 對帳 ──
        "autostart.configured": "設定檔",
        "autostart.running": "執行中",
        "autostart.verdict": "判定",
        "autostart.ok": "相符",
        "autostart.running_not_auto": "★ 執行中但未設 autostart——重開機後會消失",
        "autostart.auto_not_running": "★ 已設 autostart 卻沒起來——開機時失敗了",
        "autostart.note": "說明：兩者不一致是「重開機後網路不見了」最常見的原因。",

        # ── VLAN ──
        "bridgevlan.port": "Port",
        "bridgevlan.type": "類型",
        "bridgevlan.pvid": "PVID",
        "bridgevlan.allowed": "放行 VLAN",
        "bridgevlan.uplink": "Uplink",
        "bridgevlan.guest": "Guest 介面",
        "bridgevlan.self": "Bridge 本身",

        # ── VM/CT ──
        "guest.vmid": "VMID",
        "guest.kind": "類型",
        "guest.name": "名稱",
        "guest.netid": "網卡",
        "guest.iface": "介面",
        # [CHANGE] 2026-08-02 待辦 #26：補回 MAC 與 MTU（bash 版兩個版面都有，
        # Python 版連 key 都沒有＝實質功能倒退），並移除 bash 全檔零命中的
        # guest.model／guest.rate／guest.linkdown 及其兩個值。
        "guest.mac": "MAC",
        "guest.bridge": "Bridge",
        "guest.tag": "VLAN Tag",
        "guest.mtu": "MTU",
        "guest.firewall": "防火牆",
        "guest.state": "介面狀態",
        "guest.running": "執行中",
        "guest.stopped": "未執行",
        "guest.none": "沒有找到任何已設定網卡的 VM 或 CT。",

        # ── sysctl ──
        "sysctl.key": "參數",
        "sysctl.value": "目前值",
        "sysctl.note": "說明",
        "sysctl.bridge_nf_warn": "★ 開啟中——bridge 流量會被 iptables 攔，同 bridge 的 VM 可能互通不了",

        # ── conntrack / 鄰居表 ──
        "conntrack.used": "使用中",
        "conntrack.max": "上限",
        "conntrack.usage": "使用率",
        "conntrack.warn": "★ 使用率偏高——滿了會表現成隨機丟連線",
        "neigh.current": "目前筆數",
        "neigh.thresh": "回收門檻",
        "neigh.warn": "★ 接近 gc_thresh3——超過會開始隨機不通",

        # [CHANGE] 2026-08-02 pager、LED 與自檢文案集中管理，避免雙語介面靜默分岔。
        # ── Pager ──
        "pager.scroll_hint": "（↑↓ 捲動　←→ 橫向捲動　/ 搜尋　q 返回主選單）",

        # ── LED 定位 ──
        "led.title": "選擇要定位的實體網卡",
        "led.need_ethtool": "需要 ethtool 才能執行網卡 LED 定位。",
        "led.install_hint": "安裝指令：apt update && apt install -y ethtool",
        "led.no_nic": "找不到實體網卡。",
        "led.blinking": "正在讓 {nic} 的 LED 閃爍 {seconds} 秒（此期間畫面會停住）...",
        "led.done": "LED 定位完成。",
        "led.unsupported": "此網卡或驅動不支援 LED 定位。",
        "led.monitor_hint": "可使用另一個終端執行 ip monitor link，再由現場拔插線確認。",

        # ── 內建自檢 ──
        "selftest.title": "PVE 網路盤查工具 v{version} — 內建自檢",
        "selftest.group_width": "1. 顯示寬度計算（CJK 全形計 2 欄）",
        "selftest.group_vlan": "2. VLAN 清單展開與壓縮",
        "selftest.group_guest": "3. VM/CT 網卡設定解析",
        "selftest.group_netconf": "4. 介面設定檔解析",
        "selftest.group_i18n": "5. 雙語訊息表對齊",
        # [CHANGE] 2026-08-03 待辦 #30：六類契約加入內建自檢，讓使用者可從輸出核對射程。
        "selftest.group_sysfs": "6. sysfs 讀取失敗與空值處理",
        "selftest.group_medium": "7. 網路媒介語意欄位判定",
        "selftest.group_bridgevlan": "8. bridge VLAN 縮排輸出解析",
        "selftest.group_ethtool_calls": "9. ethtool 指令快取",
        "selftest.group_list_limit": "10. 清單截斷揭露",
        "selftest.group_report_perm": "11. 報告檔建立權限",
        "selftest.scope": "受檢 {count} 項",
        "selftest.detail_fail": "預期=[{expected}] 實得=[{actual}]",
        "selftest.summary": "自檢結果：通過 {passed} 項、失敗 {failed} 項、略過 {skipped} 項",
        "selftest.has_failure": "有檢查項未通過，工具的判定邏輯可能已經退化，請勿依賴本次盤查結果。",
        "selftest.all_passed": "全部檢查項通過。",
        "selftest.result_pass": "  [PASS] {name} = {actual}",
        "selftest.result_fail": "  [FAIL] {name} {detail}",
        "selftest.result_skip": "  [SKIP] {name}{reason}",
        "selftest.skip_reason": " — 原因：{reason}",
        "selftest.check_width_ascii": "disp_width('Link')",
        "selftest.check_width_cjk": "disp_width('已接線')",
        "selftest.check_width_mixed": "disp_width('RJ45 電口')",
        "selftest.check_width_pad": "pad 補白後總寬（欄寬 10）",
        "selftest.check_width_no_truncate": "pad 超寬不截斷",
        "selftest.check_width_truncate": "truncate 截斷後不超過欄寬",
        "selftest.check_vlan_expand": "展開 10,20-23,30",
        "selftest.check_vlan_empty": "空輸入展開為空集合",
        "selftest.check_vlan_roundtrip": "壓縮後再展開保持原集合",
        "selftest.check_vlan_contains": "範圍包含 VLAN 22",
        "selftest.check_vlan_excludes": "範圍不包含 VLAN 24",
        "selftest.check_guest_fields": "取出 MAC、bridge 與 tag",
        "selftest.check_guest_kv": "鍵值拆解會去除空白",
        "selftest.check_guest_mac": "辨識合法 MAC",
        "selftest.check_guest_bad_mac": "拒絕不完整 MAC",
        "selftest.check_netconf_join": "合併反斜線續行",
        "selftest.check_netconf_stanza": "辨識 top-level 指令",
        "selftest.check_netconf_comment": "辨識註解行",
        "selftest.check_netconf_blank": "辨識空白行",
        "selftest.check_netconf_auto": "解析 auto 介面清單",
        "selftest.check_i18n_diff": "雙語 key 差集為空",
        "selftest.check_i18n_empty": "雙語訊息沒有空值",
        "selftest.check_i18n_languages": "自檢涵蓋兩個語言表",
        # [CHANGE] 2026-08-03 待辦 #30：名稱描述被守的性質；已知輸入留在 selftest.py。
        "selftest.check_sysfs_value": "正常 sysfs 屬性會回傳去除換行的內容",
        "selftest.check_sysfs_missing": "不存在的 sysfs 路徑安靜回預設值",
        "selftest.check_sysfs_directory": "目錄冒充 sysfs 屬性時安靜回預設值",
        "selftest.check_sysfs_blank": "空白 sysfs 屬性回預設值",
        "selftest.check_medium_rj45": "Twisted Pair 判為 RJ45",
        "selftest.check_medium_backplane": "Backplane port 判為背板",
        "selftest.check_medium_aui": "AUI port 判為 AUI",
        "selftest.check_medium_mii": "MII port 判為 MII",
        "selftest.check_medium_dac": "被無關 optical 字樣干擾的被動銅纜仍判為 DAC",
        "selftest.check_medium_aoc": "Active Cable 語意欄判為 AOC",
        "selftest.check_medium_fiber": "LC 接頭語意欄判為光纖",
        "selftest.check_medium_unavailable": "無 ethtool 資料時媒介不可判定",
        "selftest.check_medium_base_t": "1000BASE-T 模組的 RJ45 規則優先於銅線長",
        "selftest.check_medium_dac_no_lengths": "缺少全部線長欄位的被動銅纜仍判為 DAC",
        "selftest.check_medium_length_counterfactual": "只改光纖線長會讓 DAC 樣本翻為光纖",
        "selftest.check_bridgevlan_ports": "多 port 的 VLAN 清單與 PVID 各自正確",
        "selftest.check_bridgevlan_header": "表頭不會成為 port",
        "selftest.check_bridgevlan_continuation": "縮排 VLAN 續行不會成為 port",
        "selftest.check_bridgevlan_count": "解析出的 port 筆數正確",
        "selftest.check_bridgevlan_expand": "去標記清單可正確接入 VLAN 展開器",
        # [CHANGE] 2026-08-03 待辦 #30 補正：單獨守「VLAN 欄位必須數字開頭」那道防線。
        "selftest.check_bridgevlan_nonnumeric": "續行中非數字開頭的欄位會被忽略",
        "selftest.check_ethtool_calls_same_nic": "同網卡重複查詢只執行一次 ethtool",
        "selftest.check_ethtool_calls_distinct_argv": "不同 ethtool argv 各自執行一次",
        "selftest.check_ethtool_calls_distinct_nics": "不同網卡不共用 ethtool 快取",
        "selftest.check_list_limit_unchanged": "未超過上限時不加說明行",
        "selftest.check_list_limit_truncated": "截斷時明列實際總數與未顯示筆數",
        "selftest.check_list_limit_empty": "空清單不產生輸出",
        "selftest.check_list_limit_disabled": "無上限或非正數上限不截斷",
        "selftest.check_report_perm_open_called": "報告建立器只呼叫 opener 一次",
        "selftest.check_report_perm_open_mode": "opener 明確收到 0600 mode",
        "selftest.check_report_perm_chmod_mode": "chmod 明確收到 0600 mode",
        # [CHANGE] 2026-08-03 待辦 #46：symlink 與 TOCTOU 兩道防護各自的檢查名稱。
        "selftest.check_report_perm_open_nofollow":
            "建檔旗標帶上不跟隨 symlink",
        "selftest.check_report_perm_chmod_takes_fd":
            "chmod 收到的是已開啟的 fd 而非路徑",

        # [CHANGE] 2026-08-02 選單 5～17 十一項實作（待辦 #16／#17／#18）。
        # 措辭與欄位逐項對齊 bash 版對應的 render_* 函式，差異一律在該區段的
        # 程式碼註解裡具名。
        #
        # ── 跨區段共用 ──
        # ★ IPv4／IPv6／狀態這三個標籤在 bash 的 render_bonds、render_bridges、
        #   render_ovs、render_vlan_subinterfaces 各自寫了一份字面值。這裡取
        #   共用 key：同一個標籤四份翻譯必然漂移，而漂移了不會有東西變紅。
        "net.ipv4": "IPv4",
        "net.ipv6": "IPv6",
        "net.state": "狀態",
        "net.no_ip_command": "找不到 ip 指令（iproute2）。",
        "app.list_truncated": "⋯ 以上為前 {limit} {unit}，實際共 {total} {unit}（未顯示 {hidden} {unit}；調整上限請設 LIST_LIMIT）",
        "unit.routes": "條路由",
        "unit.neighbours": "筆鄰居",
        # 介面類型（collect.sysfs.interface_type 的回傳鍵）
        "iftype.bond": "Bond",
        "iftype.bridge": "Linux Bridge",
        "iftype.physical": "實體網卡",
        "iftype.unknown": "未知",
        "iftype.other": "其他介面",

        # ── 選單 5：Bond ──
        "bond.label": "Bond 介面",
        "bond.mode": "Bond 模式",
        "bond.slaves": "成員網卡",
        "bond.hash_policy": "Hash Policy",
        "bond.active": "目前 Active",
        "bond.primary": "Primary Slave",
        "bond.lacp_rate": "LACP Rate",
        "bond.min_links": "Minimum Links",
        "bond.link": "Bond Link",
        "bond.member_states": "成員狀態：",
        "bond.slave_link": "Link",
        "bond.slave_speed": "Speed",
        "bond.slave_mac": "Permanent MAC",
        "bond.slave_agg": "Aggregator ID",
        "bond.up": "正常",
        "bond.down": "異常",
        "bond.none": "目前沒有執行中的 Bond 介面。",

        # ── 選單 6：Linux Bridge ──
        "bridge.label": "Bridge",
        "bridge.ports": "綁定 Port",
        "bridge.vlan_aware": "VLAN-aware",
        "bridge.vlan_proto": "VLAN 協定",
        "bridge.default_pvid": "Default PVID",
        "bridge.stp": "STP",
        "bridge.proto_dot1q": "802.1Q (0x8100)",
        "bridge.proto_qinq": "802.1ad QinQ (0x88a8)",
        "bridge.none": "目前沒有執行中的 Linux Bridge。",

        # ── 選單 7：Open vSwitch ──
        "ovs.label": "OVS Bridge",
        "ovs.ports_title": "  Port 明細：",
        "ovs.port": "Port",
        "ovs.tag": "VLAN Tag",
        "ovs.vlan_mode": "VLAN 模式",
        "ovs.members": "成員介面",
        "ovs.not_installed": "未安裝 Open vSwitch（openvswitch-switch），略過。",
        "ovs.not_installed_hint": "若此主機使用 Linux Bridge 建網，這是正常的。",
        "ovs.unreachable": "ovs-vsctl 存在但無法連線 ovsdb（openvswitch-switch 服務可能未執行）。",
        "ovs.unreachable_hint": "檢查指令：systemctl status openvswitch-switch",
        "ovs.no_bridges": "Open vSwitch 已安裝並執行，但沒有設定任何 OVS Bridge。",
        "ovs.bond_title": "OVS Bond 狀態",

        # ── 選單 8：VLAN 子介面 ──
        "vlansub.title": "傳統 VLAN 子介面",
        "vlansub.iface": "VLAN 介面",
        "vlansub.vid": "VLAN ID",
        "vlansub.parent": "上層介面",
        "vlansub.parent_type": "上層類型",
        "vlansub.none": "目前沒有執行中的 VLAN 子介面。",

        # ── 選單 11：VLAN 對帳 ──
        "vlanrec.title": "VLAN 對帳：Guest 使用的 VLAN vs Bridge Uplink 放行的 VLAN",
        "vlanrec.bridge": "Bridge",
        "vlanrec.uplink": "Uplink Port",
        "vlanrec.used": "Guest 用到的 VLAN",
        "vlanrec.missing": "Uplink 未放行",
        "vlanrec.verdict": "判定",
        "vlanrec.match": "相符",
        "vlanrec.check": "需檢查",
        "vlanrec.missing_item": "{vid}(VM {vmids})",
        "vlanrec.no_bridge_cmd": "找不到 bridge 指令，無法對帳。",
        "vlanrec.no_vlan_aware": "沒有 VLAN-aware Bridge，無需對帳。",
        "vlanrec.no_vlan_aware_hint": "若你的 VLAN 是以「傳統 VLAN 子介面 + 每 VLAN 一個 Bridge」方式建置，這是正常的。",
        "vlanrec.no_uplink": "VLAN-aware Bridge 上沒有可辨識的 Uplink Port（實體網卡／Bond／VLAN 子介面）。",
        "vlanrec.no_guest": "沒有 guest 網卡可對帳。",
        "vlanrec.note1": "說明：「Uplink 未放行」列出 guest 設了 VLAN tag，但該 Bridge 的 Uplink Port 在",
        "vlanrec.note2": "      bridge vlan 放行清單中查無此 VLAN 的情形，是 VLAN 不通最常見的原因。",
        "vlanrec.note3": "      若你的交換器 Port 設為 access（不打 tag），guest 端不應再設 tag，屬另一種情形。",

        # ── 選單 12：IP／路由／DNS／hosts／鄰居 ──
        "iprouting.addr4": "所有介面 IP 位址（IPv4）",
        "iprouting.addr6": "所有介面 IP 位址（IPv6）",
        "iprouting.route4": "IPv4 路由表",
        "iprouting.route6": "IPv6 路由表",
        "iprouting.dns": "DNS 設定（/etc/resolv.conf）",
        "iprouting.hosts": "/etc/hosts（PVE 叢集節點解析的依據）",
        "iprouting.neigh": "鄰居表（ARP / NDP，僅列 REACHABLE 與 STALE）",
        "iprouting.no_resolv": "找不到 /etc/resolv.conf。",
        "iprouting.no_hosts": "找不到 /etc/hosts。",
        "iprouting.neigh_note1": "註：本表已先濾掉 FAILED / INCOMPLETE 等狀態，非完整鄰居表；",
        "iprouting.neigh_note2": "    完整內容請執行 ip neigh show。",

        # ── 選單 13：PVE SDN ──
        "sdn.not_found": "找不到 {path}，此主機未使用 PVE SDN（或非 Proxmox VE）。",
        "sdn.empty": "SDN 目錄存在但沒有任何設定內容。",
        "sdn.file_title": "── {name}.cfg ──",
        "sdn.runtime_title": "SDN 執行期狀態（pvesh get /cluster/sdn）",
        "sdn.runtime_failed": "無法取得 SDN 執行期狀態。",

        # ── 選單 14：叢集網路 corosync ──
        "corosync.not_found": "找不到 {path}，此主機未加入叢集（單機 PVE 屬正常）。",
        "corosync.title": "corosync 環網設定",
        "corosync.node": "節點",
        "corosync.ring1_unset": "（未設定）",
        "corosync.single_ring_warn": "  ⚠ 未偵測到 ring1_addr：corosync 只有單一環網，該網路中斷即失去 quorum。",
        "corosync.cfgtool_title": "corosync 環網即時狀態",
        "corosync.cfgtool_failed": "無法取得 corosync 環網狀態（服務可能未執行）。",
        "corosync.pvecm_title": "pvecm status",
        "corosync.pvecm_failed": "無法取得 pvecm status。",

        # ── 選單 15：PVE 防火牆 ──
        "firewall.status_title": "pve-firewall status",
        "firewall.status_failed": "無法取得防火牆狀態。",
        "firewall.not_found": "找不到 pve-firewall，此主機可能不是 Proxmox VE。",
        "firewall.file_title": "── {path} ──",
        "firewall.host_title": "── 本節點 host.fw ──",

        # ── 選單 16：LLDP ──
        "lldp.not_installed": "尚未安裝 lldpd，無法查詢交換器與 Port。",
        "lldp.install_title": "安裝並啟用：",
        "lldp.install_hint": "交換器端也必須啟用 LLDP。",
        "lldp.inactive": "lldpd 目前未執行。",
        "lldp.inactive_hint": "啟動指令：systemctl enable --now lldpd",
        "lldp.none": "目前沒有收到 LLDP 鄰居資訊。",
        "lldp.check_title": "請確認：",
        "lldp.check1": "  1. lldpd 已執行",
        "lldp.check2": "  2. 交換器已啟用 LLDP",
        "lldp.check3": "  3. PVE 網卡直接連到交換器",
        "lldp.summary_title": "鄰居摘要",
        "lldp.local_iface": "本機介面",
        "lldp.sysname": "交換器名稱",
        "lldp.portid": "對端 Port",
        "lldp.portdescr": "Port 說明",
        "lldp.details_title": "完整鄰居明細",

        # ── 選單 17：持久化設定 ──
        "persistent.not_found": "找不到 {path}。",
        "persistent.file_title": "── {path} ──",
        "persistent.pending": "⚠ 偵測到 {path}.new：有網路設定已修改但尚未套用（需 reboot 或 ifreload -a）。",
    },

    "en": {
        # ── general ──
        "app.title": "PVE Network Audit Tool",
        "app.host": "Hostname",
        "app.time": "Timestamp",
        "app.need_root": "This script must be run as root.",
        "app.press_enter": "Press Enter to return to the menu...",
        "app.invalid_choice": "Invalid choice.",
        "app.back": "Back",
        "app.exit": "Exited.",
        "app.not_found": "Not found",
        "app.none": "none",
        "app.na": "N/A",
        "app.yes": "yes",
        "app.no": "no",
        "app.enabled": "enabled",
        "app.disabled": "disabled",
        "app.unknown": "unknown",
        # 見 zh-TW 段的說明：MUST 是 ": "（含尾隨空格），顯示寬度才與全形「：」相同。
        "app.kv_sep": ": ",

        # [CHANGE] 2026-08-02 keep menu, report, and CLI text aligned instead of embedding UI prose in dispatch code.
        # ── main menu ──
        "menu.prompt": "Select an audit item:",
        "menu.input": "Enter an option [{range}]: ",
        "menu.group_phys": "Physical layer",
        "menu.group_l2": "Layer 2",
        "menu.group_l3": "Layer 3 and PVE",
        "menu.group_overall": "Overall",
        "menu.group_added": "Added by the Python version (not in the bash version)",
        "menu.not_implemented": "Not implemented yet (todo #{todo})",
        "menu.nic_status": "Physical NIC status and RX/TX",
        "menu.nic_health": "NIC health: link flaps, errors, drops, firmware",
        "menu.nic_modules": "SFP/QSFP module details",
        "menu.nic_led": "Physical NIC LED identification",
        "menu.bond": "Bond configuration and member state",
        "menu.bridge": "Linux Bridge",
        "menu.ovs": "Open vSwitch",
        "menu.vlan_sub": "VLAN sub-interfaces",
        "menu.bridge_vlan": "Bridge VLAN filter (per-port allowed list)",
        "menu.guest_nics": "VM/CT NIC mapping (tap/veth to VMID)",
        "menu.vlan_reconcile": "VLAN reconciliation (guest VLAN vs uplink allowance)",
        "menu.ip_routing": "IP / routes / DNS / hosts / neighbour table",
        "menu.sdn": "PVE SDN",
        "menu.corosync": "Cluster network (corosync)",
        "menu.firewall": "PVE firewall",
        "menu.lldp": "LLDP switch and port",
        "menu.persistent": "/etc/network/interfaces persistent configuration",
        "menu.view_all": "View all available items in sequence",
        "menu.full_report": "Write a complete audit report",
        "menu.self_test": "Run the built-in self-test",
        "menu.sysctl": "sysctl networking parameters",
        "menu.conntrack": "conntrack capacity",
        "menu.neigh": "Neighbour table capacity (ARP/NDP gc_thresh)",
        "menu.autostart": "Autostart reconciliation (auto/hotplug)",
        "menu.exit": "Exit",
        # [CHANGE] 2026-08-02 待辦 #25：與 zh-TW 段同一批。
        "lang.native_name": "English",
        "menu.switch_lang": "Switch language ({target})",
        "menu.pick_nic": "Select the NIC number to identify: ",

        # ── complete report ──
        "report.title": "Complete PVE Network Audit Report",
        "report.kernel": "Kernel version",
        "report.pve_version": "PVE version",
        "report.generated_at": "Generated at",
        "report.tool_version": "Tool version",
        "report.generating": "Generating: {title}",
        "report.done": "Complete audit report written to: {path}",
        "report.mkdir_failed": "Unable to create report directory: {path}",
        "report.create_failed": "Unable to create report file: {path}",

        # ── CLI ──
        "cli.unknown_option": "Unknown option: {option}",
        "cli.usage_synopsis": "Usage:\n  {prog}                 Start the interactive menu\n  {prog} --report        Write a complete report non-interactively (for cron)\n  {prog} --self-test     Run only the built-in self-test; do not read network state\n  {prog} --version       Show the version\n  {prog} --help          Show this help",
        # [CHANGE] 2026-08-02 待辦 #24：與 zh-TW 段同一批修正（移除未實作的 LIST_LIMIT、
        #          補上四個有實作卻沒列的變數）。兩語 MUST 列出完全相同的變數集合，
        #          由 tests/test_cli.py 的對帳判準守。
        "cli.usage_env": "Environment variables:\n  REPORT_DIR        Report output directory (default: /root)\n  LIST_LIMIT        Display cap for route/neighbour lists (default: 50; truncation is stated explicitly)\n  SAMPLE_SECONDS    RX/TX sampling duration (default: 3)\n  BLINK_SECONDS     LED identification duration (default: 10)\n  COMMAND_TIMEOUT   External command timeout in seconds (default: 15; a timeout is reported as a timeout, never as 'not installed')\n  PVE_CONF_ROOT     PVE configuration root (default: /etc/pve)\n  PVE_AUDIT_LANG    Interface language zh/en (PVE locale is usually C, so English by default)\n  NO_PAGER          Set to 1 to disable the less/more pager\n  TERM_WIDTH        Force the layout width; highest priority\n  COLUMNS           Layout width fallback (lower priority than the entry above)\n  LC_ALL/LC_MESSAGES/LANG    Standard locale, used as the language fallback",
        "cli.usage_note": "Note: reports contain the corosync cluster topology and node IPs, firewall rules,\n      and /etc/hosts, so files are created as 0600. Check permissions for shared directories.",
        "cli.usage_deps": "Dependencies:\n  Required     iproute2 (ip, bridge)\n  Recommended  ethtool (speed, duplex, media, firmware, LED)\n               lldpd (switch and port mapping)\n  Optional     openvswitch-switch (OVS environments only)",

        # ── link state ──
        "link.up": "Up",
        "link.down": "Down",
        "link.unknown": "Unknown",
        "traffic.yes": "Active",
        "traffic.no": "Idle",

        # ── media type ──
        "media.rj45": "RJ45 copper",
        "media.fiber": "Fibre",
        "media.dac": "DAC copper",
        "media.aoc": "AOC active",
        "media.backplane": "Backplane",
        "media.unknown": "Unknown",

        # ── physical NIC table ──
        "nic.iface": "Iface",
        "nic.mac": "MAC Address",
        "nic.link": "Link",
        "nic.speed": "Speed",
        "nic.duplex": "Duplex",
        "nic.mtu": "MTU",
        "nic.media": "Media",
        "nic.rx": "RX",
        "nic.tx": "TX",
        "nic.driver": "Driver",
        "nic.pci": "PCI address",
        # [CHANGE] 2026-08-02 待辦 #17：與 zh-TW 段同一批（SFP/QSFP 模組明細）。
        "module.header": "── {nic} ── medium: {medium}",
        "module.vendor": "Vendor",
        "module.pn": "Part number",
        "module.sn": "Serial number",
        "module.connector": "Connector",
        "module.type": "Transceiver type",
        "module.cable_tech": "Cable technology",
        "module.length_copper": "Copper length",
        "module.temperature": "Temperature",
        "module.voltage": "Voltage",
        "module.tx_power": "Laser output power",
        "module.rx_power": "Receiver optical power",
        "module.none": "No readable SFP/QSFP module detected (normal for RJ45 copper NICs).",
        # [CHANGE] 2026-08-02 待辦 #26：與 zh-TW 段同一批（移除 nic.autostart／nic.comment）。
        "nic.none_found": "No physical NIC found.",
        "nic.sampling": "Sampling RX/TX counters for {sec}s...",
        "nic.traffic_note": "Note: RX/TX shows whether counters advanced during the {sec}s sample; idle does not imply a fault.",
        # [CHANGE] 2026-08-03 待辦 #35 補正：與 zh-TW 段同一批（不再斷言「未安裝」）。
        # [CHANGE] 2026-08-03 待辦 #41：見 zh-TW 側同位置的說明。
        "nic.ethtool_missing": "ethtool could not be executed (it may not be installed, or the file may not be executable).",
        # [CHANGE] 2026-08-03 待辦 #35：英文與中文必須保有相同的成因分流契約。
        "nic.ethtool_failed": "ethtool is installed but failed to run (possibly insufficient privileges or an unsupported driver).",
        # [CHANGE] 2026-08-03 待辦 #35 補正：與 zh-TW 段同一批（成因未知不斷言安裝與否）。
        "nic.ethtool_unknown": "Failed to read ethtool information; the reason could not be determined.",
        "nic.ethtool_timeout": "ethtool timed out; the host or driver did not respond within the limit. Adjust the limit with the COMMAND_TIMEOUT environment variable.",
        "nic.ethtool_affected": "The following fields will show N/A: {fields}.",
        "nic.ethtool_scope_link": "speed and duplex",
        "nic.ethtool_scope_driver": "driver details",
        "nic.ethtool_scope_sep": ", ",

        # ── NIC health ──
        "health.state": "State",
        "health.carrier_changes": "Link flaps",
        "health.autoneg": "Autoneg",
        "health.rx_err": "RX err",
        "health.rx_drop": "RX drop",
        "health.tx_err": "TX err",
        "health.tx_drop": "TX drop",
        "health.crc": "CRC err",
        "health.numa": "NUMA",
        "health.firmware": "Firmware",
        "health.note_flap": "Note: Link flaps = carrier_changes; 1-2 is normal after boot. A rising count means the link or module is flapping.",
        "health.note_crc": "      A non-zero CRC count is almost always physical (cable, module, peer port).",

        # ── autostart reconciliation ──
        "autostart.configured": "Configured",
        "autostart.running": "Running",
        "autostart.verdict": "Verdict",
        "autostart.ok": "Match",
        "autostart.running_not_auto": "* Up but no autostart - will disappear after reboot",
        "autostart.auto_not_running": "* Autostart set but not up - it failed to come up at boot",
        "autostart.note": "Note: a mismatch here is the most common cause of 'the network vanished after a reboot'.",

        # ── VLAN ──
        "bridgevlan.port": "Port",
        "bridgevlan.type": "Type",
        "bridgevlan.pvid": "PVID",
        "bridgevlan.allowed": "Allowed VLANs",
        "bridgevlan.uplink": "Uplink",
        "bridgevlan.guest": "Guest iface",
        "bridgevlan.self": "Bridge itself",

        # ── VM/CT ──
        "guest.vmid": "VMID",
        "guest.kind": "Kind",
        "guest.name": "Name",
        "guest.netid": "Net",
        "guest.iface": "Iface",
        # [CHANGE] 2026-08-02 待辦 #26：與 zh-TW 段同一批。
        "guest.mac": "MAC",
        "guest.bridge": "Bridge",
        "guest.tag": "VLAN tag",
        "guest.mtu": "MTU",
        "guest.firewall": "Firewall",
        "guest.state": "Iface state",
        "guest.running": "running",
        "guest.stopped": "stopped",
        "guest.none": "No VM or CT with a configured NIC was found.",

        # ── sysctl ──
        "sysctl.key": "Parameter",
        "sysctl.value": "Value",
        "sysctl.note": "Note",
        "sysctl.bridge_nf_warn": "* Enabled - bridged traffic is filtered by iptables; VMs on the same bridge may not reach each other",

        # ── conntrack / neighbour ──
        "conntrack.used": "In use",
        "conntrack.max": "Max",
        "conntrack.usage": "Usage",
        "conntrack.warn": "* High usage - once full, connections are dropped at random",
        "neigh.current": "Entries",
        "neigh.thresh": "GC thresholds",
        "neigh.warn": "* Approaching gc_thresh3 - beyond it, hosts start becoming unreachable at random",

        # [CHANGE] 2026-08-02 keep pager, LED, and self-test text aligned across both languages.
        # ── pager ──
        "pager.scroll_hint": "(Up/Down scroll  Left/Right horizontal scroll  / search  q return to menu)",

        # ── LED identification ──
        "led.title": "Select a physical NIC to identify",
        "led.need_ethtool": "ethtool is required for NIC LED identification.",
        "led.install_hint": "Install with: apt update && apt install -y ethtool",
        "led.no_nic": "No physical NIC found.",
        "led.blinking": "Blinking the LED on {nic} for {seconds} seconds (the screen will pause)...",
        "led.done": "LED identification complete.",
        "led.unsupported": "This NIC or driver does not support LED identification.",
        "led.monitor_hint": "Run ip monitor link in another terminal, then unplug and reconnect the cable on site.",

        # ── built-in self-test ──
        "selftest.title": "PVE Network Audit Tool v{version} — Built-in Self-test",
        "selftest.group_width": "1. Display width calculation (CJK full-width uses 2 columns)",
        "selftest.group_vlan": "2. VLAN list expansion and compression",
        "selftest.group_guest": "3. VM/CT NIC configuration parsing",
        "selftest.group_netconf": "4. Interface configuration parsing",
        "selftest.group_i18n": "5. Bilingual message table alignment",
        # [CHANGE] 2026-08-03 TODO #30: expose the six added contracts in self-test output.
        "selftest.group_sysfs": "6. sysfs read failures and empty values",
        "selftest.group_medium": "7. Network medium semantic-field detection",
        "selftest.group_bridgevlan": "8. Indented bridge VLAN output parsing",
        "selftest.group_ethtool_calls": "9. ethtool command caching",
        "selftest.group_list_limit": "10. List truncation disclosure",
        "selftest.group_report_perm": "11. Report file creation permissions",
        "selftest.scope": "{count} checks in scope",
        "selftest.detail_fail": "expected=[{expected}] actual=[{actual}]",
        "selftest.summary": "Self-test: {passed} passed, {failed} failed, {skipped} skipped",
        "selftest.has_failure": "One or more checks failed. The tool's decision logic may have regressed; do not rely on this audit result.",
        "selftest.all_passed": "All checks passed.",
        "selftest.result_pass": "  [PASS] {name} = {actual}",
        "selftest.result_fail": "  [FAIL] {name} {detail}",
        "selftest.result_skip": "  [SKIP] {name}{reason}",
        "selftest.skip_reason": " — Reason: {reason}",
        "selftest.check_width_ascii": "disp_width('Link')",
        # [CHANGE] 2026-08-02 這兩條原本譯成 disp_width('wired') 與
        #          disp_width('RJ45 copper')，把**測試資料本身**一起翻掉了。
        #          它們不是描述性名稱而是「函式呼叫的字面」，而實際執行的仍是
        #          CJK 字串：英文使用者會看到 disp_width('wired') = 6，可是
        #          disp_width("wired") 其實是 5——那個已知答案就變成沒辦法複核。
        #          ★ 這兩條檢查的重點正是「CJK 全形計 2 欄」，樣本翻成英文就
        #          失去意義了。字面 MUST 與 zh-TW 逐字相同（見 test_自檢項名稱裡
        #          的輸入樣本不得被翻譯）。
        "selftest.check_width_cjk": "disp_width('已接線')",
        "selftest.check_width_mixed": "disp_width('RJ45 電口')",
        "selftest.check_width_pad": "pad reaches display width 10",
        "selftest.check_width_no_truncate": "pad does not truncate overflow",
        "selftest.check_width_truncate": "truncate stays within its width",
        "selftest.check_vlan_expand": "expand 10,20-23,30",
        "selftest.check_vlan_empty": "empty input expands to an empty set",
        "selftest.check_vlan_roundtrip": "compress then expand preserves the set",
        "selftest.check_vlan_contains": "range contains VLAN 22",
        "selftest.check_vlan_excludes": "range excludes VLAN 24",
        "selftest.check_guest_fields": "extract MAC, bridge, and tag",
        "selftest.check_guest_kv": "key-value parser strips whitespace",
        "selftest.check_guest_mac": "recognise a valid MAC",
        "selftest.check_guest_bad_mac": "reject an incomplete MAC",
        "selftest.check_netconf_join": "join backslash continuation",
        "selftest.check_netconf_stanza": "classify a top-level directive",
        "selftest.check_netconf_comment": "classify a comment line",
        "selftest.check_netconf_blank": "classify a blank line",
        "selftest.check_netconf_auto": "parse auto interface list",
        "selftest.check_i18n_diff": "bilingual key difference is empty",
        "selftest.check_i18n_empty": "bilingual messages have no empty values",
        "selftest.check_i18n_languages": "self-test covers both language tables",
        # [CHANGE] 2026-08-03 TODO #30: describe the guarded property; fixtures stay in selftest.py.
        "selftest.check_sysfs_value": "a readable sysfs attribute returns stripped content",
        "selftest.check_sysfs_missing": "a missing sysfs path quietly returns its default",
        "selftest.check_sysfs_directory": "a directory used as a sysfs attribute quietly returns its default",
        "selftest.check_sysfs_blank": "a blank sysfs attribute returns its default",
        "selftest.check_medium_rj45": "Twisted Pair is classified as RJ45",
        "selftest.check_medium_backplane": "a Backplane port is classified as backplane",
        "selftest.check_medium_aui": "an AUI port is classified as AUI",
        "selftest.check_medium_mii": "an MII port is classified as MII",
        "selftest.check_medium_dac": "unrelated optical text does not stop passive copper being DAC",
        "selftest.check_medium_aoc": "the Active Cable semantic field is classified as AOC",
        "selftest.check_medium_fiber": "an LC connector semantic field is classified as fibre",
        "selftest.check_medium_unavailable": "the medium is unknown when ethtool data is unavailable",
        "selftest.check_medium_base_t": "the 1000BASE-T RJ45 rule precedes copper length",
        "selftest.check_medium_dac_no_lengths": "passive copper remains DAC without length fields",
        "selftest.check_medium_length_counterfactual": "changing only fibre length flips the DAC fixture to fibre",
        "selftest.check_bridgevlan_ports": "each port has the correct VLAN list and PVID",
        "selftest.check_bridgevlan_header": "the header is not treated as a port",
        "selftest.check_bridgevlan_continuation": "an indented VLAN continuation is not treated as a port",
        "selftest.check_bridgevlan_count": "the parsed port count is correct",
        "selftest.check_bridgevlan_expand": "a de-tagged list joins correctly to VLAN expansion",
        # [CHANGE] 2026-08-03 待辦 #30 補正：與 zh-TW 段同一批。
        "selftest.check_bridgevlan_nonnumeric": "continuation fields not starting with a digit are ignored",
        "selftest.check_ethtool_calls_same_nic": "repeated queries for one NIC execute ethtool once",
        "selftest.check_ethtool_calls_distinct_argv": "distinct ethtool argv each execute once",
        "selftest.check_ethtool_calls_distinct_nics": "different NICs do not share an ethtool cache entry",
        "selftest.check_list_limit_unchanged": "a list within the cap gains no explanatory line",
        "selftest.check_list_limit_truncated": "truncation states the total and hidden counts",
        "selftest.check_list_limit_empty": "an empty list produces no output",
        "selftest.check_list_limit_disabled": "no cap or a non-positive cap does not truncate",
        "selftest.check_report_perm_open_called": "the report writer calls its opener once",
        "selftest.check_report_perm_open_mode": "the opener explicitly receives mode 0600",
        "selftest.check_report_perm_chmod_mode": "chmod explicitly receives mode 0600",
        # [CHANGE] 2026-08-03 待辦 #46：symlink 與 TOCTOU 兩道防護各自的檢查名稱。
        "selftest.check_report_perm_open_nofollow":
            "the create flags include no-follow-symlink",
        "selftest.check_report_perm_chmod_takes_fd":
            "chmod receives the open fd rather than a path",

        # [CHANGE] 2026-08-02 選單 5～17 十一項實作（待辦 #16／#17／#18）。
        # ── shared ──
        "net.ipv4": "IPv4",
        "net.ipv6": "IPv6",
        "net.state": "State",
        "net.no_ip_command": "The ip command (iproute2) was not found.",
        "app.list_truncated": "... the above are the first {limit} {unit}; {total} in total ({hidden} not shown; set LIST_LIMIT to change the cap)",
        "unit.routes": "routes",
        "unit.neighbours": "neighbours",
        "iftype.bond": "Bond",
        "iftype.bridge": "Linux Bridge",
        "iftype.physical": "Physical NIC",
        "iftype.unknown": "unknown",
        "iftype.other": "Other interface",

        # ── menu 5: Bond ──
        "bond.label": "Bond interface",
        "bond.mode": "Bond mode",
        "bond.slaves": "Member NICs",
        "bond.hash_policy": "Hash policy",
        "bond.active": "Currently active",
        "bond.primary": "Primary slave",
        "bond.lacp_rate": "LACP rate",
        "bond.min_links": "Minimum links",
        "bond.link": "Bond link",
        "bond.member_states": "Member state:",
        "bond.slave_link": "Link",
        "bond.slave_speed": "Speed",
        "bond.slave_mac": "Permanent MAC",
        "bond.slave_agg": "Aggregator ID",
        "bond.up": "OK",
        "bond.down": "failed",
        "bond.none": "No running bond interface.",

        # ── menu 6: Linux Bridge ──
        "bridge.label": "Bridge",
        "bridge.ports": "Bound ports",
        "bridge.vlan_aware": "VLAN-aware",
        "bridge.vlan_proto": "VLAN protocol",
        "bridge.default_pvid": "Default PVID",
        "bridge.stp": "STP",
        "bridge.proto_dot1q": "802.1Q (0x8100)",
        "bridge.proto_qinq": "802.1ad QinQ (0x88a8)",
        "bridge.none": "No running Linux Bridge.",

        # ── menu 7: Open vSwitch ──
        "ovs.label": "OVS bridge",
        "ovs.ports_title": "  Port detail:",
        "ovs.port": "Port",
        "ovs.tag": "VLAN tag",
        "ovs.vlan_mode": "VLAN mode",
        "ovs.members": "Member interfaces",
        "ovs.not_installed": "Open vSwitch (openvswitch-switch) is not installed; skipped.",
        "ovs.not_installed_hint": "This is normal if the host uses Linux Bridge networking.",
        "ovs.unreachable": "ovs-vsctl exists but cannot reach ovsdb (the openvswitch-switch service may not be running).",
        "ovs.unreachable_hint": "Check with: systemctl status openvswitch-switch",
        "ovs.no_bridges": "Open vSwitch is installed and running, but no OVS bridge is configured.",
        "ovs.bond_title": "OVS bond state",

        # ── menu 8: VLAN sub-interfaces ──
        "vlansub.title": "Traditional VLAN sub-interfaces",
        "vlansub.iface": "VLAN interface",
        "vlansub.vid": "VLAN ID",
        "vlansub.parent": "Parent interface",
        "vlansub.parent_type": "Parent type",
        "vlansub.none": "No running VLAN sub-interface.",

        # ── menu 11: VLAN reconciliation ──
        "vlanrec.title": "VLAN reconciliation: VLANs used by guests vs VLANs allowed on the bridge uplink",
        "vlanrec.bridge": "Bridge",
        "vlanrec.uplink": "Uplink port",
        "vlanrec.used": "VLANs used by guests",
        "vlanrec.missing": "Not allowed on uplink",
        "vlanrec.verdict": "Verdict",
        "vlanrec.match": "match",
        "vlanrec.check": "check needed",
        "vlanrec.missing_item": "{vid}(VM {vmids})",
        "vlanrec.no_bridge_cmd": "The bridge command was not found; cannot reconcile.",
        "vlanrec.no_vlan_aware": "No VLAN-aware bridge; nothing to reconcile.",
        "vlanrec.no_vlan_aware_hint": "This is normal if your VLANs use traditional sub-interfaces with one bridge per VLAN.",
        "vlanrec.no_uplink": "No recognisable uplink port (physical NIC / bond / VLAN sub-interface) on the VLAN-aware bridge.",
        "vlanrec.no_guest": "No guest NIC to reconcile.",
        "vlanrec.note1": "Note: \"Not allowed on uplink\" lists VLAN tags set on guests that are absent from the",
        "vlanrec.note2": "      bridge vlan allowance list of that bridge's uplink port. This is the most common",
        "vlanrec.note3": "      cause of a VLAN not working. If the switch port is an access port (untagged), the guest should not set a tag; that is a different case.",

        # ── menu 12: IP / routes / DNS / hosts / neighbours ──
        "iprouting.addr4": "IP addresses on all interfaces (IPv4)",
        "iprouting.addr6": "IP addresses on all interfaces (IPv6)",
        "iprouting.route4": "IPv4 routing table",
        "iprouting.route6": "IPv6 routing table",
        "iprouting.dns": "DNS configuration (/etc/resolv.conf)",
        "iprouting.hosts": "/etc/hosts (what PVE cluster node resolution relies on)",
        "iprouting.neigh": "Neighbour table (ARP / NDP, REACHABLE and STALE only)",
        "iprouting.no_resolv": "/etc/resolv.conf was not found.",
        "iprouting.no_hosts": "/etc/hosts was not found.",
        "iprouting.neigh_note1": "Note: FAILED / INCOMPLETE entries are filtered out, so this is not the full table;",
        "iprouting.neigh_note2": "    run ip neigh show for the complete content.",

        # ── menu 13: PVE SDN ──
        "sdn.not_found": "{path} was not found; this host does not use PVE SDN (or is not Proxmox VE).",
        "sdn.empty": "The SDN directory exists but contains no configuration.",
        "sdn.file_title": "-- {name}.cfg --",
        "sdn.runtime_title": "SDN runtime state (pvesh get /cluster/sdn)",
        "sdn.runtime_failed": "Could not retrieve the SDN runtime state.",

        # ── menu 14: cluster network (corosync) ──
        "corosync.not_found": "{path} was not found; this host has not joined a cluster (normal for a standalone PVE).",
        "corosync.title": "corosync ring configuration",
        "corosync.node": "Node",
        "corosync.ring1_unset": "(not set)",
        "corosync.single_ring_warn": "  WARNING: no ring1_addr detected. corosync has a single ring; losing that network loses quorum.",
        "corosync.cfgtool_title": "corosync ring live state",
        "corosync.cfgtool_failed": "Could not retrieve the corosync ring state (the service may not be running).",
        "corosync.pvecm_title": "pvecm status",
        "corosync.pvecm_failed": "Could not retrieve pvecm status.",

        # ── menu 15: PVE firewall ──
        "firewall.status_title": "pve-firewall status",
        "firewall.status_failed": "Could not retrieve the firewall status.",
        "firewall.not_found": "pve-firewall was not found; this host may not be Proxmox VE.",
        "firewall.file_title": "-- {path} --",
        "firewall.host_title": "-- host.fw of this node --",

        # ── menu 16: LLDP ──
        "lldp.not_installed": "lldpd is not installed; cannot query the switch and port.",
        "lldp.install_title": "Install and enable:",
        "lldp.install_hint": "LLDP must also be enabled on the switch.",
        "lldp.inactive": "lldpd is not running.",
        "lldp.inactive_hint": "Start it with: systemctl enable --now lldpd",
        "lldp.none": "No LLDP neighbour information received.",
        "lldp.check_title": "Please confirm:",
        "lldp.check1": "  1. lldpd is running",
        "lldp.check2": "  2. LLDP is enabled on the switch",
        "lldp.check3": "  3. the PVE NIC is connected directly to the switch",
        "lldp.summary_title": "Neighbour summary",
        "lldp.local_iface": "Local interface",
        "lldp.sysname": "Switch name",
        "lldp.portid": "Peer port",
        "lldp.portdescr": "Port description",
        "lldp.details_title": "Full neighbour detail",

        # ── menu 17: persistent configuration ──
        "persistent.not_found": "{path} was not found.",
        "persistent.file_title": "-- {path} --",
        "persistent.pending": "WARNING: {path}.new detected. Network configuration has been changed but not applied (needs a reboot or ifreload -a).",
    },
}

_current = DEFAULT_LANG
MISSING = []


def available_langs():
    return sorted(MESSAGES)


def _normalise(raw):
    if not raw:
        return None
    token = raw.split(".")[0].split("@")[0].strip().lower()
    if token in _ALIASES:
        return _ALIASES[token]
    prefix = token.split("_")[0].split("-")[0]
    return _ALIASES.get(prefix)


def set_lang(lang=None, env=None):
    """設定語言。lang 為 None 時依環境變數推導。回傳實際採用的語言。"""
    global _current
    env = os.environ if env is None else env

    candidates = [lang, env.get("PVE_AUDIT_LANG"),
                  env.get("LC_ALL"), env.get("LC_MESSAGES"), env.get("LANG")]
    for cand in candidates:
        resolved = _normalise(cand)
        if resolved and resolved in MESSAGES:
            _current = resolved
            return _current

    _current = DEFAULT_LANG
    return _current


def current_lang():
    return _current


# [CHANGE] 2026-08-02 待辦 #25：選單內即時切換語系。
def next_lang(current=None):
    """回傳輪替到的下一個語言。

    ★ 語言集合是從 MESSAGES 推導的**衍生值**，不寫死語言名。寫成
      {"en": "zh-TW", "zh-TW": "en"} 的對照表在兩語系下正確，但新增第三語系
      時它會**靜默地永遠跳過那一個**——輪不到的語系不會讓任何測試變紅。
      同一道教訓在 selftest 的 i18n 檢查上已經踩過一次（見交接檔發現 8）。
    ★ 當前語言不在集合裡時回第一個，而不是拋例外：這條路徑只有在 MESSAGES
      被動過手腳時才會走到，屆時讓使用者看到某個語言，比讓工具當掉好。
    """
    langs = available_langs()
    if not langs:
        return DEFAULT_LANG
    now = current_lang() if current is None else current
    if now not in langs:
        return langs[0]
    return langs[(langs.index(now) + 1) % len(langs)]


def lang_display_name(lang):
    """語言的自稱名（用該語言自己的文字寫），查不到時退回語言代碼。

    ★ 刻意讓每個語系在自己的訊息表裡宣告 lang.native_name，而不是在別處
      維護一份 {代碼: 名稱} 對照——那會是第二份記載，新增語系時漏改不會變紅。
    """
    return MESSAGES.get(lang, {}).get("lang.native_name", lang)


def _needs_args(text):
    """[CHANGE] 2026-07-31 新增：訊息本身有沒有帶具名佔位符。

    有佔位符卻沒收到參數，代表呼叫端漏帶——那要吵，不能把 {sec} 原樣印進報告。
    """
    try:
        for _literal, field, _spec, _conv in string.Formatter().parse(text):
            if field is not None:
                return True
    except ValueError:
        return True  # 格式字串自己壞掉，交給 t() 走 format 路徑去吵
    return False


def t(key, **kwargs):
    """取訊息。缺 key 時回傳醒目標記並記錄，不靜默回空字串。"""
    table = MESSAGES.get(_current, {})
    text = table.get(key)

    if text is None:
        # 退回預設語言，仍找不到才算真的缺
        text = MESSAGES.get(DEFAULT_LANG, {}).get(key)
        if text is None:
            if key not in MISSING:
                MISSING.append(key)
            return "⟪ MISSING:%s ⟫" % key

    # [CHANGE] 2026-07-31 原本是 `if kwargs:`，於是呼叫端忘了帶參數時會靜默把
    # 「正在取樣 RX/TX 流量 {sec} 秒...」原樣印進盤查報告。本模組的設計原則是
    # 「缺東西必須吵」，缺 key 會吵、缺參數卻不吵並不一致——改成只要訊息本身
    # 帶佔位符就一律走 format，缺參數即回 ⟪ BADFORMAT ⟫。
    if kwargs or _needs_args(text):
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError) as exc:
            # ValueError：訊息表自己的格式字串壞掉（單獨的 { ），一樣要吵
            if key not in MISSING:
                MISSING.append(key)
            return "⟪ BADFORMAT:%s(%s) ⟫" % (key, exc)
    return text


def missing_keys():
    return list(MISSING)


def reset_missing():
    del MISSING[:]


def key_diff():
    """回傳各語言相對於「所有語言 key 聯集」缺少的 key。全部對齊時每項皆為空集合。"""
    union = set()
    for table in MESSAGES.values():
        union |= set(table)
    return {lang: sorted(union - set(table)) for lang, table in MESSAGES.items()}


def empty_values():
    """回傳翻譯為空字串或純空白的 (lang, key)。"""
    out = []
    for lang, table in MESSAGES.items():
        for key, value in sorted(table.items()):
            if not str(value).strip():
                out.append((lang, key))
    return out


set_lang()
