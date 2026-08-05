# [CHANGE] 2026-08-02 新增：純文字設定檔的原文讀取（選單 13／14／15／17 的共用供料）。
"""把設定檔讀成「可讀的原文行」。

## 為什麼需要這一層

bash 版有四個區段（SDN、corosync、防火牆、持久化設定）的呈現方式**不是**結構化
表格，而是逐字印出設定檔內容，只濾掉整行註解與空白行：

    grep -Ev '^[[:space:]]*(#|$)' "$f"

Python 版已經有 `firewall.parse_fw` 與 `netconf.parse_interfaces` 兩個**解析器**，
但它們回傳的是結構，不是原文。要與 bash 畫面等價就得印回原文，而從結構重建原文
是有損的（section 標頭、options 的原始順序都回不來）。

★ 所以「有解析器」不等於「有供料」。這一點在待辦 #17 已經踩過一次：交接檔寫
  「有供料只缺 key」，實測 `_parse_eeprom` 早在解析階段就把 bash 要的欄位丟掉了。
  這次的第 15／17 兩項是**同一個形狀的第二次**——解析得越完整，越容易讓人以為
  原文也還在。

## 為什麼濾行規則抽成一份

`firewall._meaningful_lines` 原本是本規則唯一的實作。現在第二個使用者出現了，
依本套件既定立場（見 `collect/__init__.py` 的 docstring）在**第二個使用者出現的
當下**就抽成一份，而不是等第三個：兩份濾行規則一旦漂移，某一邊多濾或少濾一種
註解形態，不會有任何測試變紅。
"""

import os

from . import STATUS_EMPTY, STATUS_OK, STATUS_UNAVAILABLE

__all__ = [
    "TextConfReader",
    "meaningful_lines",
]


def meaningful_lines(text):
    """剔除整行註解與空白行，保留其餘行的原文。

    ★ 只認**整行**註解（行首第一個非空白字元是 `#`），行尾註解一律保留——bash 的
      `grep -Ev '^[[:space:]]*(#|$)'` 也是這個範圍。把 `iface eno1 # 上聯` 的尾註
      砍掉會改變設定檔的原文，而使用者是拿這一頁去對照真正的檔案的。
    """
    return [line for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


class TextConfReader(object):
    """讀設定檔原文。root 可替換，讓測試指向 fixture 而不需要真的 /etc/pve。"""

    def __init__(self, root=None, default_root="/etc/pve", env_key="PVE_CONF_ROOT"):
        # [CHANGE] 2026-08-02 env_key 可帶入，因為持久化設定的根不是 PVE_CONF_ROOT
        #          而是 /etc/network——同一個讀取行為、兩個不同的根。
        self.root = root or os.environ.get(env_key) or default_root

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    def read_lines(self, path):
        """回 {status, lines, error}，三態的分界與 collect 其餘模組一致。

        ★ `empty` 與 `unavailable` MUST NOT 合併：「這個檔存在但整份都是註解」與
          「這台主機沒有這個檔」在盤查報告裡是兩種結論，前者代表設定被清空過，
          後者代表沒裝這個元件。
        """
        if not os.path.isfile(path):
            return {"status": STATUS_UNAVAILABLE, "lines": None,
                    "error": "%s 不存在或不是一般檔案" % path}
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError as exc:
            return {"status": STATUS_UNAVAILABLE, "lines": None,
                    # [CHANGE] 2026-08-05 待辦 #14：全形冒號改半形（理由同 netconf.py）。
                    "error": "%s: %s" % (path, exc)}

        lines = meaningful_lines(text)
        return {"status": STATUS_OK if lines else STATUS_EMPTY,
                "lines": lines, "error": None}

    def exists(self, path):
        return os.path.isfile(path)

    def list_files(self, directory, suffix=None):
        """列出目錄下的一般檔案（完整路徑），依名稱排序。

        ★ 排序 MUST 明寫：`os.listdir` 的順序由檔案系統決定，同一份設定在兩台
          主機上會印出不同的順序，而報告是拿來逐行比對的。bash 靠 shell 的
          `*` 展開（已排序）取得同樣的性質。
        """
        try:
            names = os.listdir(directory)
        except OSError:
            return []
        found = []
        for name in sorted(names):
            if suffix is not None and not name.endswith(suffix):
                continue
            full = os.path.join(directory, name)
            if os.path.isfile(full):
                found.append(full)
        return found
