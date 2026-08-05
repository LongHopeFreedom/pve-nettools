"""pve-nettools — Proxmox VE 網路盤查工具。

重寫自 v02.002.001 的 bash 版（保留於 old/ 備查，待本版真機驗證通過後除役）。

設計原則：
  * 只用 Python 標準庫。使用者 clone 下來就能跑，不需要 pip、不需要 venv——
    這是運維工具，會在別人的 production 主機上執行。
  * 取系統資料一律用 subprocess 直接 exec 執行檔，不經 shell。bash 版反覆吃過
    跳脫與 pipefail 的虧（`grep -q` 觸發 SIGPIPE 讓命中被讀成未命中、`echo 1>file`
    的 `1>` 被當成 fd 重導向），list 形式的 subprocess 天然沒有這類問題。
  * 判定邏輯與輸出分離：collect/ 只負責取值並回傳資料結構，render/ 只負責排版。
    bash 版早期把畫面與報告寫成兩套幾乎相同的碼，欄位很快就不同步了。
"""

__version__ = "03.012.000"
__author__ = "LeeFreedom"

# 目標執行環境：PVE 7（Debian 11 / Python 3.9）以上。
# 不使用 3.10+ 的 match 陳述式與 X | Y 型別語法，以免在舊節點上直接語法錯誤。
MIN_PYTHON = (3, 9)
