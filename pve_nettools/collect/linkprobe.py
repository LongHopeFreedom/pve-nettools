# [CHANGE] 2026-08-25 新增：admin-down 實體網卡的 Link 探測（使用者回報之缺陷）。
"""把 admin-down 的實體網卡短暫啟用，量到 carrier 之後還原成 down。

## 根因

PVE 預設不會啟用未寫進 `/etc/network/interfaces` 的實體網卡。kernel 在
``!netif_running(dev)`` 時不驅動 PHY，於是 ``/sys/class/net/<nic>/carrier``
讀取回 EINVAL ⇒ ``SysfsReader.carrier()`` 回 None ⇒ 畫面顯示「未知」。

那個「未知」在當下**是誠實的**——kernel 真的不知道。缺陷不在判斷寫錯，而在
  **能力邊界**：盤查工具的用途正是「告訴我哪張卡插了線」，而它對所有沒啟用的卡
  一律回答「不知道」。要拿到答案就只有一條路：先 ``ip link set dev <nic> up``。

## 這是本工具的第一支、也是唯一一支寫入型指令

在此之前全樹 0 處寫入（實測 grep ``ip link set``／``ifup`` 皆無命中）。因此本模組
的每一條邊界都是**主機層級**的風險，不是版面問題：

  1. **admin-up 的卡一律不碰**——它正在承載流量。
  2. **有 master（bond／bridge 成員）的卡不碰**——它的 up/down 屬於 master 的職權，
     從旁邊插手會讓 bond 的 slave 狀態與它自己的認知不一致。
     服役中的 bridge uplink 一定是 admin-up，會先被第 1 條攔下；本條真正守的是
       「已停用但仍歸屬於某個 master」——手動 down 的 bridge port、整組停用的備援
       bond 都屬於這一類。**這兩種情境在 Windows 開發機無法實測**，未驗證。
  3. **admin state 讀不到的卡不碰**——不知道它是不是服役中，保守側是「別動」。
  4. **借用後歸還**：探測完還原成 down；還原失敗必須具名，不得靜默。
  5. **``PROBE_LINK=0`` 可整個關掉**——唯一的寫入路徑必須有逃生門。

## admin state 的判準必須是 flags

兩個看起來能用的判準都是錯的，而且**在多數主機上會給出相同答案**，所以誤用不會
立刻現形：

  - ``carrier is None`` ⇒ 錯。admin-up 但驅動讀不到 carrier 的卡會被判成待探測，
    於是還原階段對一張**服役中的卡**送出 ``ip link set down``——我們自己製造斷線。
  - ``operstate == "down"`` ⇒ 錯。admin-up 但沒插線的卡，operstate **也是** down
    （它反映 RFC 2863 的 OPER 狀態，不是 admin 狀態）。

只有 ``/sys/class/net/<nic>/flags`` 的 ``IFF_UP``（0x1）位元是 admin state 的直接
來源。守這件事的是 `tests/test_linkprobe.py` 的零副作用測試與突變條目 LP-A／LP-G。

## 為什麼要等

``ip link set up`` 回傳時自動協商還沒完成。1G 銅纜通常 1～3 秒，10G 光模組更久。
第一次讀 carrier 就下結論，會把**有接線的卡判成未知**——那正是本模組要修的症狀，
只是換個地方再犯一次。故採輪詢至 ``PROBE_WAIT`` 秒為止。

逾時仍讀不到 ⇒ 回 None（未知），**不得回 False**。等不到答案是「不知道」，
  不是「沒接線」。這與 `collect/__init__.py` 對 ethtool 三態成因的立論相同。
"""

import os

from . import (FAILURE_UNKNOWN, STATUS_OK, STATUS_UNAVAILABLE, default_run,
               run_command)

__all__ = [
    "LinkProber",
    "SKIP_ALREADY_UP",
    "SKIP_DISABLED",
    "SKIP_ENSLAVED",
    "SKIP_UNKNOWN_ADMIN_STATE",
    "probe_enabled",
    "probe_wait_seconds",
]

# 略過探測的成因。具名而不是用 bool，理由與 collect/__init__.py 的 FAILURE_* 相同：
# 呈現層要據此對使用者說不同的話——「已啟用」不必解釋，「被 bond0 接管」要說出是誰
# 接管的，「探測已關閉」則要提示怎麼打開。合成一個 False 就全部說不出來了。
SKIP_ALREADY_UP = "already_up"
SKIP_ENSLAVED = "enslaved"
SKIP_DISABLED = "disabled"
SKIP_UNKNOWN_ADMIN_STATE = "unknown_admin_state"

# 等待自動協商的秒數上限。
#
# 5 秒的取法：1G 銅纜自動協商實務上 1～3 秒，10G 光模組較久但多數在 5 秒內完成。
#   這個數字**沒有客觀正確值**——真機上量到不夠就調 `PROBE_WAIT`，不要改碼。
#   最壞情形是「全部網卡都沒接線」，那時每張卡各等滿 PROBE_WAIT 秒。
PROBE_WAIT_DEFAULT = 5

