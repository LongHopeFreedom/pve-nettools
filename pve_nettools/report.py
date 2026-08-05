# [CHANGE] 2026-08-02 報告在建立瞬間即鎖為 0600，避免敏感內容短暫暴露於共用目錄。
"""固定寬度、無色的完整盤查報告。"""

import contextlib
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

# [CHANGE] 2026-08-04 待辦 #50：O_NOFOLLOW 只擋路徑的**最後一段**。父目錄若本身是
#          symlink，open 仍會乖乖跟過去，於是報告寫進別人選的目錄——內容外洩，而
#          「寫報告」這件事看起來完全成功。要連父目錄一起擋，就得把目錄逐段開起來，
#          每一段都帶 O_DIRECTORY|O_NOFOLLOW，最後以 dir_fd 開檔。
#          ★ dir_fd 在 Windows 不支援（os.supports_dir_fd 不含 os.open），故兩條分支
#            **都是真的走得到的**：目標平台 PVE 走逐段開啟，開發機走整條路徑開啟。
#            這與待辦 #38 那種「兩邊都走不到的分支」不同，不是同一個形態。
DIRECTORY_FLAG = getattr(os, "O_DIRECTORY", 0)

# [CHANGE] 2026-08-04 待辦 #51：報告檔名＝主機名＋**秒級**時間戳，同一秒重跑會撞名，
#          而原本的 O_CREAT|O_TRUNC 會直接截斷既有檔。加 O_EXCL 之後撞名一律失敗，
#          再由呼叫端改試 -2、-3……直到成功。使用者可見行為因此不變（重跑仍會產出
#          報告），但「開到別人預先建好的那個檔」這條路被堵死。
#          ★ 上限存在的理由：沒有上限的重試在目錄被塞滿同名檔時會變成無窮迴圈。
MAX_NAME_ATTEMPTS = 100


def report_path(directory, host, timestamp_text):
    if hasattr(timestamp_text, "strftime"):
        stamp = timestamp_text.strftime("%Y%m%d-%H%M%S")
    else:
        stamp = str(timestamp_text)
    return os.path.join(directory,
                        "pve-network-audit-%s-%s.txt" % (host, stamp))


def suffixed_path(path, attempt):
    """第 attempt 次嘗試要用的檔名；attempt 為 1 時就是原本那個名字。

    序號插在副檔名**之前**（`…-235659-2.txt`），不是接在最後面。接在 `.txt`
    後面會讓檔案不再是 `.txt`，而報告目錄裡的其他工具是按副檔名找檔的。
    """
    if attempt <= 1:
        return path
    root, ext = os.path.splitext(path)
    return "%s-%d%s" % (root, attempt, ext)


def dir_segments(directory):
    """把目錄拆成 (根, [逐段名稱])，供逐段開啟使用。

    以絕對路徑為準：相對路徑的每一段同樣要檢查，而 os.path.abspath 只做字串正規化，
    不會解析 symlink——**這正是我們要的**，解析掉就沒東西可擋了。
    """
    absolute = os.path.abspath(directory)
    drive, rest = os.path.splitdrive(absolute)
    return drive + os.sep, [part for part in rest.split(os.sep) if part]


@contextlib.contextmanager
def open_dir_chain(directory, nofollow):
    """逐段開啟目錄並 yield 最後一段的 fd；除了根以外每一段都不跟隨 symlink。

    根本身不帶 O_NOFOLLOW：`/` 不可能是 symlink，而在它上面加這個旗標，
    某些平台會直接以 ELOOP 拒絕——那會擋掉全部的正常路徑。
    """
    fd = os.open(directory_root(directory), os.O_RDONLY | DIRECTORY_FLAG)
    try:
        for segment in dir_segments(directory)[1]:
            nxt = os.open(segment, os.O_RDONLY | DIRECTORY_FLAG | nofollow,
                          dir_fd=fd)
            os.close(fd)
            fd = nxt
        yield fd
    finally:
        os.close(fd)


