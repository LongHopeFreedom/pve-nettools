# [CHANGE] 2026-08-02 內建自檢只驗純函式已知答案，讓系統取值前即可發現判定退化。
# [CHANGE] 2026-08-03 待辦 #30 補正（code review P2）：上面那句已經不完全成立。
#          新增的六類裡，`_checks_sysfs()` 會在 `tempfile.TemporaryDirectory()` 內
#          建立真實檔案，`_checks_report_perm()` 也會實際寫出一份報告。
#          ⇒ 檔首說明改寫如下。**碼改了而註解沒跟著改，會讓下一個人誤判失敗成因**
#          （例如在不可建暫存檔的環境上跑 --self-test 失敗時，照舊註解會排除
#          檔案系統這個可能性）。
"""平台無關的內建自檢與純排版。

不讀取任何**系統狀態**（不碰真實 sysfs、不執行 ethtool、不讀 PVE 設定檔）：
外部指令一律以注入的假 run_fn 取代，所有期望值都是可人工複核的已知答案。

★ 但**會使用隔離的暫存資源**：sysfs 讀取那一類需要真的建立檔案才驗得到
「讀不到時安靜回 default」，報告權限那一類需要真的寫出一份報告才驗得到
建立時的 mode。兩者都在 `tempfile.TemporaryDirectory()` 內完成、用完即刪。
"""

import contextlib
import io
import os
import subprocess
import tempfile

from . import __version__
from . import i18n, width
# [CHANGE] 2026-08-03 待辦 #30：把六類既有產品契約納入內建自檢，讓離線自檢也能守住。
from . import report
from .collect import bridge, ethtool, netconf, pve, sysfs
from .i18n import t
from .render import base

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"


def _check(group, name, expected, actual):
    return {"group": group, "name": name, "expected": expected,
            "actual": actual}


def _checks_sysfs():
    """read_value 的四種 I/O 結果；暫存樹只在 actual 執行時存在。"""
    def probe(kind):
        # [CHANGE] 2026-08-03 待辦 #30：資源在 callable 內自理，匯入模組不應碰檔案系統。
        with tempfile.TemporaryDirectory() as directory:
            reader = sysfs.SysfsReader(root=directory)
            nic = os.path.join(directory, "eno1")
            os.mkdir(nic)
            target = os.path.join(nic, kind)
            if kind == "mtu":
                with open(target, "w", encoding="utf-8") as stream:
                    stream.write("1500\n")
            elif kind == "directory":
                os.mkdir(target)
            elif kind == "blank":
                with open(target, "w", encoding="utf-8") as stream:
                    stream.write("  \n")
            return reader.read_value("eno1", kind, default="DEFAULT")

    def quiet_probe(kind):
        output = io.StringIO()
        errors = io.StringIO()
        # [CHANGE] 2026-08-03 待辦 #30：回 default 還不夠，錯誤文字也不得洩漏到自檢輸出。
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            value = probe(kind)
        return value, output.getvalue(), errors.getvalue()

    group = "selftest.group_sysfs"
    return [
        _check(group, "selftest.check_sysfs_value", "1500",
               lambda: probe("mtu")),
        _check(group, "selftest.check_sysfs_missing", "DEFAULT",
               lambda: probe("missing")),
        _check(group, "selftest.check_sysfs_directory", ("DEFAULT", "", ""),
               lambda: quiet_probe("directory")),
        _check(group, "selftest.check_sysfs_blank", "DEFAULT",
               lambda: probe("blank")),
    ]


