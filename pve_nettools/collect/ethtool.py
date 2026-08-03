# [CHANGE] 2026-07-31 新增：可注入、可快取的 ethtool 資料讀取與媒介判定。
"""讀取 ethtool 資訊，並以可稽核的優先序判定網路媒介。

★ 這個模組存在的主要理由是媒介判定不能掃整份 EEPROM dump。

舊版只要在任意位置看到 ``LC``、``SC`` 等片段就判成光纖；但 Transceiver 本身
就含有 ``sc``，DAC 也可能宣告 optical diagnostics，因而幾乎所有模組都會被誤判。
這裡只讀有語意的欄位，並讓 RJ45／BASE-T 的規則先於線長，避免 1000BASE-T SFP
因 Length (Copper) 為 100m 而落入 DAC。
"""

import re

# [CHANGE] 2026-07-31 狀態常數與指令執行慣例移到 collect/__init__.py 共用（待辦 #3
#          的 bridge.py 要做同一件事）。這裡照原名 re-export，呼叫端與既有測試
#          仍可從 collect.ethtool 匯入。
from . import (
    STATUS_EMPTY,
    STATUS_OK,
    STATUS_UNAVAILABLE,
    default_run,
    parsed_result,
    run_command,
)

MEDIUM_RJ45 = "rj45"
MEDIUM_BACKPLANE = "backplane"
MEDIUM_AUI = "aui"
MEDIUM_MII = "mii"
MEDIUM_DAC = "dac"
MEDIUM_AOC = "aoc"
MEDIUM_FIBER = "fiber"


class EthtoolReader:
    """讀 ethtool；run_fn 可替換，避免測試依賴主機是否安裝 ethtool。"""

    def __init__(self, run_fn=None):
        self.run_fn = run_fn if run_fn is not None else default_run
        self._cache = {}

    # ── 指令與快取 ────────────────────────────────────────────────────

    def _command(self, nic, option=None):
        key = (nic, option)
        if key in self._cache:
            return self._cache[key]

        argv = ["ethtool"]
        if option is not None:
            argv.append(option)
        argv.append(nic)
        result = run_command(self.run_fn, argv)

        self._cache[key] = result
        return result

    @staticmethod
    def _parsed(command, parser):
        return parsed_result(command, parser)

    # ── 四類 ethtool 資料 ─────────────────────────────────────────────

    def link_info(self, nic):
        """保留未知值為 None；不能把「沒驗到 link」說成「確定 link down」。"""
        return self._parsed(self._command(nic), _parse_link)

    def driver_info(self, nic):
        return self._parsed(self._command(nic, "-i"), _parse_driver)

    def module_eeprom(self, nic):
        """EEPROM 無模組或權限不足很常見，故以 unavailable 回報而不拋例外。"""
        return self._parsed(self._command(nic, "-m"), _parse_eeprom)

    def statistics(self, nic):
        return self._parsed(self._command(nic, "-S"), _parse_statistics)

    # ── 媒介判定 ──────────────────────────────────────────────────────

    def medium(self, nic):
        """依固定優先序判定；順序本身是修正的一部分，不可任意重排。"""
        link = self.link_info(nic)
        port = ""
        if link["status"] == STATUS_OK:
            port = link["data"].get("port") or ""

        # Port 已明示雙絞線時不碰 EEPROM；有些 NIC 讀 EEPROM 會慢或須額外權限。
        if port.lower() == "twisted pair":
            return _medium_result(STATUS_OK, MEDIUM_RJ45, "Port: Twisted Pair")

        for word, medium_name in (
                ("backplane", MEDIUM_BACKPLANE),
                ("aui", MEDIUM_AUI),
                ("mii", MEDIUM_MII)):
            if re.search(r"\b%s\b" % re.escape(word), port, re.IGNORECASE):
                return _medium_result(STATUS_OK, medium_name, "Port: %s" % port)

        module = self.module_eeprom(nic)
        if module["status"] != STATUS_OK:
            return _medium_result(
                module["status"], None, None, error=module["error"])

        fields = module["data"]
        connector = fields.get("connector", "")
        transceiver_type = fields.get("transceiver_type", "")
        cable_technology = fields.get("cable_technology", "")

        # MUST 在 Length (Copper) 前：1000BASE-T SFP 的銅線長度可達 100m。
        if (_has_anchored_word(connector, "RJ45")
                or re.search(r"BASE[\s-]*T\b", transceiver_type, re.IGNORECASE)):
            evidence = "Connector: %s" % connector
            if not _has_anchored_word(connector, "RJ45"):
                evidence = "Transceiver type: %s" % transceiver_type
            return _medium_result(STATUS_OK, MEDIUM_RJ45, evidence)

        lengths = _module_lengths(fields)
        fiber_lengths = [
            value for name, value in lengths.items()
            if name != "copper"
        ]
        if any(value > 0 for value in fiber_lengths):
            return _medium_result(STATUS_OK, MEDIUM_FIBER, "光纖線長 > 0")
        if (lengths.get("copper", 0) > 0
                and fiber_lengths
                and all(value == 0 for value in fiber_lengths)):
            if _is_active_cable(cable_technology, transceiver_type):
                return _medium_result(STATUS_OK, MEDIUM_AOC, "Length (Copper) > 0")
            return _medium_result(STATUS_OK, MEDIUM_DAC, "Length (Copper) > 0")

        # 只能比對接頭與線纜技術欄位；絕不能退回掃描整份 EEPROM dump。
        if _is_active_cable(cable_technology, transceiver_type):
            return _medium_result(STATUS_OK, MEDIUM_AOC, "線纜技術: Active Cable")
        if re.search(r"\b(?:PASSIVE\s+COPPER|COPPER\s+PIGTAIL|DAC)\b",
                     "%s %s" % (connector, cable_technology), re.IGNORECASE):
            return _medium_result(STATUS_OK, MEDIUM_DAC, "接頭／線纜技術: Copper")
        if re.search(r"\b(?:LC|SC|MPO|MTP)\b", connector, re.IGNORECASE):
            return _medium_result(STATUS_OK, MEDIUM_FIBER, "Connector: %s" % connector)

        return _medium_result(STATUS_EMPTY, None, None)