# [CHANGE] 2026-08-05 待辦 #60：逐段建立目錄，補掉 generate() 的 os.makedirs
# 會跟隨 symlink 的殘留（原由第 4 輪資安檢測具名登記）。
#
# ★★ 這是一條**只在目標平台執行**的分支（Windows 的 os.mkdir 不收 dir_fd），
#    而上一棒最貴的缺陷正是這個形態：#50 讓 write_report 在支援 dir_fd 的平台
#    改以關鍵字呼叫 opener，卻沒問「既有的五個注入點在這條新分支下活不活得了」
#    ——開發機全綠、真機七個 TypeError，其中三個在產品碼裡。
#    ⇒ 本次刻意**不動 makedirs_fn 的簽名**：呼叫形態仍是
#      `makedirs_fn(path, exist_ok=True)`，既有注入點一個字都不必改。
#      逐段分支只在 makedirs_fn is None 時才會被選到（見 prepared_dir()）。
# ★ mkdir_fn / open_fn 可注入，讓「每一段都帶 dir_fd、都帶 nofollow」這件事
#   在**開發機上也驗得到**——否則這段邏輯只能靠真機，而真機不會逐行看。
# ★ mode 沿用 os.mkdir 的預設（由 umask 決定），與原本的 os.makedirs 一致。
#   這一棒只修 symlink 跟隨，不順手改權限——那會是另一個行為改變。
# [CHANGE] 2026-08-05 待辦 #67：由「建完就關」改成 context manager，把最後一段的
#   fd **交出去**而不是關掉。原本的形態是 mkdir_chain() 關 fd → write_report() 再以
#   open_dir_chain() 從根重新解析一次，中間那段空隙就是第 2 輪 code review 登記的
#   TOCTOU。現在整條路徑只解析一次，之後全部相對於同一個 fd。
#   ★ 這不是「多一層保險」而是**少一次解析**：第二次解析本身就是那個空隙。
@contextlib.contextmanager
def mkdir_chain(directory, nofollow, mkdir_fn=None, open_fn=None,
                close_fn=None):
    """逐段建立目錄並 yield 最後一段的 fd；除了根以外每一段都不跟隨 symlink。

    某一段已存在時不當作錯誤（等同 makedirs 的 exist_ok=True）；但它若是
    symlink，隨後帶 O_NOFOLLOW 的開啟會以 ELOOP 失敗——**那正是要擋的**。
    某一段是普通檔案時，帶 O_DIRECTORY 的開啟會以 ENOTDIR 失敗。

    ★ 呼叫端 MUST 在 with 區塊內用完這個 fd：離開區塊就關掉了。持有期間橫跨
      report_lines() 那段耗時取值是**刻意**的——fd 一放掉，就得再解析一次路徑，
      而那次解析正是 #67 要消掉的東西。fd 本身沒有逾時，持有久不影響正確性。
    """
    mkdir_fn = os.mkdir if mkdir_fn is None else mkdir_fn
    open_fn = os.open if open_fn is None else open_fn
    close_fn = os.close if close_fn is None else close_fn
    root, segments = dir_segments(directory)
    fd = open_fn(root, os.O_RDONLY | DIRECTORY_FLAG)
    try:
        for segment in segments:
            try:
                mkdir_fn(segment, dir_fd=fd)
            except FileExistsError:
                pass
            nxt = open_fn(segment, os.O_RDONLY | DIRECTORY_FLAG | nofollow,
                          dir_fd=fd)
            close_fn(fd)
            fd = nxt
        yield fd
    finally:
        close_fn(fd)


def dir_fd_mkdir_supported():
    """這台機器能不能做逐段 mkdir。Windows 不支援 dir_fd，一律回 False。"""
    return os.mkdir in os.supports_dir_fd and bool(NOFOLLOW_FLAG)


# [CHANGE] 2026-08-05 待辦 #67：取代原本的 choose_makedirs()。差別不在包裝方式，
#   在於**回傳型態**：原本回傳一個「建完就結束」的函式，於是父目錄的 fd 沒有辦法
#   活到寫檔那一刻；現在改成 context manager，把 fd 一路交到 write_report()。
#   ★ 三個分支 yield 出來的東西形態一致（fd 或 None），這件事在開發機驗得到——
#     沿用 choose_makedirs 立下的理由，見 test_mkdir_chain.py 的模組說明。
@contextlib.contextmanager
def prepared_dir(directory, makedirs_fn=None, supported=None, chain=None):
    """建好報告目錄，並在支援的平台上**持有**父目錄 fd 直到寫檔完成。

    yield 出來的是父目錄 fd，或 `None`——`None` 代表這台機器沒有 dir_fd、
    或呼叫端注入了自己的建目錄函式，此時 write_report() 退回逐段重開的路徑。

    ★★ 注入分支的呼叫形態仍是 `makedirs_fn(directory, exist_ok=True)`，一個字
       都沒變——上一棒 #50 的教訓是「新增只在目標平台執行的分支時，MUST 回頭
       檢查既有呼叫端」，既有注入點（含測試裡那五個）因此不必改。
    ★ supported / chain 可注入，讓 Linux 專屬那一支在開發機上也驗得到。
    """
    if makedirs_fn is not None:
        makedirs_fn(directory, exist_ok=True)
        yield None
    elif dir_fd_mkdir_supported() if supported is None else supported:
        chain = mkdir_chain if chain is None else chain
        with chain(directory, NOFOLLOW_FLAG) as parent_fd:
            yield parent_fd
    else:
        os.makedirs(directory, exist_ok=True)
        yield None