def _checks_medium():
    """媒介判定只讀 Port、Connector、Transceiver type 與線長等語意欄。"""
    link_template = "Settings for eno1:\n\tPort: %s\n\tLink detected: yes\n"
    dac = ("Connector: 0x21 (Copper pigtail)\n"
           "Transceiver type: 10G Ethernet: 10G Base-CR\n"
           "Length (SMF): 0m\nLength (50um): 0m\n"
           "Length (Copper): 3m\n")

    def completed(stdout="", returncode=0, stderr=""):
        return subprocess.CompletedProcess([], returncode, stdout, stderr)

    def value(port, eeprom=""):
        def run(argv):
            if "-m" in argv:
                return completed(eeprom)
            return completed(link_template % port)
        return ethtool.EthtoolReader(run_fn=run).medium("eno1")["medium"]

    def unavailable_contract():
        def run(_argv):
            raise FileNotFoundError("ethtool")
        result = ethtool.EthtoolReader(run_fn=run).medium("eno1")
        return result["status"], result["medium"]

    def counterfactual():
        before = value("FIBRE", dac)
        after = value("FIBRE", dac.replace("Length (50um): 0m",
                                            "Length (50um): 80m"))
        return before, after

    # [CHANGE] 2026-08-03 待辦 #30：每個可判定常數都有陽性案，另以只改線長的反事實守欄位語意。
    group = "selftest.group_medium"
    return [
        _check(group, "selftest.check_medium_rj45", ethtool.MEDIUM_RJ45,
               lambda: value("Twisted Pair")),
        _check(group, "selftest.check_medium_backplane",
               ethtool.MEDIUM_BACKPLANE, lambda: value("Backplane")),
        _check(group, "selftest.check_medium_aui", ethtool.MEDIUM_AUI,
               lambda: value("AUI")),
        _check(group, "selftest.check_medium_mii", ethtool.MEDIUM_MII,
               lambda: value("MII")),
        _check(group, "selftest.check_medium_dac", ethtool.MEDIUM_DAC,
               lambda: value("FIBRE", dac)),
        _check(group, "selftest.check_medium_aoc", ethtool.MEDIUM_AOC,
               lambda: value("FIBRE", "Cable technology: Active Cable\n")),
        _check(group, "selftest.check_medium_fiber", ethtool.MEDIUM_FIBER,
               lambda: value("FIBRE", "Connector: 0x07 (LC)\n")),
        _check(group, "selftest.check_medium_unavailable",
               ("unavailable", None), unavailable_contract),
        _check(group, "selftest.check_medium_base_t", ethtool.MEDIUM_RJ45,
               lambda: value(
                   "FIBRE", "Connector: 0x22 (RJ45)\n"
                   "Transceiver type: Ethernet: 1000BASE-T\n"
                   "Length (SMF): 0m\nLength (50um): 0m\n"
                   "Length (Copper): 100m\n")),
        _check(group, "selftest.check_medium_dac_no_lengths",
               ethtool.MEDIUM_DAC,
               lambda: value("FIBRE", "Connector: 0x21 (Copper pigtail)\n"
                             "Device technology: Passive Copper Cable\n")),
        _check(group, "selftest.check_medium_length_counterfactual",
               (ethtool.MEDIUM_DAC, ethtool.MEDIUM_FIBER), counterfactual),
    ]


def _checks_bridge_vlan():
    """守真實的 port 首行／VLAN 續行格式及與範圍展開器的接合點。"""
    sample = ("port              vlan-id\n"
              "vmbr0             1 PVID Egress Untagged\n"
              "                  100\n"
              "10gbe0\n"
              "                  20 PVID Egress Untagged\n"
              "                  200-202\n"
              "eno1              300\n")

    # [CHANGE] 2026-08-03 待辦 #30 補正：上面那份 sample **驗不到「防線二」**。
    # ★ 該函式有兩道防線（見其 docstring）：防線一在 port 名獨佔一行時清空 rest，
    #   防線二要求 VLAN 欄位以數字開頭。兩道同時生效時，拿掉防線二輸出完全不變
    #   ——實測把防線二改成恆 False，**53 項自檢全數通過**，是 unittest 才抓到它。
    #   那一刻「六類自檢都有鑑別力」這個宣稱就有了一個反例。
    # ★ 要讓防線二單獨現形，需要一個「**續行**欄位不是數字」的輸入：續行走的是
    #   `rest = line.strip()`，防線一對它不生效，於是只剩防線二擋得住。
    noise = ("vmbr0             1 PVID Egress Untagged\n"
             "                  garbage\n"
             "                  100\n")

    def parsed():
        return bridge.parse_vlan_show(sample)

    # [CHANGE] 2026-08-03 待辦 #30：分開守內容、負面 port、規模與跨函式接合，避免只驗快照。
    group = "selftest.group_bridgevlan"
    return [
        _check(group, "selftest.check_bridgevlan_ports", {
            "vmbr0": {"vlans": "1u,100t", "pvid": "1"},
            "10gbe0": {"vlans": "20u,200-202t", "pvid": "20"},
            "eno1": {"vlans": "300t", "pvid": "-"},
        }, parsed),
        _check(group, "selftest.check_bridgevlan_header", False,
               lambda: "port" in parsed()),
        _check(group, "selftest.check_bridgevlan_continuation", False,
               lambda: "20" in parsed()),
        _check(group, "selftest.check_bridgevlan_count", 3,
               lambda: len(parsed())),
        _check(group, "selftest.check_bridgevlan_expand",
               [20, 200, 201, 202],
               lambda: bridge.expand_vlan_list(
                   bridge.strip_tags(parsed()["10gbe0"]["vlans"]))),
        _check(group, "selftest.check_bridgevlan_nonnumeric", "1u,100t",
               lambda: bridge.parse_vlan_show(noise)["vmbr0"]["vlans"]),
    ]


