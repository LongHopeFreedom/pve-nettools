# [CHANGE] 2026-08-01 新增：render 層的顏色與終端寬度判定（待辦 #8 骨架）。
"""顏色與終端寬度——決定「用哪一種版面」的那一層。

這裡的兩件事在 bash 版是踩過雷才改對的，移植時 MUST 保留其判準：

1. **寬度要向「有終端可問的地方」問，不是只看 stdout。**
   互動檢視會把輸出接給 pager，此時 stdout 是 pipe，但使用者面前仍然是一個有固定
   寬度的終端。只看 stdout 會誤判成寬螢幕，窄終端的區塊版永遠不會被觸發
   （bash v02.002.000 的修正）。stdout 與 stderr **皆**非 tty 才是真正的報告／管線
   情境，此時回 REPORT_WIDTH。

2. **報告版面不受終端寬度影響。**
   同一份報告在不同機器上讀必須一致，所以報告情境固定回一個大到永遠選表格版的
   寬度，而不是去問終端。

★ 兩者都可注入（env / isatty_fn / size_fn），否則這一層只能在真終端上驗證，
  等同於沒有人驗。
"""

import os

# [CHANGE] 2026-08-02 這兩個函式原本就定義在本檔，待辦 #10 的 pager 與 LED 定位
#          各自抄了一份逐字相同的複本。三份複本無人對帳（改一份另外兩份不會有
#          任何測試變紅），故抽到套件根的 util.py，本檔改為引用。
#          別名維持 `_` 開頭：它們在本檔仍是實作細節，不屬公開介面。
from ..util import isatty as _default_isatty, positive_int as _positive_int

# 報告／管線情境採用的寬度。大到任何表格都放得下，故報告恆為表格版。
REPORT_WIDTH = 9999

# 問不到終端寬度時的保底值，與 bash 版一致。
FALLBACK_WIDTH = 80

_COLOUR_CODES = {
    "red": "\033[0;31m",
    "green": "\033[0;32m",
    "yellow": "\033[0;33m",
    "blue": "\033[0;34m",
    "cyan": "\033[0;36m",
    "bold": "\033[1m",
}

RESET = "\033[0m"


class Palette(object):
    """ANSI 著色。enabled 為 False 時 paint() 原樣回傳，不留下任何逸出碼。

    ★ 關掉時 MUST 回「原樣的字串本身」而不是空碼夾住的字串：報告檔會被 grep、
    會被貼進工單，多兩個逸出碼在肉眼上看不出來，卻會讓比對失敗。
    """

    def __init__(self, enabled=True):
        self.enabled = bool(enabled)

    @classmethod
    def auto(cls, isatty_fn=None):
        """依 stdout 是否為終端決定要不要上色（與 bash 版 `[[ -t 1 ]]` 同判準）。

        報告模式的 stdout 是檔案或管線，於是自動無色——報告檔不該含 ANSI 碼。
        """
        isatty = _default_isatty if isatty_fn is None else isatty_fn
        return cls(enabled=bool(isatty(1)))

    def paint(self, text, colour):
        """把 text 塗成 colour。colour 為 None／空字串時不塗。"""
        if not self.enabled or not colour:
            return text
        code = _COLOUR_CODES.get(colour)
        if code is None:
            raise ValueError("未知的顏色：%s" % colour)
        return code + text + RESET

    def available(self):
        return sorted(_COLOUR_CODES)


def term_width(env=None, isatty_fn=None, size_fn=None):
    """回傳版面判定要用的終端寬度。

    優先序（MUST NOT 調換前兩項）：
      1. `TERM_WIDTH` 明示指定——供測試與使用者強制指定，最優先
      2. stdout 與 stderr **皆**非 tty ⇒ REPORT_WIDTH（報告／管線情境）
      3. 向 stdout、再向 stderr 問實際終端大小
      4. `COLUMNS`
      5. FALLBACK_WIDTH

    ★ 第 2 項排在問終端之前：報告情境下就算問得到寬度也不能用它，否則同一份報告
      在不同機器上版面會不同。
    """
    env = os.environ if env is None else env
    isatty = _default_isatty if isatty_fn is None else isatty_fn
    size = _default_terminal_size if size_fn is None else size_fn

    explicit = _positive_int(env.get("TERM_WIDTH"))
    if explicit is not None:
        return explicit

    if not isatty(1) and not isatty(2):
        return REPORT_WIDTH

    for fd in (1, 2):
        measured = _positive_int(size(fd))
        if measured is not None:
            return measured

    from_env = _positive_int(env.get("COLUMNS"))
    if from_env is not None:
        return from_env

    return FALLBACK_WIDTH


def _default_terminal_size(fd):
    try:
        return os.get_terminal_size(fd).columns
    except (OSError, ValueError, AttributeError):
        return None
