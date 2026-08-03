# [CHANGE] 2026-08-02 新增：corosync 叢集網路供料（選單第 14 項，待辦 #16）。
"""解析 corosync.conf 並取得環網即時狀態。

規格真值＝bash `render_corosync`（`old/pve-network-audit.sh:1784-1827`）。

★ 為什麼要解析而不是整份印出：`corosync.conf` 含 `logging`、`quorum` 等與網路
  無關的大段落，而這一頁要回答的問題只有兩個——「有幾個節點、各自的環網位址是
  什麼」與「是不是只有單一環網」。bash 用一段 awk 做到，這裡照做。

★ 為什麼結果是**有序清單**而不是 dict：bash 的 awk 是逐行處理，節點行與叢集層
  選項行（cluster_name／transport／…）**依檔案順序交錯輸出**。改成先印節點再印
  選項會與 bash 的畫面不同，而那個順序是 corosync.conf 自己的段落順序（nodelist
  在前、totem 在後），對讀的人是有意義的。
"""

import os
import re

from . import STATUS_OK, STATUS_UNAVAILABLE, default_run, run_command
from .textconf import TextConfReader

__all__ = [
    "CLUSTER_OPTION_KEYS",
    "ClusterReader",
    "DEFAULT_CONF_NAME",
    "parse_corosync",
]

DEFAULT_CONF_NAME = "corosync.conf"

# bash：/^[[:space:]]*(cluster_name|transport|secauth|crypto_cipher|link_mode):/
CLUSTER_OPTION_KEYS = ("cluster_name", "transport", "secauth",
                       "crypto_cipher", "link_mode")

_NODE_OPEN_RE = re.compile(r"^\s*node\s*{")
_CLOSE_RE = re.compile(r"^\s*}")
_OPTION_RE = re.compile(r"^\s*(%s)\s*:" % "|".join(CLUSTER_OPTION_KEYS))

# 節點內的四個欄位。★ 以**錨定**的正則取值，不用 `"name:" in line` 這種子字串
# 判定——`cluster_name:` 含有 `name:`，子字串判定會把它誤認成節點名稱。
# 這與記憶裡「掃 frontmatter 禁用子字串比對」是同一條。
_NODE_FIELDS = {
    "name": re.compile(r"^\s*name\s*:\s*(.*)$"),
    "nodeid": re.compile(r"^\s*nodeid\s*:\s*(.*)$"),
    "ring0": re.compile(r"^\s*ring0_addr\s*:\s*(.*)$"),
    "ring1": re.compile(r"^\s*ring1_addr\s*:\s*(.*)$"),
}


def parse_corosync(text):
    """回 {"entries": [...], "has_ring1": bool}。

    entries 依檔案順序，每筆為下列兩種之一：
      {"kind": "node",   "name", "nodeid", "ring0", "ring1"}
      {"kind": "option", "text"}
    ring1 缺席時為 None（顯示成什麼由 render 決定，供料層不塞「（未設定）」）。
    """
    entries = []
    has_ring1 = False
    node = None

    for line in text.splitlines():
        if _NODE_OPEN_RE.match(line):
            node = {"kind": "node", "name": None, "nodeid": None,
                    "ring0": None, "ring1": None}
            continue

        if node is not None:
            if _CLOSE_RE.match(line):
                entries.append(node)
                node = None
                continue
            for field, pattern in _NODE_FIELDS.items():
                found = pattern.match(line)
                if found is not None:
                    value = found.group(1).strip()
                    node[field] = value or None
                    if field == "ring1" and value:
                        has_ring1 = True
                    break
            continue

        if _OPTION_RE.match(line):
            entries.append({"kind": "option", "text": line.strip()})

    # ★ 檔案結尾少一個 `}` 時 bash 會靜默丟掉最後一個節點（awk 只在遇到 `}`
    #   才 print）。這裡補上，因為「設定檔壞了」與「少一個節點」在畫面上同形，
    #   而後者會讓人以為叢集真的少一台。
    if node is not None:
        entries.append(node)

    return {"entries": entries, "has_ring1": has_ring1}


class ClusterReader(object):
    """corosync 設定與環網狀態。"""

    def __init__(self, root=None, run_fn=None, conf_reader=None):
        self.conf = conf_reader or TextConfReader(root=root)
        self.run_fn = run_fn if run_fn is not None else default_run
        self._cache = {}

    def conf_path(self):
        return self.conf.path(DEFAULT_CONF_NAME)

    def exists(self):
        return os.path.isfile(self.conf_path())

    def read(self):
        """回 {"status", "data", "error", "path"}。"""
        path = self.conf_path()
        result = self.conf.read_lines(path)
        if result["status"] == STATUS_UNAVAILABLE:
            return {"status": STATUS_UNAVAILABLE, "data": None,
                    "error": result["error"], "path": path}
        # ★ 這裡 MUST 用原文而非 meaningful_lines 的結果嗎？不用——被濾掉的只有
        #   註解與空行，而 parse_corosync 的每一條正則都要求該行有實質內容。
        #   但 `}` 也是實質內容且會被保留，故區塊結構不受影響。
        parsed = parse_corosync("\n".join(result["lines"]))
        return {"status": STATUS_OK, "data": parsed, "error": None,
                "path": path}

    def _command(self, argv):
        key = tuple(argv)
        if key not in self._cache:
            self._cache[key] = run_command(self.run_fn, argv)
        return self._cache[key]

    def cfgtool_status(self):
        """`corosync-cfgtool -s` 的原始輸出。"""
        return self._command(["corosync-cfgtool", "-s"])

    def pvecm_status(self):
        """`pvecm status` 的原始輸出。"""
        return self._command(["pvecm", "status"])
