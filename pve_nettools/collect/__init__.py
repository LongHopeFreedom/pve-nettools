# [CHANGE] 2026-07-31 新增：collect 子套件共用的狀態常數與外部指令執行慣例（待辦 #3）。
"""collect 子套件的共用基礎。

★ 這裡的東西原本只存在於 ethtool.py。bridge.py 要做的是同一件事：跑一個外部
  指令、把結果歸類成「有資料／沒資料／取不到」三態，再交給解析器。

  兩份複本一旦漂移不會有任何測試變紅——狀態是靠字面字串比對的，某一邊把
  "unavailable" 寫成 "unavailble"，呼叫端只會靜默走進另一條分支。所以在第二個
  使用者出現的當下就抽成一份，而不是等第三個。

三態的分界必須明確，因為報告的措辭完全依賴它：
  ok          指令成功且有輸出
  empty       指令成功但沒有輸出（例如所有 bridge 都沒開 vlan_filtering）
  unavailable 指令不存在、非零離開碼、或執行時拋例外

★ empty 與 unavailable MUST NOT 合併。「查過了，沒有」與「查不到」在盤查報告裡
  是兩種完全不同的結論，合併之後使用者無從判斷要不要去裝 iproute2。
"""

import os
import subprocess

STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_UNAVAILABLE = "unavailable"

# [CHANGE] 2026-08-02 新增：unavailable 的**成因**（選單 7 的三態要用）。
#
# ★ 為什麼要多這一層：`unavailable` 把兩件事合在一起——「這支指令根本跑不起來」
#   與「跑起來了但回非零」。對多數呼叫端這無所謂，但 OVS 那一頁要據此告訴使用者
#   下一步做什麼：前者是「去裝 openvswitch-switch」，後者是「服務沒跑，去
#   systemctl status」。給錯了，使用者會去裝一個已經裝好的套件。
#
# ★★ 這裡**MUST NOT** 改用比對錯誤訊息字串來分辨。實測：ovsdb 停掉時
#   ovs-vsctl 的原文是
#       ovs-vsctl: unix:/var/run/openvswitch/db.sock: database connection failed
#       (No such file or directory)
#   它含有「No such file」，與「指令不存在」的訊息**逐字重疊** ⇒ 以訊息比對的
#   判準對這兩種情形同時回 True，鑑別力為零。差別是**結構性**的（有沒有拋
#   OSError），不是文字上的。這是「以形態列舉代替性質」的又一次。
FAILURE_NOT_EXECUTABLE = "not_executable"
FAILURE_EXIT_CODE = "exit_code"
# [CHANGE] 2026-08-03 待辦 #35：舊 fake 或其他上游可能沒交代 unavailable 的成因；
#          用具名值讓呼叫端能採取不誤稱「未安裝」的保守訊息。
# [CHANGE] 2026-08-03 待辦 #38：run_command() 現在也會**自己**回這個值——子行程層級
#          的例外（subprocess.SubprocessError，含 TimeoutExpired）代表「指令已經
#          啟動過，是執行過程出的事」，與「這支指令跑不起來」是兩件事。原文寫
#          「只供下游在上游沒交代成因時使用」，改動後已不成立，一併改掉。
FAILURE_UNKNOWN = "unknown"
# [CHANGE] 2026-08-03 待辦 #48（使用者裁決）：指令逾時是**獨立的成因**。
#
# ★ 它與「跑不起來」的差別對使用者是可操作的：前者叫他去裝套件，後者叫他去看
#   那台主機為什麼沒回應。與 OVS 那組常數同一個立論。
FAILURE_TIMEOUT = "timeout"

# 外部指令的逾時秒數。
#
# ★★ 為什麼要有（待辦 #48，2026-08-03 使用者裁決加上）：在此之前**沒有任何外部
#   指令設過逾時**，bash 版 2978 行同樣 0 處。後果是真機上一支指令卡住就讓整份
#   盤查停在那裡，使用者只能 Ctrl-C——而盤查工具正是「主機有點不對勁」時才會被
#   打開的東西。本檔與 `collect/sdn.py`、`render/corosync.py` 的既有註解都早就
#   寫著「`pvecm status` 在非叢集主機上會等到 timeout」，處置卻是「先看有沒有
#   設定內容再決定跑不跑」——那是**迴避**，不是防護。
#
# ★ 15 秒的取法：ethtool／ip／bridge 這類本機查詢在慢速硬體上也是毫秒級；會慢的
#   是 `pvecm status`／`ovs-vsctl` 這種要等對端回應的。15 秒足夠讓正常回應完成，
#   又不會讓一次盤查等到使用者以為當掉。**可由 `COMMAND_TIMEOUT` 調整**——這個
#   數字沒有客觀正確值，真機上量到不夠就調它，不要改碼。
COMMAND_TIMEOUT_DEFAULT = 15


def command_timeout(env=None):
    """讀取外部指令逾時秒數；空值、零、負數或非數字都回預設值。

    ★ 形態刻意與 `collect/led.py` 的 `blink_seconds()` 一致——同一個專案裡讀環境
      變數的兩種寫法會讓下一個人以為它們的容錯行為不同。
    """
    env = os.environ if env is None else env
    try:
        value = int((env.get("COMMAND_TIMEOUT") or "").strip())
    except (AttributeError, TypeError, ValueError):
        return COMMAND_TIMEOUT_DEFAULT
    return value if value > 0 else COMMAND_TIMEOUT_DEFAULT


