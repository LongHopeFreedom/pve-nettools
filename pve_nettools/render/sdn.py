# [CHANGE] 2026-08-02 新增：PVE SDN 輸出區段（選單第 13 項，待辦 #16）。
"""PVE SDN 設定檔與執行期狀態。

規格真值＝bash `render_sdn`（`old/pve-network-audit.sh:1751-1780`）。
"""

from ..collect import FAILURE_NOT_EXECUTABLE, STATUS_OK, STATUS_UNAVAILABLE
from ..i18n import t
from .base import Section, blank, note, subsection

__all__ = ["SdnSection"]


class SdnSection(Section):
    """PVE SDN。"""

    def __init__(self, sdn_reader):
        self.sdn = sdn_reader

    def build(self):
        return self.sdn.read()

    def is_empty(self, data):
        return not data["configs"]

    def empty_lines(self, data, ctx):
        if data["status"] == STATUS_UNAVAILABLE:
            return [note(t("sdn.not_found", path=data["directory"]), ctx.palette)]
        return [note(t("sdn.empty"), ctx.palette)]

    def table(self, data, ctx):
        return None

    def blocks(self, data, ctx):
        lines = []
        for name, result in data["configs"]:
            lines.append(blank())
            lines.extend(subsection(t("sdn.file_title", name=name), ctx.palette))
            lines.extend(result["lines"])

        runtime = data["runtime"]
        # ★ bash 只在 `command_exists pvesh` 時才印這一段。Python 這邊的等價
        #   判準是「指令跑不跑得起來」——runtime 為 None 代表上游根本沒去跑
        #   （沒有任何設定內容時 collect 會略過，理由見 collect/sdn.py）。
        if runtime is None:
            return lines
        if runtime["status"] == STATUS_UNAVAILABLE and _not_executable(runtime):
            return lines

        lines.append(blank())
        lines.extend(subsection(t("sdn.runtime_title"), ctx.palette))
        if runtime["status"] == STATUS_OK:
            lines.extend(runtime["stdout"].splitlines())
        else:
            lines.append(note(t("sdn.runtime_failed"), ctx.palette))
        return lines


def _not_executable(result):
    """pvesh 根本不存在時整段不印，與 bash 的 command_exists 同義。

    ★ 與「pvesh 存在但取不到狀態」是兩件事：後者 bash 會印小標題再印一句
      「無法取得」，前者整段不出現。合併之後，非 PVE 主機的報告會多出一段
      看起來像故障的內容。
    """
    return result.get("failure") == FAILURE_NOT_EXECUTABLE
