# [CHANGE] 2026-08-02 pager 必須保住完整盤查輸出，並把使用者提早離開視為正常操作。
"""把完整輸出交給可用的終端 pager。"""

__all__ = ["LESS_CHARSET_VALUE", "LESS_CHARSET_VAR", "page_output",
           "pager_available", "pager_command", "pager_env"]

import errno
import os
import shutil
import subprocess
import sys

# [CHANGE] 2026-08-02 原本在本檔複製了一份 render/theme.py 的 _default_isatty。
#          兩份複本無人對帳，故共用實作抽到套件根的 util.py。
from .util import isatty as _default_isatty


def _conditions(env, isatty_fn, which_fn):
    env = os.environ if env is None else env
    isatty = _default_isatty if isatty_fn is None else isatty_fn
    which = shutil.which if which_fn is None else which_fn
    if not isatty(1) or env.get("NO_PAGER") == "1":
        return None
    if which("less"):
        return ["less", "-SRX"]
    if which("more"):
        return ["more"]
    return None


def pager_available(env=None, isatty_fn=None, which_fn=None):
    """stdout、NO_PAGER 與程式存在性三道判準全數成立才可使用。"""
    return _conditions(env, isatty_fn, which_fn) is not None


def pager_command(env=None, isatty_fn=None, which_fn=None):
    """回傳優先採用 less 的 argv；不可用時回 None。"""
    return _conditions(env, isatty_fn, which_fn)


# [CHANGE] 2026-08-25 pager 子行程的字元集環境。
#
# 實地缺陷（2026-08-25 於一台真機回報）：進入 less 之後，畫面上每一個
#   非 ASCII 字元都被逐位元組展開成 `<E5><AF><A6>`，欄位對齊全毀。
#
#   關鍵鑑別：less 啟動**之前**印到終端的中文完全正常，而 less 內連
#   `MAC Address`／`1000Mb/s` 這些純 ASCII 也都好好的 ⇒ 終端是 UTF-8、
#   本工具的輸出也是 UTF-8，**壞的只有 less 對字元集的判定**。
#
# 這不是「中文才有」的問題：英文介面同樣中招，因為區塊標題的
#   `── nic2 ──` 用的是 U+2500（UTF-8 為 E2 94 80）。切語系躲不掉。
#
#   成因：PVE 的 locale 預設是 C（本檔隔壁的 `cli.usage_env` 早就寫著
#   「PVE 的 locale 多為 C」），less 在該情況下把字元集當成 ASCII。
#   `LESSCHARSET` 是 less 官方支援的環境變數，優先於 locale 推導。
LESS_CHARSET_VAR = "LESSCHARSET"
LESS_CHARSET_VALUE = "utf-8"


def pager_env(env=None):
    """回傳要交給 pager 子行程的環境。

    回傳的是**補上一項的完整環境**，不是只有那一項——子行程沒有 TERM 就不知道
      終端能力，沒有 PATH 連自己都找不到，畫面會壞得比原本更徹底。

    使用者已明確設定 `LESSCHARSET` 時不覆蓋。這裡補的是「沒人設定時的預設」，
      不是「工具比使用者更懂」。

    複製一份再改，不得就地寫入：傳進來的很可能就是 `os.environ`，
      污染它會讓本行程後續每一次子行程啟動都帶著這一項，而症狀出現的地方
      離這裡很遠。
    """
    source = os.environ if env is None else env
    child = dict(source)
    child.setdefault(LESS_CHARSET_VAR, LESS_CHARSET_VALUE)
    return child


def _default_spawn(argv, env, popen_fn=None):
    """啟動 pager。

    `encoding="utf-8"` 必須明確指定，不得退回 `universal_newlines=True`：
      後者的編碼取自 `locale.getpreferredencoding()`，在 LANG=C 的主機上那是個
      隱含相依，最壞情況是 `UnicodeEncodeError` 讓整份盤查中斷。
      這與 `LESSCHARSET` 是**不同的兩件事**——一個是工具怎麼寫，一個是 less
        怎麼讀。兩者恰好都由同一個 locale 引起，但少做任何一邊都不算修好。
    """
    popen = subprocess.Popen if popen_fn is None else popen_fn
    return popen(argv, stdin=subprocess.PIPE, encoding="utf-8", env=env)


def _default_write(text):
    sys.stdout.write(text)


def _as_text(lines):
    return "".join(line if line.endswith("\n") else line + "\n" for line in lines)


def _is_epipe(exc):
    return isinstance(exc, BrokenPipeError) or (
        isinstance(exc, OSError) and getattr(exc, "errno", None) == errno.EPIPE)


def page_output(lines, env=None, isatty_fn=None, which_fn=None,
                spawn_fn=None, write_fn=None):
    """輸出所有 lines；pager 被 q 關閉造成的 EPIPE 不算錯誤。"""
    text = _as_text(list(lines))
    command = pager_command(env, isatty_fn, which_fn)
    write = _default_write if write_fn is None else write_fn
    if command is None:
        write(text)
        return None

    spawn = _default_spawn if spawn_fn is None else spawn_fn
    try:
        # [CHANGE] 2026-08-25 環境必須經過這個注入點交給子行程。
        # 只讓 `_default_spawn` 自己去讀 os.environ 也能跑，但那樣
        #   「有沒有真的把 LESSCHARSET 傳過去」就沒有任何測試守得到——
        #   純函式回傳正確的字典、而這裡根本沒交出去，兩者在單測純函式時
        #   輸出完全相同。
        process = spawn(command, pager_env(env))
    except OSError:
        write(text)
        return None

    try:
        process.stdin.write(text)
        process.stdin.close()
        process.wait()
    # [CHANGE] 2026-08-03：Ctrl-C 時 SIGINT 送給的是**整個前景群組**，pager 自己也
    #   收到了。這裡再 wait 一次，讓它把終端收拾乾淨——less 要還原 alternate screen
    #   並復原 termios 設定；直接往上拋會讓終端停在殘缺畫面，使用者得自己打 reset。
    # 收拾完仍 re-raise：決定「怎麼向使用者交代中斷」是 cli.main() 的職責，不是
    #   pager 的。兩層各做各的，才不會兩個地方都印一次訊息。
    # 第二次 wait 再被打斷就放手——使用者連按兩次 Ctrl-C 的意思是「現在就走」。
    except KeyboardInterrupt:
        try:
            process.wait()
        except KeyboardInterrupt:
            pass
        raise
    except (BrokenPipeError, OSError) as exc:
        if not _is_epipe(exc):
            raise
        try:
            process.wait()
        except (BrokenPipeError, OSError) as wait_exc:
            if not _is_epipe(wait_exc):
                raise
    return None
