# [CHANGE] 2026-08-02 將 CLI 分派保留為可注入純入口，讓權限、stdout/stderr 與動作逐列驗證。
"""命令列分派。"""

import os
import sys

from . import __version__, app, menu, report, selftest
from .i18n import set_lang, t
from .render.base import error


def usage_lines(prog):
    return ["%s  v%s" % (t("app.title"), __version__), "",
            t("cli.usage_synopsis", prog=prog), "", t("cli.usage_env"), "",
            t("cli.usage_note"), "", t("cli.usage_deps")]


def _write_lines(lines, write_fn):
    for line in lines:
        write_fn(str(line) + "\n")


def require_root(euid_fn=None, stderr_fn=None, palette=None):
    """無法取得 EUID 時採 fail closed；未知權限不等於 root。"""
    stderr_fn = sys.stderr.write if stderr_fn is None else stderr_fn
    checker = getattr(os, "geteuid", None) if euid_fn is None else euid_fn
    try:
        is_root = checker is not None and checker() == 0
    except (AttributeError, OSError):
        is_root = False
    if not is_root:
        stderr_fn(error(t("app.need_root"), palette) + "\n")
    return is_root


def main(argv, env=None, prog="pve-network-audit", stdout_fn=None,
         stderr_fn=None, euid_fn=None, readers_factory=None,
         menu_fn=None, report_fn=None, checks_fn=None, format_fn=None,
         selftest_exit_fn=None, choose_lang_fn=None):
    """依 argv 分派並回傳離開碼，不自行 sys.exit。"""
    env = os.environ if env is None else env
    stdout_fn = sys.stdout.write if stdout_fn is None else stdout_fn
    stderr_fn = sys.stderr.write if stderr_fn is None else stderr_fn
    readers_factory = app.Readers if readers_factory is None else readers_factory
    menu_fn = menu.run_menu if menu_fn is None else menu_fn
    report_fn = report.generate if report_fn is None else report_fn
    checks_fn = selftest.run_checks if checks_fn is None else checks_fn
    format_fn = selftest.format_results if format_fn is None else format_fn
    selftest_exit_fn = (selftest.exit_code if selftest_exit_fn is None
                        else selftest_exit_fn)
    # [CHANGE] 2026-08-02 待辦 #27：語系選擇畫面。
    choose_lang_fn = (menu.choose_language if choose_lang_fn is None
                      else choose_lang_fn)
    set_lang(env=env)
    # [CHANGE] 2026-08-03：Ctrl-C **不是程式錯誤**，不該噴 traceback。
    #
    # ★ 真機實測踩到：在 pager 的 `(END)` 提示按 Ctrl-C，畫面留下九層 traceback，
    #   最底下是 `os.waitpid` ——讀的人只會覺得工具壞了。而這支工具從頭到尾都是
    #   互動式的（選單等輸入、pager 等翻頁、LED 定位阻塞十秒），**Ctrl-C 是預期
    #   中的操作，不是例外路徑**。
    # ★ 實測全套件對 `KeyboardInterrupt` 的命中數是 **0**（陽性對照：
    #   `BrokenPipeError` 有 3 處），三層——入口腳本／本函式／pager——都沒有攔。
    # ★ 攔在這裡而不是入口腳本：入口腳本無副檔名，`import` 不進來，寫在那裡的
    #   判斷沒有任何測試涵蓋得到（見該檔檔頭）。
    # ★ 離開碼 130 是 shell 慣例（128 + SIGINT 的 2）。回 0 會讓排程把「使用者中斷」
    #   當成正常完成，回 1 則與「真的失敗」混在一起。
    try:
        option = argv[0] if argv else None
        if option in ("--help", "-h"):
            _write_lines(usage_lines(prog), stdout_fn)
            return 0
        if option in ("--version", "-V"):
            stdout_fn(__version__ + "\n")
            return 0
        if option == "--self-test":
            results, summary = checks_fn()
            _write_lines(format_fn(results, summary), stdout_fn)
            return selftest_exit_fn(summary)
        if option == "--report":
            palette = app.build_context(env=env).palette
            if not require_root(euid_fn=euid_fn, stderr_fn=stderr_fn,
                                palette=palette):
                return 1
            readers = readers_factory(env=env)
            _path, code = report_fn(readers, env=env, quiet=True)
            return code
        if option is None:
            ctx = app.build_context(env=env)
            if not require_root(euid_fn=euid_fn, stderr_fn=stderr_fn,
                                palette=ctx.palette):
                return 1
            # ★ MUST 只在這個分支問語系。--report／--self-test 都不能停下來等人：
            #   前者是設計來排 cron 的，半夜掛住不會有任何錯誤訊息。
            choose_lang_fn()
            readers = readers_factory(env=env)
            return menu_fn(readers, ctx, env=env)
        stderr_fn(t("cli.unknown_option", option=option) + "\n\n")
        _write_lines(usage_lines(prog), stderr_fn)
        return 2
    except KeyboardInterrupt:
        # 前導換行：Ctrl-C 的 `^C` 會留在游標所在那一行。
        stderr_fn("\n" + t("cli.interrupted") + "\n")
        return 130