def directory_root(directory):
    return dir_segments(directory)[0]


def report_lines(readers, host, timestamp, version, kernel, pve_version,
                 progress_fn=None):
    """組成整份報告；報告永遠以自己的無色 context 產生。

    [CHANGE] 2026-08-04 待辦 #36：原簽名收一個 `ctx`，而函式體從第一行起就自己建
             `safe_ctx`，那個參數**從未被讀取過**。收下卻靜默丟棄比不收更糟——
             呼叫端傳一個開了顏色的 context 進來，會合理地以為報告就會有顏色。
             不信任呼叫端的 context 是對的，作法是**不要收**，不是收了不用。
    """
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


def _open_candidate(candidate, flags, opener, dir_chain, dir_fd_supported,
                    directory, nofollow, parent_fd=None):
    """開出報告檔的 fd；有 dir_fd 的平台改走逐段開啟的父目錄。

    ★ 建檔權限只寫在這裡一次。兩條分支各寫一次 0o600 的話，突變條目就沒辦法
      指名其中一條——命中兩次的 old 會被 `--check-targets` 判成位置有歧義。
    ★ [CHANGE] 2026-08-05 待辦 #67：呼叫端已經持有父目錄 fd 時直接用它，不再
      重新解析一次路徑。撞名重試也共用同一個 fd——原本每試一次就重解析一次。
    """
    mode = 0o600
    if dir_fd_supported:
        # ★ basename 這一步只寫一次是刻意的（理由同上：突變條目要指名得到）。
        #   兩條來源（呼叫端交來的 fd／自己開一條鏈）只差在 fd 從哪裡來。
        with contextlib.ExitStack() as stack:
            fd = (parent_fd if parent_fd is not None
                  else stack.enter_context(dir_chain(directory, nofollow)))
            return opener(os.path.basename(candidate), flags, mode, dir_fd=fd)
    return opener(candidate, flags, mode)


def _write_fd(fd, lines, chmod_fn):
    """把行寫進已開啟的 fd；權限補強走 fd 不走路徑。"""
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


