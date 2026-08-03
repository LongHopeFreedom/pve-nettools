# [CHANGE] 2026-08-02 LED 定位沿用 collect 共用三態，避免外部指令錯誤分類日後漂移。
"""執行實體網卡 LED 定位，不包含任何互動畫面。"""

import os

from . import STATUS_UNAVAILABLE, default_run, run_command
# [CHANGE] 2026-08-02 原本在本檔複製了一份 render/theme.py 的 _positive_int。
#          兩份複本無人對帳，且 collect 層 MUST NOT 依賴 render 層，故共用實作
#          抽到套件根的 util.py，兩邊都引用它。
from ..util import positive_int as _positive_int

BLINK_SECONDS_DEFAULT = 10

REASON_TOOL_MISSING = "tool_missing"
REASON_UNSUPPORTED = "unsupported"
REASON_EXECUTION_FAILED = "execution_failed"


def blink_seconds(env=None):
    """讀取正整數秒數；空值、auto、零、負數或非數字都回預設值。"""
    env = os.environ if env is None else env
    value = _positive_int(env.get("BLINK_SECONDS"))
    return BLINK_SECONDS_DEFAULT if value is None else value


def blink(run_fn, nic, seconds=None):
    """執行 ethtool 定位，並用 reason 細分工具缺少與硬體不支援。"""
    duration = _positive_int(seconds)
    if duration is None:
        duration = BLINK_SECONDS_DEFAULT
    runner = default_run if run_fn is None else run_fn
    tool_missing = [False]
    command_ran = [False]

    def tracked_run(argv):
        try:
            completed = runner(argv)
            command_ran[0] = True
            return completed
        except FileNotFoundError:
            tool_missing[0] = True
            raise

    result = run_command(
        tracked_run, ["ethtool", "-p", str(nic), str(duration)])
    result["reason"] = None
    if result["status"] == STATUS_UNAVAILABLE:
        if tool_missing[0]:
            result["reason"] = REASON_TOOL_MISSING
        elif command_ran[0]:
            result["reason"] = REASON_UNSUPPORTED
        else:
            result["reason"] = REASON_EXECUTION_FAILED
    return result
