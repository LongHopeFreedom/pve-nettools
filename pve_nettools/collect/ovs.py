# [CHANGE] 2026-08-02 新增：Open vSwitch 指令解析、探測三態與 argv 快取。
"""收集 Open vSwitch Bridge、Port 與 Bond 資料。"""

from . import (FAILURE_NOT_EXECUTABLE, STATUS_EMPTY, STATUS_OK,
               STATUS_UNAVAILABLE, default_run, run_command)
from .sysfs import _natural_key


def parse_names(text):
    """解析每行一個名稱的輸出，忽略空白行。"""
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def parse_bonds(text):
    """跳過 ovs-appctl bond/list 表頭，取每個資料列第一欄。"""
    lines = (text or "").splitlines()
    return [line.split()[0] for line in lines[1:] if line.split()]


def parse_single_value(text):
    """把 OVS 的空集合與空輸出保留為供料層的 None。"""
    value = (text or "").replace("\r", "").replace("\n", "").strip()
    return None if value in ("", "[]") else value


class OvsReader(object):
    """執行 OVS 指令；同一 argv 永遠只執行一次。"""

    def __init__(self, run_fn=None):
        self.run_fn = run_fn if run_fn is not None else default_run
        self._cache = {}
        self._probe = None

    def _command(self, argv):
        key = tuple(argv)
        if key not in self._cache:
            self._cache[key] = run_command(self.run_fn, argv)
        return self._cache[key]

    def probe(self):
        if self._probe is not None:
            return self._probe
        shown = self._command(["ovs-vsctl", "show"])
        if shown["status"] == STATUS_UNAVAILABLE:
            # [CHANGE] 2026-08-02 改以 run_command 的 failure 欄判定成因。
            #
            # ★ 原實作比對 error 的字串內容（"no such file" / "not found" / …）。
            #   實測那道判準**鑑別力為零**：ovsdb 停掉時 ovs-vsctl 的原文是
            #   「database connection failed (No such file or directory)」，
            #   同樣含有 "no such file" ⇒ 兩種情形都被判成「沒安裝」，使用者
            #   會被叫去 apt install 一個已經裝好的套件，而且裝完毫無變化。
            # ★ 根因在**我（委派方）的規格**：規格寫了「要分辨三態」卻沒有指定
            #   分辨的依據，而當時的 run_command 也不提供結構上的區分。受託方
            #   是在沒有可用性質的前提下，合理地退而求其次去比對訊息。
            reason = ("not_installed"
                      if shown.get("failure") == FAILURE_NOT_EXECUTABLE
                      else "ovsdb_unreachable")
            self._probe = {
                "status": STATUS_UNAVAILABLE, "reason": reason,
                "data": None, "error": shown["error"],
            }
            return self._probe

        bridges = self._command(["ovs-vsctl", "list-br"])
        if bridges["status"] == STATUS_UNAVAILABLE:
            self._probe = {
                "status": STATUS_UNAVAILABLE, "reason": "ovsdb_unreachable",
                "data": None, "error": bridges["error"],
            }
        else:
            names = sorted(parse_names(bridges["stdout"]), key=_natural_key)
            self._probe = {
                "status": STATUS_OK if names else STATUS_EMPTY,
                "reason": None if names else "no_bridges",
                "data": names, "error": None,
            }
        return self._probe

    def bridges(self):
        return self.probe()["data"] or []

    def ports(self, bridge):
        result = self._command(["ovs-vsctl", "list-ports", bridge])
        if result["status"] == STATUS_UNAVAILABLE:
            return []
        return sorted(parse_names(result["stdout"]), key=_natural_key)

    def port_info(self, port):
        tag = self._command(["ovs-vsctl", "get", "port", port, "tag"])
        mode = self._command(["ovs-vsctl", "get", "port", port, "vlan_mode"])
        ifaces = self._command(["ovs-vsctl", "list-ifaces", port])
        iface_names = None
        if ifaces["status"] != STATUS_UNAVAILABLE:
            names = parse_names(ifaces["stdout"])
            iface_names = ",".join(names) if names else port
        return {
            "tag": None if tag["status"] == STATUS_UNAVAILABLE
            else parse_single_value(tag["stdout"]),
            "vlan_mode": None if mode["status"] == STATUS_UNAVAILABLE
            else parse_single_value(mode["stdout"]),
            "ifaces": iface_names,
        }

    def bonds(self):
        result = self._command(["ovs-appctl", "bond/list"])
        if result["status"] == STATUS_UNAVAILABLE:
            return []
        return parse_bonds(result["stdout"])

    def bond_show(self, name):
        result = self._command(["ovs-appctl", "bond/show", name])
        if result["status"] == STATUS_UNAVAILABLE:
            return None
        return result["stdout"] or None