def write_report(path, lines, opener=None, chmod_fn=None,
                 makedirs_fn=None, nofollow_flag=None, dir_chain=None,
                 dir_fd_supported=None, parent_fd=None):
    """以原子式權限判準建立並寫入 UTF-8/LF 報告；回傳**實際寫入的路徑**。

    ★ 回傳值可能與傳入的 path 不同（撞名時會加序號）。呼叫端 MUST 用回傳值，
      MUST NOT 沿用自己傳進去的那一個——印一個沒有被寫到的路徑，比不印還糟：
      使用者會照著去看一個不存在的檔，然後以為報告壞了。

    ★ [CHANGE] 2026-08-05 待辦 #67：`parent_fd` 是**已經開好的** `os.path.dirname(path)`
      那個目錄的 fd（由 prepared_dir() 交出來）。給了它就代表目錄已存在且已被持有，
      於是本函式**不會**再呼叫 makedirs_fn——那一步會重新解析一次路徑，而消掉
      重複解析正是 #67 的全部內容。不給就維持原路徑，既有呼叫端一個字都不必改。
    """
    opener = os.open if opener is None else opener
    # [CHANGE] 2026-08-03 待辦 #46：補強權限改吃 fd 而非路徑。走路徑的 chmod 是在 open
    #          之後才重新解析一次名稱，那個空隙足以讓路徑被抽換，結果是把 0600 打到別人
    #          的檔案上。fd 指向的是已經開啟的那個 inode，沒有第二次解析。
    #          ★ os.fchmod 實測在本機 Windows 3.13 亦可呼叫，故不寫平台 fallback——
    #            那會是一個在開發機與目標機都走不到的分支。
    chmod_fn = os.fchmod if chmod_fn is None else chmod_fn
    makedirs_fn = os.makedirs if makedirs_fn is None else makedirs_fn
    nofollow = NOFOLLOW_FLAG if nofollow_flag is None else nofollow_flag
    dir_chain = open_dir_chain if dir_chain is None else dir_chain
    if dir_fd_supported is None:
        dir_fd_supported = os.open in os.supports_dir_fd
    directory = os.path.dirname(path) or "."
    if parent_fd is None:
        makedirs_fn(directory, exist_ok=True)
    # [CHANGE] 2026-08-04 待辦 #51：O_TRUNC 拿掉、換成 O_EXCL。O_EXCL 保證這個檔是
    #          我們建的，既然是新建的就沒有東西可以截斷——兩者同時寫只會讓讀的人
    #          以為還有覆寫路徑。
    # ★ O_EXCL 與 O_NOFOLLOW 在**最後一段**上射程重疊：POSIX 規定 O_CREAT|O_EXCL
    #   遇到既有 symlink 一律 EEXIST，不論它指向哪裡。兩個都留著是刻意的——
    #   哪天有人把 O_EXCL 拿掉（例如為了「同一秒重跑不要改名」），O_NOFOLLOW 仍在。
    #   ★ O_NOFOLLOW 對**父目錄**沒有射程，那是 dir_fd 逐段開啟在守的，見上方註解。
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow
    candidate = path
    for attempt in range(1, MAX_NAME_ATTEMPTS + 1):
        candidate = suffixed_path(path, attempt)
        try:
            fd = _open_candidate(candidate, flags, opener, dir_chain,
                                 dir_fd_supported, directory, nofollow,
                                 parent_fd)
        except FileExistsError:
            continue
        _write_fd(fd, lines, chmod_fn)
        return candidate
    raise FileExistsError(
        "報告檔名連續 %d 次都已存在，最後嘗試：%s" % (MAX_NAME_ATTEMPTS, candidate))


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
    # [CHANGE] 2026-08-04 待辦 #50 的具名殘留（該棒第 1 輪對抗式覆核抓到）：
    #   這一步原本用真的 os.makedirs，而它**會跟隨 symlink**。REPORT_DIR 若指向
    #   一個父目錄是 symlink 的不存在路徑，就會穿過去建出目錄。
    # [CHANGE] 2026-08-05 待辦 #60：已補上。支援 dir_fd 的平台改走 mkdir_chain()
    #   逐段建立，每一段都帶 O_NOFOLLOW。
    #   ★ [CHANGE] 2026-08-05 待辦 #67：入口由 `choose_makedirs()` 改成
    #     `prepared_dir()`（context manager）。**注入分支的呼叫形態沒有變**——
    #     仍是 `makedirs_fn(directory, exist_ok=True)`，既有注入點不受影響。
    #   ★ exist_ok 在逐段分支被忽略是**刻意**的：mkdir_chain 對已存在的段一律
    #     略過，語意等同 exist_ok=True，而本檔沒有任何呼叫端傳 False。
    #   ★ Windows 不支援 dir_fd ⇒ 仍走 os.makedirs，那條路徑的殘留維持原狀
    #     （危害僅止於在別人的目錄下多一個空目錄，報告內容仍不會外洩：
    #     write_report() 的逐段開啟會以 ELOOP 失敗，一個位元組都不寫出去）。
    # [CHANGE] 2026-08-05 待辦 #67：目錄的 fd 在整段 with 內都被持有，寫檔時直接
    #   相對於它開檔 ⇒ 路徑只解析一次。持有期間橫跨 report_lines() 的耗時取值，
    #   那是刻意的：中途放掉 fd 就等於把那次解析放回去。
    with contextlib.ExitStack() as stack:
        try:
            parent_fd = stack.enter_context(prepared_dir(directory, makedirs_fn))
        except OSError:
            stderr_fn(error(t("report.mkdir_failed", path=directory),
                            ctx.palette) + "\n")
            return path, 1
        progress = None

        if not quiet:
            progress = lambda text: stdout_fn("  %s\n" % text)
        lines = report_lines(readers, host, now, version, kernel_fn(),
                             _pve_version(run_fn), progress_fn=progress)
        try:
            # [CHANGE] 2026-08-04 待辦 #51：撞名時 write_report() 會改用加序號的檔名，
            #          故成功訊息與回傳值都 MUST 用它回報的**實際路徑**。
            # ★ makedirs_fn 仍傳 no-op：沒有 dir_fd 的平台 parent_fd 是 None，
            #   那條路徑上 write_report() 會照原樣呼叫它，而目錄這裡已經建好了。
            written = write_report(path, lines, opener=opener, chmod_fn=chmod_fn,
                                   makedirs_fn=lambda _path, exist_ok=True: None,
                                   parent_fd=parent_fd)
        except (OSError, IOError):
            stderr_fn(error(t("report.create_failed", path=path),
                            ctx.palette) + "\n")
            return path, 1
    stdout_fn("\n%s\n" % success(t("report.done", path=written), ctx.palette))
    return written, 0