def default_run(argv, env=None):
    """固定英文輸出，否則欄位名稱會隨 production 主機 locale 改變而無法解析。

    `env` 供測試注入；它同時決定子行程的環境與逾時秒數。
    """
    source = os.environ if env is None else env
    child_env = dict(source)
    child_env["LC_ALL"] = "C"
    return subprocess.run(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        errors="replace",
        env=child_env,
        check=False,
        # [CHANGE] 2026-08-03 待辦 #48：逾時 MUST 傳進去。沒有它，上面那個
        #          `FAILURE_TIMEOUT` 就是一個產品碼永遠產生不出來的值——那種
        #          分類只會讓人以為有人在守。
        timeout=command_timeout(source),
    )


def run_command(run_fn, argv):
    """執行外部指令並歸類成三態，回傳 {status, stdout, error, failure}。

    指令不存在時 run_fn 會拋 OSError（FileNotFoundError 是它的子類）——這在
    production 主機上很常見（沒裝 ethtool、沒裝 iproute2），不該讓整份盤查中斷。

    [CHANGE] 2026-08-03 待辦 #38：本函式**實際會產生**的成因由兩個變成三個
    （NOT_EXECUTABLE／EXIT_CODE／UNKNOWN）。原文寫「run_command 自己永遠不會回
    UNKNOWN」，改動後不再成立。

    `failure` 在 status 為 unavailable 時說明**成因**，其餘情形為 None。呼叫端要
    分辨「沒裝」與「裝了但不通」時 MUST 讀這一欄，MUST NOT 去比對 error 的字串內容
    （理由見上方 FAILURE_NOT_EXECUTABLE 的註解：訊息文字會逐字重疊）。

    ⇒ 為什麼要把 OSError 與 SubprocessError 拆開：因為**歸類錯誤本身**是缺陷。
      合併時 `FAILURE_NOT_EXECUTABLE` 這個名字承載了它名字以外的情形，而下游正是
      靠這個名字決定要不要對使用者說「去裝套件」。歸錯類的後果是叫人去裝一個
      已經裝好的東西。

    [CHANGE] 2026-08-03 待辦 #48：`default_run()` 現在會傳 `timeout`，所以
    `TimeoutExpired` **已經是產品碼到得了的狀態**了。原文寫「這條分支在現行產品
    路徑上不可達」「不細分成 TIMEOUT 因為產品碼產生不出來」——加了逾時之後兩句
    都不成立，一併改掉。
    """
    try:
        completed = run_fn(argv)
        returncode = completed.returncode
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
    except OSError as exc:
        # 指令不存在或檔案沒有執行權限：這支指令**跑不起來**。
        return {"status": STATUS_UNAVAILABLE, "stdout": None,
                "error": str(exc), "failure": FAILURE_NOT_EXECUTABLE}
    # [CHANGE] 2026-08-03 待辦 #48：逾時獨立成一個成因。
    #
    # ★★ 這一條 MUST 排在 `SubprocessError` **之前**——`TimeoutExpired` 是它的
    #   子類，順序倒過來的話這個 except 永遠走不到，而**語法完全合法、測試不動
    #   一根寒毛**（除了專門守它的那一條）。突變條目 HN 打的就是這個順序。
    except subprocess.TimeoutExpired as exc:
        return {"status": STATUS_UNAVAILABLE, "stdout": None,
                "error": str(exc), "failure": FAILURE_TIMEOUT}
    # [CHANGE] 2026-08-03 待辦 #38：與 OSError 拆開。子行程層級的例外代表指令
    #          **已經啟動過**，說它「未安裝」是沒有證據的斷言。逾時以外的
    #          SubprocessError 沒有更具體的說法，就誠實回「成因不明」。
    except subprocess.SubprocessError as exc:
        return {"status": STATUS_UNAVAILABLE, "stdout": None,
                "error": str(exc), "failure": FAILURE_UNKNOWN}

    if returncode != 0:
        return {
            "status": STATUS_UNAVAILABLE,
            "stdout": None,
            "error": stderr.strip() or "%s 離開碼 %s" % (argv[0], returncode),
            "failure": FAILURE_EXIT_CODE,
        }
    if stdout.strip():
        return {"status": STATUS_OK, "stdout": stdout, "error": None,
                "failure": None}
    return {"status": STATUS_EMPTY, "stdout": "", "error": None,
            "failure": None}


def parsed_result(command, parser):
    """把 run_command() 的結果餵給解析器，並保留原本的狀態、錯誤與失敗成因。

    解析後為空即降級成 empty：指令有輸出但一個欄位都認不出來，等同於沒有資料，
    呼叫端不該拿到一個空 dict 卻以為狀態是 ok。

    [CHANGE] 2026-08-03 待辦 #35：為相容不含 failure 欄的既有 fake，非 OK 路徑用
    fail-open 的 `.get()` 取成因。**這個 fail-open 有後果**：若 status 是
    unavailable 而 failure is None，那代表「上游沒交代成因」而不是「沒有成因」，
    呼叫端 MUST 視為**成因未知**，MUST NOT 當作「未安裝」，也 MUST NOT 當作
    「已安裝但執行失敗」——兩者都是沒有證據的斷言。
    """
    if command["status"] == STATUS_OK:
        data = parser(command["stdout"])
        return {
            "status": STATUS_OK if data else STATUS_EMPTY,
            "data": data,
            "error": None,
            # [CHANGE] 2026-08-03 待辦 #35：解析為空不是執行失敗，不可沿用上游成因。
            "failure": None,
        }
    return {
        "status": command["status"],
        "data": {} if command["status"] == STATUS_EMPTY else None,
        "error": command["error"],
        # [CHANGE] 2026-08-03 待辦 #35：保留結構性成因，避免下游猜測 error 文字。
        "failure": command.get("failure"),
    }
