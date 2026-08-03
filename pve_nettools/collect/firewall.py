# [CHANGE] 2026-08-01 新增：解析並收集 PVE 防火牆設定（待辦 #7）。
"""從 PVE 設定樹讀取 cluster、guest 與 host 防火牆設定。

本模組只解析結構，不驗證規則語意：不檢查 ``SSH(ACCEPT)`` 等 macro 是否存在，
也不檢查 ``-i net0`` 指定的介面是否存在。

本模組不涵蓋 SDN／vnet 層的防火牆設定（例如 ``/etc/pve/sdn``），只讀取
``firewall/cluster.fw``、數字 VMID 的 guest ``.fw`` 與 ``local/host.fw``。

``[group ...]`` 只在 cluster.fw 有語意，但共用解析器不強制檢查它出現在哪一種
檔案裡；來源與語意的搭配由呼叫端判斷。
"""

import os
import re

from . import (STATUS_EMPTY, STATUS_OK, STATUS_UNAVAILABLE, default_run,
               run_command)
# [CHANGE] 2026-08-02 濾行規則移到 textconf，本檔改為取用。第二個使用者（選單
#          15 要印 .fw 原文）出現的當下就抽成一份——兩份濾行規則漂移不會有任何
#          測試變紅，這是本套件既定立場（collect/__init__.py 的 docstring）。
from .textconf import meaningful_lines as _meaningful_lines

DEFAULT_ROOT = "/etc/pve"
FIREWALL_DIR = "firewall"
CLUSTER_FILE = "cluster.fw"
HOST_FILE = "host.fw"
LOCAL_DIR = "local"
FW_SUFFIX = ".fw"

SECTION_OPTIONS = "options"
SECTION_RULES = "rules"
SECTION_IPSET = "ipset"
SECTION_ALIASES = "aliases"
SECTION_GROUP = "group"

_SECTION_RE = re.compile(r"^\[([^\]\s]+)(?:\s+([^\]]+?))?\]$")
_DIGITS_RE = re.compile(r"^\d+$")


def parse_fw(text):
    """把一份 .fw 的內容解析成結構。純函式，不碰檔案系統。"""
    options = {}
    sections = []
    active_kind = None
    current = None

    for line in _meaningful_lines(text):
        matched = _SECTION_RE.match(line.strip())
        if matched is not None:
            active_kind = matched.group(1).lower()
            name = matched.group(2)
            if name is not None:
                name = name.strip()
            if active_kind == SECTION_OPTIONS:
                current = None
            else:
                current = {
                    "kind": active_kind,
                    "name": name,
                    "entries": [],
                }
                sections.append(current)
            continue

        if active_kind == SECTION_OPTIONS:
            if ":" in line:
                key, value = line.split(":", 1)
                options[key.strip().lower()] = value.strip()
            continue

        if current is None:
            active_kind = ""
            current = {"kind": "", "name": None, "entries": []}
            sections.append(current)

        disabled = (current["kind"] in (SECTION_RULES, SECTION_GROUP) and
                    line.startswith("|"))
        current["entries"].append({
            "text": line[1:] if disabled else line,
            "disabled": disabled,
        })

    return {"options": options, "sections": sections}


def _enabled(result):
    """依檔案狀態與 OPTIONS enable 判斷該層是否啟用。"""
    if result["status"] != STATUS_OK:
        return False
    value = result["data"]["options"].get("enable")
    return value is not None and value.strip() == "1"


class FirewallReader(object):
    """讀取可替換根目錄的 PVE 防火牆設定。"""

    def __init__(self, root=None, run_fn=None):
        self.root = root or os.environ.get("PVE_CONF_ROOT") or DEFAULT_ROOT
        self.run_fn = run_fn or default_run

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    def read_file(self, path):
        """讀取並解析單一 .fw，明確區分 empty 與 unavailable。"""
        if not os.path.isfile(path):
            return {
                "status": STATUS_UNAVAILABLE,
                "data": None,
                "error": "%s 不存在或不是一般檔案" % path,
            }
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError as exc:
            return {
                "status": STATUS_UNAVAILABLE,
                "data": None,
                "error": "%s：%s" % (path, exc),
            }

        data = parse_fw(text)
        return {
            "status": STATUS_OK if _meaningful_lines(text) else STATUS_EMPTY,
            "data": data,
            "error": None,
        }

    def _layer(self, path):
        result = self.read_file(path)
        result["path"] = path
        result["enabled"] = _enabled(result)
        return result

    def cluster(self):
        return self._layer(self.path(FIREWALL_DIR, CLUSTER_FILE))

    def host(self):
        return self._layer(self.path(LOCAL_DIR, HOST_FILE))

    def guest_ids(self):
        directory = self.path(FIREWALL_DIR)
        try:
            entries = os.listdir(directory)
        except OSError:
            return []

        found = []
        for entry in entries:
            if not entry.endswith(FW_SUFFIX):
                continue
            vmid = entry[:-len(FW_SUFFIX)]
            if not _DIGITS_RE.match(vmid):
                continue
            if not os.path.isfile(os.path.join(directory, entry)):
                continue
            found.append(vmid)
        return sorted(found, key=int)

    def guest(self, vmid):
        return self._layer(self.path(FIREWALL_DIR,
                                     "%s%s" % (vmid, FW_SUFFIX)))

    def guests(self):
        return [(vmid, self.guest(vmid)) for vmid in self.guest_ids()]

    def status(self):
        result = run_command(self.run_fn, ["pve-firewall", "status"])
        state = None
        if result["stdout"] is not None:
            for line in result["stdout"].splitlines():
                matched = re.match(r"^Status:\s*(.*)$", line)
                if matched is not None:
                    state = matched.group(1).strip()
                    break
        result["state"] = state
        return result

    def read(self):
        cluster = self.cluster()
        host = self.host()
        guests = self.guests()
        fw_status = self.status()
        warn = (not cluster["enabled"] and
                any(item["enabled"] for _vmid, item in guests))
        return {
            "status": (STATUS_OK if os.path.isdir(
                self.path(FIREWALL_DIR)) else STATUS_UNAVAILABLE),
            "cluster": cluster,
            "host": host,
            "guests": guests,
            "fw_status": fw_status,
            "warn": warn,
        }