# 輪詢間隔。不設成環境變數：它與 PROBE_WAIT 是同一件事的兩個旋鈕，兩個都能調
# 只會讓「等多久」變成要兩個值相乘才算得出來，而使用者真正想控制的是總時間。
PROBE_INTERVAL = 0.5

# 這裡列舉的是**關閉**的字面值，不是開啟的。理由：開關的保守側是「不寫入」，
#   而未知字串（打錯的 "flase"、"of"）應該落在哪一側是有語意的——落在「開啟」
#   代表打錯字就會對主機動手。但反過來把未列舉的一律當關閉，又會讓 PROBE_LINK=1
#   以外的任何寫法都靜默失效。取捨結果：明確列舉關閉值，其餘視為開啟，
#   而**真正的保守側由呼叫端的預設值提供**（app 層預設帶不帶這個變數）。
_FALSE_VALUES = frozenset(("0", "no", "off", "false"))


def probe_wait_seconds(env=None):
    """讀取協商等待秒數；空值、零、負數或非數字都回預設值。

    形態刻意與 `collect/__init__.py` 的 `command_timeout()`、`collect/led.py`
      的 `blink_seconds()` 一致——同一個專案裡讀環境變數的三種寫法，會讓下一個人
      以為它們的容錯行為不同。
    """
    env = os.environ if env is None else env
    try:
        value = int((env.get("PROBE_WAIT") or "").strip())
    except (AttributeError, TypeError, ValueError):
        return PROBE_WAIT_DEFAULT
    return value if value > 0 else PROBE_WAIT_DEFAULT


def probe_enabled(env=None):
    """探測開關。未設定時為開啟；明確寫 0／no／off／false 才關閉。"""
    env = os.environ if env is None else env
    try:
        raw = (env.get("PROBE_LINK") or "").strip().lower()
    except (AttributeError, TypeError):
        return True
    return raw not in _FALSE_VALUES if raw else True


