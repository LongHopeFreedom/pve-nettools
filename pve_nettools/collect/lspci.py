# [CHANGE] 2026-10-06 v03.018.000 新增：以 lspci 取實體網卡的型號。
"""讀 ``lspci -vmm -D -s <PCI 位址>``，解析廠商／型號並組成顯示字串。

這個模組存在的理由：選單第 1 項只列到「驅動」與「PCI 位址」，使用者仍得自己去
  `lspci` 對照這張卡到底是什麼。型號資料的來源只有 lspci（pci.ids），ethtool 給不出。

外部指令的執行、逾時與失敗分類一律走 `collect/__init__.py` 的 `run_command()`，
  不另立一套。
"""

import re

from . import default_run, parsed_result, run_command

# 例：0000:af:00.0。網域位數不固定（VMD 的網域可多於 4 位），故 {4,8}。
PCI_ADDRESS_RE = re.compile(
    r"^[0-9a-f]{4,8}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]$", re.IGNORECASE)

# lspci 對 pci.ids 查不到子系統名稱時的佔位字，例：`Device 001f`。
# 只認樣本（一台真機，2026-10-06）裡實際出現的這一種形態；其他形態原樣顯示。
_PLACEHOLDER_RE = re.compile(r"^Device [0-9a-f]{4}$")

# lspci 鍵名 → 本模組欄位名。
_FIELDS = {
    "Vendor": "vendor",
    "Device": "device",
    "SVendor": "svendor",
    "SDevice": "sdevice",
}


def valid_pci_address(value):
    return isinstance(value, str) and PCI_ADDRESS_RE.match(value) is not None


def parse_lspci(text):
    """解析 ``lspci -vmm`` 輸出的**第一筆**記錄；認不出任何廠商／型號時回 {}。

    以第一個冒號切開、兩側去空白：真機輸出是 `鍵:<TAB>值`，終端機貼上後 TAB 可能
      變成空格，兩種都要吃得下。`Slot:` 的值本身含冒號，所以只能切第一個。
    記錄以空行分隔；`-s` 指定單一位址時只會有一筆，多筆時只取第一筆，
      同鍵重複時第一個贏。
    """
    fields = {}
    started = False
    for line in (text or "").splitlines():
        if not line.strip():
            if started:
                break
            continue
        started = True
        name, sep, value = line.partition(":")
        if not sep:
            continue
        key = _FIELDS.get(name.strip())
        value = value.strip()
        if key is not None and value:
            fields.setdefault(key, value)
    if "vendor" not in fields and "device" not in fields:
        return {}
    return fields


def format_model(fields):
    """`<Vendor> <Device>`；子系統名稱有意義時後面加全形括號 `（<SVendor> <SDevice>）`。

    回 None 表示連廠商與型號都沒有。
    """
    main = " ".join(part for part in (fields.get("vendor"), fields.get("device"))
                    if part)
    if not main:
        return None
    sdevice = fields.get("sdevice")
    if sdevice and _PLACEHOLDER_RE.match(sdevice) is None:
        sub = " ".join(part for part in (fields.get("svendor"), sdevice) if part)
        return "%s（%s）" % (main, sub)
    return main


class LspciReader(object):
    """執行 lspci；run_fn 可替換，以位址為鍵快取。"""

    def __init__(self, run_fn=None):
        self.run_fn = run_fn if run_fn is not None else default_run
        self._cache = {}

    def model(self, address):
        """回 `parsed_result()` 形態：status／data／error／failure。

        必須先以 `valid_pci_address()` 驗過；非 PCI 位址一律拋 ValueError，
        避免以 `-` 開頭的字串被 lspci 讀成選項。
        """
        if not valid_pci_address(address):
            raise ValueError("非 PCI 位址：%r" % (address,))
        if address not in self._cache:
            command = run_command(
                self.run_fn, ["lspci", "-vmm", "-D", "-s", address])
            self._cache[address] = parsed_result(command, parse_lspci)
        return self._cache[address]