def _checks_ethtool_calls():
    """快取鍵必須同時包含網卡與 argv 選項。"""
    def calls_for(operations):
        calls = []

        def run(argv):
            calls.append(tuple(argv))
            return subprocess.CompletedProcess(argv, 0, "Port: Twisted Pair\n", "")

        reader = ethtool.EthtoolReader(run_fn=run)
        for method, nic in operations:
            getattr(reader, method)(nic)
        return calls

    # [CHANGE] 2026-08-03 待辦 #30：計數底層呼叫，而非只驗快取前後輸出仍正確。
    group = "selftest.group_ethtool_calls"
    return [
        _check(group, "selftest.check_ethtool_calls_same_nic", 1,
               lambda: len(calls_for((("link_info", "eno1"),
                                      ("link_info", "eno1"))))),
        _check(group, "selftest.check_ethtool_calls_distinct_argv", [
            ("ethtool", "eno1"), ("ethtool", "-i", "eno1")],
            lambda: calls_for((("link_info", "eno1"),
                               ("driver_info", "eno1")))),
        _check(group, "selftest.check_ethtool_calls_distinct_nics", [
            ("ethtool", "eno1"), ("ethtool", "eno2")],
            lambda: calls_for((("link_info", "eno1"),
                               ("link_info", "eno2")))),
    ]


def _checks_list_limit():
    """截斷時的說明行是契約的一部分，不能只驗留下的資料列。"""
    def truncated():
        # [CHANGE] 2026-08-03 待辦 #30：3／8／5 互異，避免把 limit 誤當成 hidden 仍通過。
        got = base.limited(["a", "b", "c", "d", "e", "f", "g", "h"],
                           3, "items")
        tail = got[-1]
        return got[:3], len(got), "8" in tail, "5" in tail

    # [CHANGE] 2026-08-03 待辦 #30：同驗資料列與總數／隱藏數，靜默 lines[:limit] 必須失敗。
    group = "selftest.group_list_limit"
    return [
        _check(group, "selftest.check_list_limit_unchanged", ["a", "b"],
               lambda: base.limited(["a", "b"], 3, "items")),
        _check(group, "selftest.check_list_limit_truncated",
               (["a", "b", "c"], 4, True, True), truncated),
        _check(group, "selftest.check_list_limit_empty", [],
               lambda: base.limited([], 2, "items")),
        _check(group, "selftest.check_list_limit_disabled",
               (["a", "b"], ["a", "b"], ["a", "b"]),
               lambda: tuple(base.limited(["a", "b"], limit, "items")
                             for limit in (None, 0, -1))),
    ]


# [CHANGE] 2026-08-03 待辦 #46：判斷 chmod 拿到的是不是 opener 剛回傳的那個 fd。
#          ★ MUST 在同一次執行的紀錄內比對：fd 號在關閉後會被作業系統回收，跨兩次
#            執行比對會恆真，看起來全綠而什麼都沒守到。
def _chmod_got_open_fd(recorded):
    """chmod 收到的第一個引數是否就是 opener 回傳的那個 fd。"""
    opened = [call for call in recorded if call[0] == "open"]
    chmodded = [call for call in recorded if call[0] == "chmod"]
    if not opened or not chmodded:
        return False
    return chmodded[0][3] == opened[0][3]


