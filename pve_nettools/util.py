# [CHANGE] 2026-08-02 待辦 #10 批 A 驗收：把三處逐字相同的複本抽成一份。
"""跨層共用的小工具。

## 為什麼這個模組存在

這裡的兩個函式原本各有兩份**逐字相同**的複本：`positive_int` 在
`render/theme.py` 與 `collect/led.py`，`isatty` 在 `render/theme.py` 與
`pager.py`。抽成一份的理由與 `collect/__init__.py` 的 docstring 寫的是同一條：

> 兩份複本一旦漂移不會有任何測試變紅——某一邊把 `> 0` 改成 `>= 0`，呼叫端只會
> 靜默走進另一條分支。所以在第二個使用者出現的當下就抽成一份，而不是等第三個。

而第二個使用者正是本批的 pager 與 LED 定位。

★ 放在套件根而不是 `collect/` 或 `render/` 底下：**collect 層 MUST NOT 依賴
  render 層**（那是分層倒置），而這兩個函式兩邊都要用。

★ 抽成一份之後，守它的突變條目也只需要一條（harness 的 B）——一條判準、一個
  地方、一次驗證，而它的 expect 同時指名 theme 與 LED 兩邊的測試。
"""

import os


def positive_int(raw):
    """把設定值轉成正整數；不是正整數就回 None（交給下一個來源）。

    ★ 空字串、`auto`、負數、`0` 都 MUST 當成「沒設定」而不是 `0`。兩個使用者
    各自的失效形態都是**靜默**的：寬度 0 會讓每個區段都選區塊版（症狀是「明明
    螢幕很寬卻永遠不用表格」），LED 秒數 0 會讓燈完全不閃卻回報「定位完成」
    ——後者會讓現場人員拔錯線，而且不會有任何錯誤訊息。
    """
    if raw is None:
        return None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def isatty(fd):
    """fd 是不是終端；問不到就當成「不是」。

    ★ 猜錯的代價不對稱：誤判成「是」會讓報告檔帶上 ANSI 逸出碼（被 grep、被貼
    進工單時比對失敗），誤判成「不是」只是少了顏色。所以取不到時 MUST 回 False。
    """
    try:
        return os.isatty(fd)
    except (OSError, ValueError):
        return False