def _medium_result(status, medium, evidence, error=None):
    return {
        "status": status,
        "medium": medium,
        "evidence": evidence,
        "error": error,
    }


def _has_anchored_word(value, word):
    return re.search(r"\b%s\b" % re.escape(word), value, re.IGNORECASE) is not None


def _split_field(line):
    match = re.match(r"^\s*([^:]+?)\s*:\s*(.*?)\s*$", line)
    if match is None:
        return None, None
    return match.group(1), match.group(2)


def _parse_link(text):
    fields = {}
    modes_key = None
    mode_names = {
        "Supported link modes": "supported_modes",
        "Advertised link modes": "advertised_modes",
    }
    scalar_names = {
        "Speed": "speed",
        "Duplex": "duplex",
        "Auto-negotiation": "auto_negotiation",
        "Port": "port",
    }
    for line in text.splitlines():
        name, value = _split_field(line)
        if name in mode_names:
            modes_key = mode_names[name]
            fields[modes_key] = value.split()
        elif name in scalar_names:
            modes_key = None
            fields[scalar_names[name]] = value or None
        elif name == "Link detected":
            modes_key = None
            lowered = value.lower()
            fields["link_detected"] = (
                True if lowered == "yes" else False if lowered == "no" else None)
        elif modes_key is not None and name is None and line.strip():
            fields[modes_key].extend(line.split())
        else:
            modes_key = None
    return fields


def _parse_driver(text):
    wanted = {
        "driver": "driver",
        "version": "driver_version",
        "firmware-version": "firmware_version",
        "bus-info": "bus_info",
    }
    fields = {}
    for line in text.splitlines():
        name, value = _split_field(line)
        if name in wanted:
            fields[wanted[name]] = value or None
    return fields


def _normalise_field_name(name):
    return re.sub(r"\s+", " ", name.strip().lower())


def _parse_eeprom(text):
    fields = {}
    for line in text.splitlines():
        name, value = _split_field(line)
        if name is None:
            continue
        normal = _normalise_field_name(name)
        # [CHANGE] 2026-08-02 待辦 #17：保留全部原始欄位，供 SFP/QSFP 模組明細
        # 區段使用。此前這個解析器**只留下媒介判定要用的四類**，其餘（廠商、
        # 料號、序號、溫度、電壓、光功率）在這裡就被丟掉了——交接檔記載第 3 項
        # 「有供料只缺 key」，實際上供料也不完整。
        # ★ setdefault 而非直接賦值：bash 的 field_value 以 awk 的 exit 取**第一個**
        #   匹配，而 QSFP 的每個 lane 各有一行同名欄位（如 4 行 Laser output power）。
        #   直接賦值會取到最後一個 lane，與 bash 不等價且沒有任何徵兆。
        fields.setdefault(normal, value)
        if normal == "connector":
            fields["connector"] = value
        elif normal == "transceiver type":
            previous = fields.get("transceiver_type")
            fields["transceiver_type"] = (
                previous + " " + value if previous else value)
        elif normal in ("cable technology", "device technology"):
            fields["cable_technology"] = value
        elif normal.startswith("length ("):
            fields["length:" + normal] = value
    return fields


def _parse_length(value):
    match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", value or "")
    if match is None:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _module_lengths(fields):
    lengths = {}
    for key, value in fields.items():
        if not key.startswith("length:"):
            continue
        name = key[len("length:"):]
        number = _parse_length(value)
        if number is None:
            continue
        if "copper" in name:
            lengths["copper"] = number
        else:
            lengths[name] = number
    return lengths


def _is_active_cable(cable_technology, transceiver_type):
    selected_fields = "%s %s" % (cable_technology, transceiver_type)
    return re.search(
        r"\b(?:ACTIVE\s+(?:COPPER\s+)?CABLE|AOC)\b",
        selected_fields,
        re.IGNORECASE,
    ) is not None


def _parse_statistics(text):
    counters = {}
    for line in text.splitlines():
        name, value = _split_field(line)
        if name is None or name.lower() == "nic statistics":
            continue
        try:
            counters[name.strip()] = int(value, 0)
        except (TypeError, ValueError):
            counters[name.strip()] = value
    return counters