def _checks_report_perm():
    """記錄 write_report 下給 opener/chmod 的 mode、flags 與第一個引數。"""
    def calls():
        recorded = []
        # [CHANGE] 2026-08-03 待辦 #30：Windows 不具完整 POSIX mode bits，故驗指令引數。
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "report.txt")

            # [CHANGE] 2026-08-04 v03.009.000：MUST 收 dir_fd。真機（Linux）抓到的
            #   缺陷——待辦 #50 讓 write_report() 在支援 dir_fd 的平台改以
            #   `opener(basename, flags, mode, dir_fd=…)` 呼叫，而這個注入點只收
            #   三個位置參數 ⇒ **在目標平台上 TypeError**。
            #   ★ 開發機（Windows）不支援 dir_fd，那條分支從不執行，故本機全綠。
            def opener(target, flags, mode, dir_fd=None):
                handle = os.open(target, flags, mode, dir_fd=dir_fd)
                recorded.append(("open", mode, flags, handle))
                return handle

            # [CHANGE] 2026-08-03 待辦 #46：第一個引數原樣記下——它應該是 opener 回傳的
            #          fd；產品碼若退回傳路徑，這裡收到的會是字串，下面那條就判紅。
            def chmod_fn(target, mode):
                recorded.append(("chmod", mode, None, target))

            report.write_report(path, ["secret"], opener=opener,
                                chmod_fn=chmod_fn)
        return recorded

    group = "selftest.group_report_perm"
    return [
        _check(group, "selftest.check_report_perm_open_called", 1,
               lambda: len([call for call in calls() if call[0] == "open"])),
        _check(group, "selftest.check_report_perm_open_mode", 0o600,
               lambda: calls()[0][1]),
        _check(group, "selftest.check_report_perm_chmod_mode", 0o600,
               lambda: calls()[1][1]),
        # [CHANGE] 2026-08-03 待辦 #46：★ 只有在有 O_NOFOLLOW 的平台（＝真機 PVE）上這條
        #          才有鑑別力；Windows 上期望與實際同為 0，它誠實地不判紅也不宣稱驗過。
        #          平台無關的鑑別力由 tests/test_report.py 的注入式旗標測試負責。
        _check(group, "selftest.check_report_perm_open_nofollow",
               report.NOFOLLOW_FLAG,
               lambda: calls()[0][2] & report.NOFOLLOW_FLAG),
        _check(group, "selftest.check_report_perm_chmod_takes_fd", True,
               lambda: _chmod_got_open_fd(calls())),
    ]

def default_checks():
    """回傳十一組已知答案；actual callable 只會由 run_checks 執行。"""
    guest_sample = (
        "virtio=AA:BB:CC:DD:EE:FF, bridge=vmbr0, tag=100, firewall=1")
    vlan_values = "10,20,21,22,23,30"
    checks = [
        _check("selftest.group_width", "selftest.check_width_ascii", 4,
               lambda: width.disp_width("Link")),
        _check("selftest.group_width", "selftest.check_width_cjk", 6,
               lambda: width.disp_width("已接線")),
        _check("selftest.group_width", "selftest.check_width_mixed", 9,
               lambda: width.disp_width("RJ45 電口")),
        _check("selftest.group_width", "selftest.check_width_pad", 10,
               lambda: width.disp_width(width.pad("已接線", 10))),
        _check("selftest.group_width", "selftest.check_width_no_truncate",
               "SFP/QSFP 模組", lambda: width.pad("SFP/QSFP 模組", 10)),
        _check("selftest.group_width", "selftest.check_width_truncate", 5,
               lambda: width.disp_width(width.truncate("abcdef", 5))),

        _check("selftest.group_vlan", "selftest.check_vlan_expand",
               [10, 20, 21, 22, 23, 30],
               lambda: bridge.expand_vlan_list("10,20-23,30")),
        _check("selftest.group_vlan", "selftest.check_vlan_empty", [],
               lambda: bridge.expand_vlan_list("")),
        _check("selftest.group_vlan", "selftest.check_vlan_roundtrip",
               [10, 20, 21, 22, 23, 30],
               lambda: bridge.expand_vlan_list(
                   bridge.compress_vlan_list(vlan_values))),
        _check("selftest.group_vlan", "selftest.check_vlan_contains", True,
               lambda: bridge.vlan_in_list(22, "10,20-23,30")),
        _check("selftest.group_vlan", "selftest.check_vlan_excludes", False,
               lambda: bridge.vlan_in_list(24, "10,20-23,30")),

        _check("selftest.group_guest", "selftest.check_guest_fields",
               ("AA:BB:CC:DD:EE:FF", "vmbr0", "100"),
               lambda: tuple(pve.parse_net_value(guest_sample)[key]
                             for key in ("mac", "bridge", "tag"))),
        _check("selftest.group_guest", "selftest.check_guest_kv",
               [("bridge", "vmbr0"), ("tag", "100")],
               lambda: pve.parse_kv(" bridge=vmbr0, tag=100 ")),
        _check("selftest.group_guest", "selftest.check_guest_mac", True,
               lambda: pve.is_mac("AA:BB:CC:DD:EE:FF")),
        _check("selftest.group_guest", "selftest.check_guest_bad_mac", False,
               lambda: pve.is_mac("AA:BB:CC:DD:EE")),

        _check("selftest.group_netconf", "selftest.check_netconf_join",
               ["auto vmbr0 vmbr1"],
               lambda: netconf.join_continuations("auto vmbr0 \\\n  vmbr1")),
        _check("selftest.group_netconf", "selftest.check_netconf_stanza",
               "stanza", lambda: netconf.classify_line("auto vmbr0")),
        _check("selftest.group_netconf", "selftest.check_netconf_comment",
               "comment", lambda: netconf.classify_line("  # note")),
        _check("selftest.group_netconf", "selftest.check_netconf_blank",
               "blank", lambda: netconf.classify_line("")),
        _check("selftest.group_netconf", "selftest.check_netconf_auto",
               ["vmbr0", "vmbr1"],
               lambda: netconf.parse_auto("auto vmbr0 vmbr1")),

        # [CHANGE] 2026-08-02 這兩條的期望值原本寫死成 {"en": [], "zh-TW": []}
        #          與 ["en", "zh-TW"]。語言集合是從 MESSAGES 推導出來的衍生值，
        #          一旦新增第三語系，這兩條就會 FAIL——**而那是誤報**：訊息表其實
        #          完全正常。自檢誤報比不檢查更糟，它會讓人以為判定邏輯退化了，
        #          進而不敢採信整份盤查結果（見 selftest.has_failure 的措辭）。
        #          改成驗「性質」而不是「當下的形態」：缺 key 的語言一個都不能有、
        #          語言數至少兩種——後者與 tests/test_i18n.py 的 test_規模與範圍
        #          是同一道判準，那裡用的也是 assertGreaterEqual(len(langs), 2)。
        _check("selftest.group_i18n", "selftest.check_i18n_diff", [],
               lambda: sorted(lang for lang, keys in i18n.key_diff().items()
                              if keys)),
        _check("selftest.group_i18n", "selftest.check_i18n_empty", [],
               i18n.empty_values),
        _check("selftest.group_i18n", "selftest.check_i18n_languages", True,
               lambda: len(i18n.available_langs()) >= 2),
    ]
    # [CHANGE] 2026-08-03 待辦 #30：六類各自成函式，否則本函式會膨脹到無法閱讀。
    for extra in (_checks_sysfs, _checks_medium, _checks_bridge_vlan,
                  _checks_ethtool_calls, _checks_list_limit,
                  _checks_report_perm):
        checks.extend(extra())
    return checks


