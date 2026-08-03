# [CHANGE] 2026-08-02 將畫面組裝與 I/O 分開，讓互動分派可在無真終端與硬體下驗證。
"""互動選單與單項檢視流程。"""

import datetime
import shutil
import socket
import sys

from . import __version__
from . import app, pager, report, selftest
from .collect import STATUS_UNAVAILABLE
from .collect import led
from .i18n import (available_langs, current_lang, lang_display_name, next_lang,
                   set_lang, t)
from .render.base import error, header, note, section, success
from .render.nic import link_state

# [CHANGE] 2026-08-02 待辦 #27：啟動時的語系選擇。
# ★ 這一行**刻意不進 i18n 訊息表**：這個畫面出現在使用者選定語言**之前**，
#   用任何單一語言寫，另一邊的使用者就看不懂——這是雞生蛋的問題，唯一的解
#   是不依賴當前語言。選項本身用各語系的 native_name（用自己的文字寫自己），
#   所以新增第三語系時這一行完全不必動。
LANG_PROMPT = "請選擇語言 / Select language"

# [CHANGE] 2026-08-02 待辦 #25：語系切換刻意用**非數字鍵**。
# ★ 1–20 是 bash 版的原編號、21–24 是 Python 版新增的盤查能力，那個數字空間的
#   語意是「第幾項盤查」。把「切換語言」放進去（例如給它 25）會讓它讀起來像
#   第 25 項盤查項目，而它其實是工具本身的設定。
# ★ 附帶的好處是射程完全不動：MENU_ENTRIES／INTERACTIVE_NUMBERS／
#   ACTION_NUMBERS／report_entries() 全都不必改，守著射程的突變條目 BA–BD
#   也就不會被這一批動到。
LANG_KEY = "L"


def input_range():
    """選單可接受的輸入；數字範圍**從目錄推導**，不寫死。

    ★ 原本這裡是寫死的 "0-24"。目錄增減時那串字會靜默說謊，而提示文字說謊
      比不印更糟——它正是使用者用來判斷「這個工具涵蓋到哪裡」的依據。
    """
    numbers = sorted(entry.number for entry in app.MENU_ENTRIES)
    return "%d-%d/%s" % (numbers[0], numbers[-1], LANG_KEY)


# [CHANGE] 2026-08-02 base.header 的既有中文標籤無法隨語系切換，故只沿用版面契約並由 i18n 組標籤。
# [CHANGE] 2026-08-02 原本在此自組一份抬頭，因為 render/base.py 的 header() 把
#          「主機名稱」「執行時間」硬編碼成中文，不符本批的 i18n 硬約束。缺陷已
#          就地修好（base.header 改用 app.host／app.time），故改為呼叫它——
#          ★ 兩份抬頭是本專案 render/base.py docstring 明文反對的形態：一邊多加
#          一個欄位而另一邊忘了，不會有任何東西變紅。
def _header_lines(ctx, host, timestamp, version):
    return header(t("app.title"), host, timestamp, version=version,
                  palette=ctx.palette)

# [CHANGE] 2026-08-02 待辦 #27：使用者裁決「每次進互動模式都先問語系」。
def choose_language(input_fn=None, write_fn=None, clear_fn=None):
    """啟動時的語系選擇畫面；回傳實際採用的語言。

    ★ **只有互動模式會呼叫它**。`--report` 是設計來排 cron 的，任何停下來等
      人輸入的東西都會讓它在半夜永遠掛住，而且不會有任何錯誤訊息。這是
      本函式放在 cli 的互動分支、而不是放進 set_lang 的唯一理由。
    ★ 無效輸入**重問**而不是沿用預設：這是啟動的第一步，靜默帶過會讓使用者
      以為自己選到了，然後對著非預期的語言操作整輪。
    ★ EOF 才退出並沿用現行語言——管線或 here-doc 餵進來時不能無限迴圈。
    """
    input_fn = input if input_fn is None else input_fn
    write_fn = sys.stdout.write if write_fn is None else write_fn
    clear_fn = (lambda: write_fn("\033c")) if clear_fn is None else clear_fn
    langs = available_langs()
    while True:
        clear_fn()
        lines = [LANG_PROMPT, ""]
        lines.extend("  %d) %s" % (index, lang_display_name(lang))
                     for index, lang in enumerate(langs, 1))
        lines.append("")
        _emit(lines, write_fn)
        try:
            raw = input_fn("  [1-%d]: " % len(langs))
        except EOFError:
            return current_lang()
        try:
            index = int(raw)
        except (TypeError, ValueError):
            index = 0
        if 1 <= index <= len(langs):
            return set_lang(langs[index - 1])


