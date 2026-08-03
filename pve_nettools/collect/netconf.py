# [CHANGE] 2026-07-31 新增：解析持久化網路設定與來源檔（待辦 #5）。
"""讀取並解析 ifupdown 的 ``/etc/network/interfaces``。

解析器刻意保留 option 的順序與重複項目，也分開記錄 ``auto`` 與
``allow-hotplug``，讓 render 層之後能拿來和執行中狀態對帳。

介面註解採兩種常見形態：緊接 top-level 指令前的註解歸給下一個 stanza；
stanza 後、接著遇到空白或 option 的註解歸給前一個 stanza。PVE Web UI 的
Comment 會落在 stanza 後方，此為依 PVE Web UI 慣例的判定，真機驗證前為假設。
"""

import glob
import os
import re

from . import STATUS_EMPTY, STATUS_OK, STATUS_UNAVAILABLE

DEFAULT_CONF_FILE = "/etc/network/interfaces"
DEFAULT_CONF_DIR = "/etc/network/interfaces.d"

_TOP_LEVEL = frozenset((
    "auto", "iface", "source", "source-directory", "mapping",
))
_SOURCE_DIRECTORY_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def join_continuations(text):
    """把反斜線續行合併成邏輯行，並保留沒有續行的原始行內容。"""
    logical = []
    pending = None
    for physical in (text or "").splitlines():
        if pending is None:
            current = physical
        else:
            current = pending + physical.lstrip()

        trimmed = current.rstrip()
        if trimmed.endswith("\\"):
            pending = trimmed[:-1].rstrip() + " "
        else:
            logical.append(current)
            pending = None

    if pending is not None:
        logical.append(pending.rstrip())
    return logical


def _directive(line):
    """取出一行的第一個詞；空白行回空字串。"""
    stripped = (line or "").strip()
    return stripped.split(None, 1)[0] if stripped else ""


def _is_top_level(line):
    """判斷是否為會切換解析上下文的 top-level 指令。"""
    word = _directive(line)
    return word in _TOP_LEVEL or word.startswith("allow-")


def classify_line(line):
    """把邏輯行分成 blank、comment、stanza 或 option。"""
    stripped = (line or "").strip()
    if not stripped:
        return "blank"
    if stripped.startswith("#"):
        return "comment"
    if _is_top_level(line):
        return "stanza"
    return "option"


def parse_auto(line):
    """解析 auto 行，回傳該行列出的所有介面名稱。"""
    parts = (line or "").strip().split()
    if not parts or parts[0] != "auto":
        return []
    return parts[1:]


def parse_allow(line):
    """解析 allow-<類型> 行；不是 allow 行時回傳 ``(None, [])``。"""
    parts = (line or "").strip().split()
    if not parts or not parts[0].startswith("allow-"):
        return (None, [])
    kind = parts[0][len("allow-"):]
    if not kind:
        return (None, [])
    return (kind, parts[1:])


def parse_iface_head(line):
    """解析 iface 表頭；缺少 family 或 method 時以 None 表示。"""
    parts = (line or "").strip().split()
    if len(parts) < 2 or parts[0] != "iface":
        return None
    return {
        "name": parts[1],
        "family": parts[2] if len(parts) > 2 else None,
        "method": parts[3] if len(parts) > 3 else None,
    }


def parse_option(line):
    """把 option 拆成 ``(名稱, 完整值)``；行內的 # 是值的一部分。"""
    stripped = (line or "").strip()
    if not stripped:
        return (None, "")
    parts = stripped.split(None, 1)
    return (parts[0], parts[1] if len(parts) > 1 else "")


def parse_source(line):
    """解析 source 或 source-directory，其他行回傳 ``(None, None)``。"""
    stripped = (line or "").strip()
    parts = stripped.split(None, 1)
    if len(parts) != 2 or parts[0] not in ("source", "source-directory"):
        return (None, None)
    value = parts[1].strip()
    return (parts[0], value) if value else (None, None)


def _comment_text(lines):
    """去掉註解符號與其後空白，多行以換行串接。"""
    text = []
    for line in lines:
        stripped = line.lstrip()
        text.append(stripped[1:].strip())
    return "\n".join(text)


def _append_comment(stanza, comment):
    """在同一 stanza 已有註解時保留兩段的先後順序。"""
    if not comment:
        return
    if stanza["comment"]:
        stanza["comment"] += "\n" + comment
    else:
        stanza["comment"] = comment


def _ordered_names(lines):
    """從邏輯行收集 auto 與 hotplug，保留順序並去重。"""
    auto = []
    hotplug = []
    for line in lines:
        names = parse_auto(line)
        for name in names:
            if name not in auto:
                auto.append(name)
        kind, names = parse_allow(line)
        if kind == "hotplug":
            for name in names:
                if name not in hotplug:
                    hotplug.append(name)
    return auto, hotplug


