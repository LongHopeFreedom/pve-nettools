# [CHANGE] 2026-08-02 pager 必須保住完整盤查輸出，並把使用者提早離開視為正常操作。
"""把完整輸出交給可用的終端 pager。"""

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


def _default_spawn(argv):
    return subprocess.Popen(argv, stdin=subprocess.PIPE, universal_newlines=True)


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
        process = spawn(command)
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
    # ★ 收拾完仍 re-raise：決定「怎麼向使用者交代中斷」是 cli.main() 的職責，不是
    #   pager 的。兩層各做各的，才不會兩個地方都印一次訊息。
    # ★ 第二次 wait 再被打斷就放手——使用者連按兩次 Ctrl-C 的意思是「現在就走」。
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