def render_menu(ctx, entries=None):
    """回傳選單內容，不做 I/O。"""
    selected = app.MENU_ENTRIES if entries is None else tuple(entries)
    lines = [t("menu.prompt"), ""]
    for group in ("phys", "l2", "l3", "overall", "added"):
        items = [entry for entry in selected
                 if entry.group == group and entry.number != 0]
        if not items:
            continue
        lines.append(ctx.paint(t("menu.group_" + group), "bold"))
        for entry in items:
            lines.append("  %2d) %s" % (entry.number, t(entry.title_key)))
        lines.append("")
    # [CHANGE] 2026-08-02 待辦 #25：顯示「切過去會變成哪一個語言」而不是
    # 「目前是哪一個」——使用者要判斷的是按下去會得到什麼，而不是現況；
    # 現況他正在看。target 走 next_lang() 故三語系以上也會逐一輪替。
    lines.append("   %s) %s" % (
        LANG_KEY, t("menu.switch_lang", target=lang_display_name(next_lang()))))
    exit_entry = next((entry for entry in selected if entry.number == 0), None)
    if exit_entry is not None:
        lines.extend(("   0) %s" % t(exit_entry.title_key), ""))
    return lines


def view_lines(entry, readers, ctx, host, timestamp, version,
               include_hint=True):
    """回傳單一項目的抬頭、區段內容與選用的捲動提示。"""
    lines = _header_lines(ctx, host, timestamp, version)
    lines.extend(section(t(entry.title_key), ctx.palette))
    lines.extend(entry.factory(readers).render(ctx))
    if include_hint:
        lines.extend(("", "-" * 60, t("pager.scroll_hint")))
    return lines


def _emit(lines, write_fn):
    for line in lines:
        write_fn(str(line) + "\n")


def _pause(input_fn):
    try:
        input_fn(t("app.press_enter"))
    except EOFError:
        return


def _now_text(now_fn):
    value = now_fn()
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _view(entry, readers, ctx, input_fn, write_fn, page_fn,
          pager_available_fn, env, host_fn, now_fn, version):
    # [CHANGE] 2026-08-03 RX/TX 取樣提示只屬於互動流程；報告仍會取樣，但正文不寫
    #          「畫面會停住」這種終端操作提示。
    if entry.number == 1:
        _emit((note(t("nic.sampling", sec=readers.sample_seconds),
                    ctx.palette),), write_fn)
    if pager_available_fn(env=env):
        lines = view_lines(entry, readers, ctx, host_fn(), _now_text(now_fn),
                           version, include_hint=True)
        page_fn(lines, env=env)
    else:
        lines = view_lines(entry, readers, ctx, host_fn(), _now_text(now_fn),
                           version, include_hint=False)
        _emit(lines, write_fn)
        _pause(input_fn)