def run_checks(checks=None):
    """執行檢查並分開計算 PASS、FAIL、SKIP。"""
    selected = default_checks() if checks is None else list(checks)
    results = []
    summary = {"pass": 0, "fail": 0, "skip": 0}
    for check in selected:
        expected = check.get("expected")
        actual_source = check.get("actual")
        if check.get("skip") or check.get("status") == SKIP:
            actual = None if callable(actual_source) else actual_source
            status = SKIP
        else:
            actual = actual_source() if callable(actual_source) else actual_source
            status = PASS if actual == expected else FAIL
        summary[status.lower()] += 1
        results.append({
            "group": check.get("group"),
            "name": check.get("name"),
            "expected": expected,
            "actual": actual,
            "status": status,
            "reason": check.get("reason"),
        })
    return results, summary


def _display(value):
    return repr(value)


def _paint(palette, text, colour):
    return palette.paint(text, colour) if palette is not None else text


def format_results(results, summary, palette=None):
    """把檢查結果排成行；不做任何 I/O，且明列每組射程與三態摘要。"""
    lines = [t("selftest.title", version=__version__), ""]
    groups = []
    for result in results:
        if result["group"] not in groups:
            groups.append(result["group"])
    for group in groups:
        items = [item for item in results if item["group"] == group]
        lines.append(t(group))
        lines.append(t("selftest.scope", count=len(items)))
        for item in items:
            name = t(item["name"])
            if item["status"] == PASS:
                line = t("selftest.result_pass", name=name,
                         actual=_display(item["actual"]))
                lines.append(_paint(palette, line, "green"))
            elif item["status"] == FAIL:
                detail = t("selftest.detail_fail",
                           expected=_display(item["expected"]),
                           actual=_display(item["actual"]))
                line = t("selftest.result_fail", name=name, detail=detail)
                lines.append(_paint(palette, line, "red"))
            else:
                reason = item.get("reason")
                suffix = (t("selftest.skip_reason", reason=reason)
                          if reason is not None else "")
                line = t("selftest.result_skip", name=name, reason=suffix)
                lines.append(_paint(palette, line, "yellow"))
        lines.append("")
    lines.append(t("selftest.summary", passed=summary["pass"],
                   failed=summary["fail"], skipped=summary["skip"]))
    conclusion = (t("selftest.has_failure") if summary["fail"]
                  else t("selftest.all_passed"))
    lines.append(_paint(palette, conclusion,
                        "red" if summary["fail"] else "green"))
    return lines


def exit_code(summary):
    """有任何 FAIL 時回 1；SKIP 不改變離開碼。"""
    return 1 if summary["fail"] > 0 else 0