def parse_interfaces(text, origin):
    """解析單一 interfaces 檔，回傳 stanza 清單。"""
    lines = join_continuations(text)
    auto, hotplug = _ordered_names(lines)
    stanzas = []
    current = None
    pending_comment = None
    index = 0

    while index < len(lines):
        line = lines[index]
        kind = classify_line(line)

        if kind == "comment":
            block = []
            while index < len(lines) and classify_line(lines[index]) == "comment":
                block.append(lines[index])
                index += 1
            comment = _comment_text(block)

            # 空白會結束註解區塊；只有緊接 top-level 指令才算前置註解。
            if index < len(lines) and classify_line(lines[index]) == "stanza":
                pending_comment = comment
            elif current is not None:
                _append_comment(current, comment)
            continue

        if kind == "blank":
            pending_comment = None
            index += 1
            continue

        if kind == "stanza":
            word = _directive(line)
            if word == "iface":
                head = parse_iface_head(line)
                if head is not None:
                    current = {
                        "name": head["name"],
                        "family": head["family"],
                        "method": head["method"],
                        "options": [],
                        "comment": None,
                        "auto": head["name"] in auto,
                        "hotplug": head["name"] in hotplug,
                        "origin": origin,
                    }
                    if pending_comment:
                        _append_comment(current, pending_comment)
                    pending_comment = None
                    stanzas.append(current)
            elif word in ("source", "source-directory", "mapping"):
                current = None
                pending_comment = None
            # auto 與 allow-* 不會關閉現有 stanza；它們也可能承接前置註解。
            index += 1
            continue

        if current is not None:
            option = parse_option(line)
            if option[0] is not None:
                current["options"].append(option)
        pending_comment = None
        index += 1

    return stanzas


def _source_lines(text):
    """列出一份檔案內的 source 指令，供 Reader 遞迴處理。"""
    found = []
    for line in join_continuations(text):
        directive = parse_source(line)
        if directive[0] is not None:
            found.append(directive)
    return found


def _extend_unique(target, values):
    """依出現順序把尚未存在的值加入清單。"""
    for value in values:
        if value not in target:
            target.append(value)


class NetconfReader(object):
    """讀 interfaces 主檔與其 source 樹；路徑可替換以供離線測試。"""

    def __init__(self, conf_file=None, conf_dir=None):
        self.conf_file = (conf_file or os.environ.get("NET_CONF_FILE")
                          or DEFAULT_CONF_FILE)
        self.conf_dir = (conf_dir or os.environ.get("NET_CONF_DIR")
                         or DEFAULT_CONF_DIR)

    def read_conf(self, path):
        """以 UTF-8 讀設定；壞位元組以替代字元保留其餘盤查資料。"""
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()

    def pending_change(self):
        """主設定旁是否存在尚未套用的 .new 檔。"""
        return os.path.exists(self.conf_file + ".new")

    def _mapped_path(self, value, origin):
        """解析來源路徑；測試覆寫 conf_dir 時也映射標準 interfaces.d 路徑。"""
        normalized = value.replace("/", os.sep)
        default_dir = DEFAULT_CONF_DIR.replace("/", os.sep)
        if self.conf_dir != DEFAULT_CONF_DIR:
            if normalized == default_dir:
                return self.conf_dir
            prefix = default_dir + os.sep
            if normalized.startswith(prefix):
                return os.path.join(self.conf_dir, normalized[len(prefix):])
        if os.path.isabs(normalized):
            return normalized
        return os.path.join(os.path.dirname(origin), normalized)

    def _source_paths(self, directive, value, origin):
        """展開一條 source 指令；不存在的 glob 或目錄視為空集合。"""
        target = self._mapped_path(value, origin)
        if directive == "source":
            return [path for path in sorted(glob.glob(target)) if os.path.isfile(path)]

        try:
            names = sorted(os.listdir(target))
        except OSError:
            return []
        paths = []
        for name in names:
            if not _SOURCE_DIRECTORY_NAME_RE.match(name):
                continue
            path = os.path.join(target, name)
            if os.path.isfile(path):
                paths.append(path)
        return paths

    def read(self):
        """讀完整來源樹，回傳三態、stanza、啟動旗標與讀取缺口。"""
        interfaces = []
        auto = []
        hotplug = []
        sources = []
        unreadable = []
        visited = set()

        def visit(path, is_main=False):
            canonical = os.path.normcase(os.path.abspath(path))
            if canonical in visited:
                return None
            visited.add(canonical)
            sources.append(path)

            try:
                text = self.read_conf(path)
            except OSError as exc:
                unreadable.append(path)
                return exc

            lines = join_continuations(text)
            file_auto, file_hotplug = _ordered_names(lines)
            _extend_unique(auto, file_auto)
            _extend_unique(hotplug, file_hotplug)
            interfaces.extend(parse_interfaces(text, path))

            for directive, value in _source_lines(text):
                for child in self._source_paths(directive, value, path):
                    visit(child)
            return None

        main_error = visit(self.conf_file, is_main=True)
        pending = self.pending_change()
        if main_error is not None:
            return {
                "status": STATUS_UNAVAILABLE,
                "interfaces": [],
                "auto": [],
                "hotplug": [],
                "sources": sources,
                "unreadable": unreadable,
                "pending_change": pending,
                "error": "%s：%s" % (self.conf_file, main_error),
            }

        auto_set = set(auto)
        hotplug_set = set(hotplug)
        for stanza in interfaces:
            stanza["auto"] = stanza["name"] in auto_set
            stanza["hotplug"] = stanza["name"] in hotplug_set

        return {
            "status": STATUS_OK if interfaces else STATUS_EMPTY,
            "interfaces": interfaces,
            "auto": auto,
            "hotplug": hotplug,
            "sources": sources,
            "unreadable": unreadable,
            "pending_change": pending,
            "error": None,
        }

    def autostart(self):
        """回傳 render 層可直接使用的 auto 與 hotplug 對帳原語。"""
        result = self.read()
        return {"auto": result["auto"], "hotplug": result["hotplug"]}

    def comments(self):
        """回傳介面名稱到註解的對照；同名 stanza 以後出現的註解為準。"""
        table = {}
        for stanza in self.read()["interfaces"]:
            if stanza["comment"] is not None:
                table[stanza["name"]] = stanza["comment"]
        return table