def _led_flow(readers, ctx, input_fn, write_fn, which_fn, run_fn, env):
    if which_fn("ethtool") is None:
        _emit((error(t("led.need_ethtool"), ctx.palette),
               t("led.install_hint")), write_fn)
        _pause(input_fn)
        return
    nics = readers.sysfs.physical_nics()
    if not nics:
        _emit((error(t("led.no_nic"), ctx.palette),), write_fn)
        _pause(input_fn)
        return
    lines = [t("led.title")]
    for index, nic in enumerate(nics, 1):
        mac = readers.sysfs.mac(nic) or t("app.na")
        link_text, link_colour = link_state(readers.sysfs.carrier(nic))
        lines.append("  %d) %-12s  %-17s  %s" % (
            index, nic, mac, ctx.paint(link_text, link_colour)))
    lines.extend(("   0) %s" % t("app.back"), ""))
    _emit(lines, write_fn)
    try:
        choice = input_fn(t("menu.pick_nic"))
    except EOFError:
        return
    if choice == "0":
        return
    try:
        index = int(choice)
    except (TypeError, ValueError):
        index = 0
    if index < 1 or index > len(nics):
        _emit((error(t("app.invalid_choice"), ctx.palette),), write_fn)
        _pause(input_fn)
        return
    nic = nics[index - 1]
    seconds = led.blink_seconds(env=env)
    _emit((t("led.blinking", nic=ctx.paint(nic, "cyan"),
             seconds=seconds),), write_fn)
    result = led.blink(run_fn, nic, seconds=seconds)
    if result.get("status") != STATUS_UNAVAILABLE:
        _emit((success(t("led.done"), ctx.palette),), write_fn)
    else:
        _emit((note(t("led.unsupported"), ctx.palette),
               t("led.monitor_hint")), write_fn)
    _pause(input_fn)


def run_menu(readers, ctx, input_fn=None, write_fn=None, clear_fn=None,
             page_fn=None, env=None, pager_available_fn=None,
             which_fn=None, led_run_fn=None, report_fn=None,
             host_fn=None, now_fn=None, version=None):
    """執行互動迴圈；所有有副作用的邊界皆可注入。"""
    input_fn = input if input_fn is None else input_fn
    write_fn = sys.stdout.write if write_fn is None else write_fn
    clear_fn = (lambda: write_fn("\033c")) if clear_fn is None else clear_fn
    page_fn = pager.page_output if page_fn is None else page_fn
    pager_available_fn = (pager.pager_available if pager_available_fn is None
                          else pager_available_fn)
    which_fn = shutil.which if which_fn is None else which_fn
    report_fn = report.generate if report_fn is None else report_fn
    host_fn = socket.gethostname if host_fn is None else host_fn
    now_fn = datetime.datetime.now if now_fn is None else now_fn
    version = __version__ if version is None else version
    env = {} if env is None else env

    while True:
        clear_fn()
        readers.reset_caches()
        _emit(_header_lines(ctx, host_fn(), _now_text(now_fn), version),
              write_fn)
        _emit(render_menu(ctx), write_fn)
        try:
            raw = input_fn(t("menu.input", range=input_range()))
        except EOFError:
            _emit((t("app.exit"),), write_fn)
            return 0
        # [CHANGE] 2026-08-02 待辦 #25：切換語系後 continue，讓迴圈頂端重畫整個
        # 畫面。★ MUST 在 int() 之前判斷：'L' 走到 int() 會變成無效選項而被
        # 當成打錯字。大小寫都收，現場打字不該因為 Caps Lock 而失敗。
        if isinstance(raw, str) and raw.strip().upper() == LANG_KEY:
            set_lang(next_lang())
            continue
        try:
            number = int(raw)
        except (TypeError, ValueError):
            number = -1
        entry = app.entry_by_number(number)
        if entry is None:
            _emit((error(t("app.invalid_choice"), ctx.palette),), write_fn)
            _pause(input_fn)
            continue
        if number == 0:
            _emit((t("app.exit"),), write_fn)
            return 0
        if entry.factory is None:
            _emit((t("menu.not_implemented", todo=entry.todo),), write_fn)
            _pause(input_fn)
            continue
        if number == 4:
            _led_flow(readers, ctx, input_fn, write_fn, which_fn, led_run_fn, env)
        elif number == 18:
            for report_entry in app.report_entries():
                _view(report_entry, readers, ctx, input_fn, write_fn, page_fn,
                      pager_available_fn, env, host_fn, now_fn, version)
        elif number == 19:
            report_fn(readers, env=env, quiet=False)
            _pause(input_fn)
        elif number == 20:
            results, summary = selftest.run_checks()
            _emit(selftest.format_results(results, summary, ctx.palette), write_fn)
            _pause(input_fn)
        else:
            _view(entry, readers, ctx, input_fn, write_fn, page_fn,
                  pager_available_fn, env, host_fn, now_fn, version)
