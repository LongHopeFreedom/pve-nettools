# [CHANGE] 2026-08-02 新增：PVE SDN 供料（選單第 13 項，待辦 #16）。
"""讀取 `/etc/pve/sdn` 下的設定檔與 SDN 執行期狀態。

規格真值＝bash `render_sdn`（`old/pve-network-audit.sh:1751-1780`）。

★ 這一段 bash **不解析**任何 SDN 設定的語意，只是把六個 `.cfg` 逐份濾掉註解後
  原樣印出。故本模組也不解析——SDN 的段落格式（zones/vnets/subnets 各有各的
  欄位）會隨 PVE 版本演進，而一個解析不到就吞掉內容的解析器，比原樣印出更糟。
"""

import os

from . import STATUS_EMPTY, STATUS_OK, STATUS_UNAVAILABLE, default_run, run_command
from .textconf import TextConfReader

__all__ = ["SDN_DIR", "SDN_FILES", "SdnReader"]

SDN_DIR = "sdn"

# bash：for f in zones vnets subnets controllers ipams dns
# ★ 順序 MUST 逐字沿用——它不是字母序，是「由外而內」的閱讀順序
#   （zone 裝 vnet、vnet 裝 subnet），照字母排會把 controllers 排到最前面。
SDN_FILES = ("zones", "vnets", "subnets", "controllers", "ipams", "dns")


class SdnReader(object):
    """PVE SDN 設定與執行期狀態。"""

    def __init__(self, root=None, run_fn=None, conf_reader=None):
        self.conf = conf_reader or TextConfReader(root=root)
        self.run_fn = run_fn if run_fn is not None else default_run
        self._runtime = None

    def directory(self):
        return self.conf.path(SDN_DIR)

    def exists(self):
        return os.path.isdir(self.directory())

    def configs(self):
        """回 [(名稱, 讀取結果)]，只含**有實質內容**的檔。

        ★ bash 的條件是兩層：`-f`（存在）且 `-s`（非空檔）。這裡再嚴一格——
          整份都是註解的檔也排除，因為它在畫面上會印出一個空的小標題，讀起來
          像工具壞了。差異已具名：bash 會為「只有註解的 .cfg」印出空標題。
        """
        found = []
        for name in SDN_FILES:
            path = os.path.join(self.directory(), "%s.cfg" % name)
            result = self.conf.read_lines(path)
            if result["status"] != STATUS_OK:
                continue
            found.append((name, result))
        return found

    def runtime(self):
        """`pvesh get /cluster/sdn --output-format text` 的原始輸出。"""
        if self._runtime is None:
            self._runtime = run_command(
                self.run_fn,
                ["pvesh", "get", "/cluster/sdn", "--output-format", "text"])
        return self._runtime

    def read(self):
        """一次取齊，讓 render 只呼叫一次就拿到全部。"""
        if not self.exists():
            return {"status": STATUS_UNAVAILABLE, "configs": [],
                    "runtime": None, "directory": self.directory()}
        configs = self.configs()
        return {
            "status": STATUS_OK if configs else STATUS_EMPTY,
            "configs": configs,
            # ★ 沒有任何設定內容時 bash 直接 return，**不會**去跑 pvesh。
            #   照做的理由不只是等價：pvesh 在非叢集主機上會等 timeout。
            "runtime": self.runtime() if configs else None,
            "directory": self.directory(),
        }