class LinkProber:
    """對 admin-down 的實體網卡做「啟用→量測→還原」。

    run_fn／sleep_fn 可注入，讓測試不必真的動網卡、也不必真的等。
    """

    def __init__(self, sysfs_reader, run_fn=None, sleep_fn=None, env=None):
        self.sysfs = sysfs_reader
        self.run_fn = run_fn if run_fn is not None else default_run
        if sleep_fn is not None:
            self.sleep_fn = sleep_fn
        else:
            import time
            self.sleep_fn = time.sleep
        source = os.environ if env is None else env
        self.enabled = probe_enabled(source)
        self.wait_seconds = probe_wait_seconds(source)

    # ── 結果結構 ──────────────────────────────────────────────────────

    @staticmethod
    def _blank(nic):
        """一份「什麼都沒做」的結果。

        每個欄位的預設值都選在**最保守**的一側：link 是 None（不知道）、
          probed 是 False（沒動過）、restored 是 None（沒有還原這件事）。
          任何一條提早 return 的路徑因此都不會意外宣稱自己做了什麼。
        """
        return {
            "nic": nic,
            "probed": False,        # 有沒有真的送出寫入指令
            "link": None,           # True 有接線／False 沒接線／None 不知道
            "restored": None,       # True 還原成功／False 失敗／None 不需還原
            "skipped": None,        # 略過成因，見 SKIP_*
            "master": None,         # 被誰接管（skipped == SKIP_ENSLAVED 時才有值）
            "status": STATUS_OK,
            "failure": None,
            "error": None,
            "restore_error": None,
            "timed_out": False,
            # while_up 回呼自己出的事。具名而不是往外拋：回呼失敗只代表
            # 「順便做的那件事沒做成」，不該讓整批探測中斷、也不該掩蓋已經
            # 取得的 link 證據。
            "while_up_error": None,
        }

    # ── 單張網卡 ──────────────────────────────────────────────────────

    def probe(self, nic, while_up=None):
        """探測單張網卡。回傳結構見 `_blank()`。

        `while_up(nic)` 在**卡還開著、還原之前**被呼叫一次，供呼叫端做那些
        「非得在啟用狀態才問得到」的查詢（ethtool 的速率與 Duplex 就是）。
        略過探測或 up 失敗時不會呼叫——那時卡根本沒開起來。
        """
        result = self._blank(nic)
        if self._skip(nic, result):
            return result
        if not self._bring_up(nic, result):
            # 沒 up 成功就不曾改變狀態 ⇒ 不送 down。restored 保持 None
            #   （「不需要還原」），而不是 False（「還原失敗」）。
            return result

        result["probed"] = True
        # 從這裡到還原之間，這張卡是**開著的**——那是我們對主機造成的改變。
        #   量測與回呼放 try、還原放 finally：回呼是呼叫端注入的碼，它拋例外
        #   而還原被跳過的話，我們就把一張卡永遠留在開啟狀態。拿不到速率是
        #   小事，留一張卡開著不是。
        try:
            link, timed_out = self._await_carrier(nic)
            result["link"] = link
            result["timed_out"] = timed_out
            self._run_while_up(nic, while_up, result)
        finally:
            self._restore(nic, result)
        return result

    def _skip(self, nic, result):
        """四道「不該碰／不想碰」的判斷。回傳 True 表示這張卡不進行探測。

        順序有語意，不得重排：
          admin state 不明 → 已啟用 → 被接管 → 探測關閉。
          前三者是「不該碰」，最後一個是「不想碰」；把關閉排到最前面，會讓
          「已啟用」這個本來就有答案的情形也拿不到 carrier 值。
        """
        admin_up = self.sysfs.admin_up(nic)
        if admin_up is None:
            # flags 讀不到 ⇒ 不知道它是不是服役中 ⇒ 保守側是別動它。
            # carrier 仍照讀：讀得到就是白撿的證據，讀不到也只是維持 None。
            result["skipped"] = SKIP_UNKNOWN_ADMIN_STATE
            result["link"] = self.sysfs.carrier(nic)
            return True

        if admin_up:
            result["skipped"] = SKIP_ALREADY_UP
            result["link"] = self.sysfs.carrier(nic)
            return True

        master = self.sysfs.master(nic)
        if master:
            result["skipped"] = SKIP_ENSLAVED
            result["master"] = master
            return True

        if not self.enabled:
            result["skipped"] = SKIP_DISABLED
            return True

        return False

    # ── 寫入 ──────────────────────────────────────────────────────────

    def _link_set(self, nic, action):
        """送出 ``ip link set dev <nic> <up|down>``。

        `dev` 關鍵字必須保留。kernel 的 `dev_valid_name()` 擋 `/`、空白、
          空字串與長度，**不擋開頭的 `-`** ⇒ 一張名為 `-f` 的介面在
          `ip link set -f up` 裡會被解讀成選項而不是裝置名。少了 `dev`，
          這道指令的正確性就得靠下游的錯誤處理兜住，而不是靠它自己成立。
        argv 以 list 傳入且 `subprocess.run` 不帶 `shell=True` ⇒ 不經 shell，
          介面名不會被當成 shell 語法。這一點不得改成字串拼接。
        """
        return run_command(self.run_fn,
                           ["ip", "link", "set", "dev", nic, action])

    def _bring_up(self, nic, result):
        """啟用網卡。回傳 True 表示卡確實被我們開起來了。

        `ip link set` 成功時**沒有任何輸出** ⇒ run_command 回的是 STATUS_EMPTY
          而不是 STATUS_OK。判成功必須用「不是 unavailable」，寫成
          `== STATUS_OK` 會讓每一次成功的 up 都被當成失敗——而測試若剛好只驗
          「沒有送出 down」就會通過。突變條目 LP-C 打的就是這個。
        """
        up = self._link_set(nic, "up")
        if up["status"] == STATUS_UNAVAILABLE:
            result["status"] = STATUS_UNAVAILABLE
            result["failure"] = up.get("failure") or FAILURE_UNKNOWN
            result["error"] = up.get("error")
            return False
        return True

    def _restore(self, nic, result):
        """把卡關回去。無條件執行：走到這裡卡就已經被我們 up 起來了，
        量到或量不到都一樣要還。"""
        down = self._link_set(nic, "down")
        if down["status"] == STATUS_UNAVAILABLE:
            result["restored"] = False
            result["restore_error"] = down.get("error")
        else:
            result["restored"] = True

    # ── 量測 ──────────────────────────────────────────────────────────

    def _await_carrier(self, nic):
        """輪詢 carrier 直到有值或逾時。回傳 (link, timed_out)。"""
        waited = 0.0
        while True:
            link = self.sysfs.carrier(nic)
            if link is not None:
                return link, False
            if waited >= self.wait_seconds:
                return None, True
            self.sleep_fn(PROBE_INTERVAL)
            waited += PROBE_INTERVAL

    @staticmethod
    def _run_while_up(nic, while_up, result):
        """執行「趁卡還開著」的回呼，並吞下它自己的例外。"""
        if while_up is None:
            return
        try:
            while_up(nic)
        except Exception as exc:      # noqa: BLE001 —— 見上方說明
            # 不攔 BaseException：KeyboardInterrupt／SystemExit 要能往外傳，
            #   使用者按 Ctrl-C 時 probe() 的 finally 仍會把卡關回去。
            result["while_up_error"] = str(exc)

    # ── 批次 ──────────────────────────────────────────────────────────

    def probe_all(self, nics, while_up=None):
        """對多張網卡依序探測，回傳 {nic: result}。

        刻意**序列**而不併發：併發 up 多張卡會讓交換器同時看到數個 port 上線，
          在有 STP 的環境下是一次不必要的拓撲擾動。慢一點的代價由 PROBE_WAIT 控制。
        """
        return dict((nic, self.probe(nic, while_up=while_up)) for nic in nics)
