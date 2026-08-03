# [CHANGE] 2026-08-02 報告在建立瞬間即鎖為 0600，避免敏感內容短暫暴露於共用目錄。
"""固定寬度、無色的完整盤查報告。"""

import datetime
import os
import platform
import socket
import sys

from . import __version__
from . import app
from .collect import STATUS_OK, default_run, run_command
from .i18n import t
from .render import Palette, REPORT_WIDTH, RenderContext
from .render.base import error, success

# [CHANGE] 2026-08-03 待辦 #46：報告檔名可預測（host＋秒級時間戳），而 REPORT_DIR 是文件
#          明列的可調項；只要它落在他人可寫的目錄，預先種下的 symlink 就會讓「寫報告」
#          變成任意檔覆寫（O_TRUNC 會截斷 symlink 指到的目標）。O_NOFOLLOW 讓 open 直接
#          以 ELOOP 失敗。★ 這個旗標在 Windows 不存在（實測 3.13：hasattr 為 False；目標
#          平台 PVE 為 Linux 一定有），故以 getattr 取值——代價是在 Windows 上它等於 0，
#          「flags 有帶上它」的斷言會失去鑑別力，因此 write_report() 另外開放
#          nofollow_flag 參數，讓判準在沒有這個旗標的平台上也驗得到旗標確實被帶進 open。
NOFOLLOW_FLAG = getattr(os, "O_NOFOLLOW", 0)


def report_path(directory, host, timestamp_text):
    if hasattr(timestamp_text, "strftime"):
        stamp = timestamp_text.strftime("%Y%m%d-%H%M%S")
    else:
        stamp = str(timestamp_text)
    return os.path.join(directory,
                        "pve-network-audit-%s-%s.txt" % (host, stamp))


def report_lines(readers, ctx, host, timestamp, version, kernel, pve_version,
                 progress_fn=None):
    """組成整份報告；安全環境不信任呼叫端傳來的終端 context。"""
    safe_ctx = RenderContext(REPORT_WIDTH, Palette(enabled=False))
    timestamp_text = (timestamp.strftime("%Y-%m-%d %H:%M:%S")
                      if hasattr(timestamp, "strftime") else str(timestamp))
    # [CHANGE] 2026-08-02 分隔符改走 i18n（見 i18n.py 的 app.kv_sep）。
    sep = t("app.kv_sep")
    lines = [
        t("report.title"),
        "%s%s%s" % (t("app.host"), sep, host),
        "%s%s%s" % (t("report.kernel"), sep, kernel),
        "%s%s%s" % (t("report.pve_version"), sep, pve_version),
        "%s%s%s" % (t("report.generated_at"), sep, timestamp_text),
        "%s%s%s" % (t("report.tool_version"), sep, version),
    ]
    for entry in app.report_entries():
        title = t(entry.title_key)
        if progress_fn is not None:
            progress_fn(t("report.generating", title=title))
        lines.extend(("", "#" * 80, "# %s" % title, "#" * 80, ""))
        lines.extend(entry.factory(readers).render(safe_ctx))
    return lines


def write_report(path, lines, opener=None, chmod_fn=None,
                 makedirs_fn=None, nofollow_flag=None):
    """以原子式權限判準建立並寫入 UTF-8/LF 報告。"""
    opener = os.open if opener is None else opener
    # [CHANGE] 2026-08-03 待辦 #46：補強權限改吃 fd 而非路徑。走路徑的 chmod 是在 open
    #          之後才重新解析一次名稱，那個空隙足以讓路徑被抽換，結果是把 0600 打到別人
    #          的檔案上。fd 指向的是已經開啟的那個 inode，沒有第二次解析。
    #          ★ os.fchmod 實測在本機 Windows 3.13 亦可呼叫，故不寫平台 fallback——
    #            那會是一個在開發機與目標機都走不到的分支。
    chmod_fn = os.fchmod if chmod_fn is None else chmod_fn
    makedirs_fn = os.makedirs if makedirs_fn is None else makedirs_fn
    nofollow = NOFOLLOW_FLAG if nofollow_flag is None else nofollow_flag
    directory = os.path.dirname(path) or "."
    makedirs_fn(directory, exist_ok=True)
    fd = opener(path,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC | nofollow, 0o600)
    try:
        chmod_fn(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            fd = None
            for line in lines:
                stream.write(str(line))
                stream.write("\n")
    finally:
        if fd is not None:
            os.close(fd)
    return path


def _pve_version(run_fn):
    result = run_command(run_fn, ["pveversion"])
    if result["status"] != STATUS_OK:
        return t("app.na")
    output = result["stdout"].splitlines()
    return output[0] if output else t("app.na")


def generate(readers, env=None, quiet=False, host_fn=None, now_fn=None,
             kernel_fn=None, run_fn=None, stdout_fn=None, stderr_fn=None,
             opener=None, chmod_fn=None, makedirs_fn=None, version=None):
    """取得可注入的系統資訊、寫檔並回傳 (path, exit_code)。"""
    env = os.environ if env is None else env
    host_fn = socket.gethostname if host_fn is None else host_fn
    now_fn = datetime.datetime.now if now_fn is None else now_fn
    kernel_fn = platform.release if kernel_fn is None else kernel_fn
    run_fn = default_run if run_fn is None else run_fn
    stdout_fn = sys.stdout.write if stdout_fn is None else stdout_fn
    stderr_fn = sys.stderr.write if stderr_fn is None else stderr_fn
    version = __version__ if version is None else version
    host = host_fn()
    now = now_fn()
    directory = env.get("REPORT_DIR") or "/root"
    path = report_path(directory, host, now.strftime("%Y%m%d-%H%M%S"))
    # [CHANGE] 2026-08-03 此 context 只供終端訊息著色；report_lines() 會自行建立
    #          Palette(enabled=False)，不可把互動 palette 寫進報告正文。
    ctx = app.build_context(env=env)
    # [CHANGE] 2026-08-02 先確認目錄可建立，避免明知無法輸出仍執行耗時且可能敏感的系統取值。
    make = os.makedirs if makedirs_fn is None else makedirs_fn
    try:
        make(directory, exist_ok=True)
    except OSError:
        stderr_fn(error(t("report.mkdir_failed", path=directory),
                        ctx.palette) + "\n")
        return path, 1
    progress = None

    if not quiet:
        progress = lambda text: stdout_fn("  %s\n" % text)
    lines = report_lines(readers, ctx, host, now, version, kernel_fn(),
                         _pve_version(run_fn), progress_fn=progress)
    try:
        write_report(path, lines, opener=opener, chmod_fn=chmod_fn,
                     makedirs_fn=lambda _path, exist_ok=True: None)
    except (OSError, IOError):
        stderr_fn(error(t("report.create_failed", path=path),
                        ctx.palette) + "\n")
        return path, 1
    stdout_fn("\n%s\n" % success(t("report.done", path=path), ctx.palette))
    return path, 0
