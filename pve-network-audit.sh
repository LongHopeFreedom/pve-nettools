#!/usr/bin/env bash
#
# ============================================================================
# PVE 互動式網路盤查工具
# ============================================================================
#
# 用途：盤查 Proxmox VE 主機的實體網卡與網路設定。可互動逐項檢視，也可非互動
#       輸出完整報告排進定期巡檢。
#
# 負責人：LeeFreedom（秉迅資訊 BingXun InfoTech）
# 建立日期：2026-07-29 ｜ 變動日期：2026-07-30 20:32
# 版本：v02.002.001
#       ★本檔頭之版本字樣為【狀態型宣稱】，指向現行版。改版時共三處 MUST 同步：
#         本行、下方的 VERSION 變數、CHANGELOG.md 最上方的版本區塊。
#         此三處是否一致由 --self-test 的第 14 段實際比對，漂移會讓自檢變紅。
#
# 變更紀錄：見同目錄 CHANGELOG.md
#           （不放在本檔，避免檔頭隨版本累積而愈來愈長）
# 說明文件：見同目錄 README.md
#           （盤查項目一覽、依賴套件、判讀提示、驗證限度）
#
# 依賴：必要  iproute2（ip、bridge）
#       建議  ethtool（速率／Duplex／媒介／韌體／LED 定位）
#             lldpd（交換器名稱與對端 Port）
#       選用  openvswitch-switch（僅 OVS 環境需要）
#       缺少任一項時該章節會印出提示並略過，不會中斷。
#
# 權限：需 root（ethtool -m 讀 SFP EEPROM、ethtool -p LED 定位、/etc/pve 讀取）。
#       --self-test 與 --help 不需 root。
#
# ⚠ 驗證限度：本工具尚未在真正的 Proxmox VE 主機上執行過。目前所有驗證都在開發機
#   以模擬的 sysfs 與 PVE 設定檔進行，自檢樣本是依 SFF-8472 等規格「構造」的，不是
#   真機擷取。首次上線請先跑 --self-test，再逐項與 ip／ethtool 的原始輸出對照，
#   確認無誤後才排進定期巡檢。未經真機驗證的項目詳見 README.md。
#
# 設計要點（改動前必讀，這幾條都是實測踩過才寫下的）：
#   1. 媒介判定只讀 SFF-8472 的「結構化欄位值」，MUST NOT 對整份 ethtool -m 輸出做
#      關鍵詞比對——該輸出必然含 "Transceiver"（內含 "sc"）與 "Optical diagnostics
#      support"，會讓 DAC 被判成光纖。
#   2. 讀 sysfs MUST 判「讀取是否成功」而非「檔案是否可讀」——介面 admin-down 時
#      讀 carrier 會回 EINVAL。
#   3. 表格對齊 MUST 用 pad()／str_width()，MUST NOT 用 printf %-Ns——後者按 byte
#      補白，中文欄位會錯位。
#   4. ethtool 快取 MUST 由迴圈直接呼叫 prime_nic_cache() 預熱，MUST NOT 指望在
#      $( ) 內寫入——那是 subshell，寫入不回傳父行程，快取會靜默失效。
#   5. 清單類輸出 MUST 用 print_limited()，MUST NOT 直接 head -N 靜默截斷。
#
# 功能：
#    1. 實體網卡：MAC、Link、速率、Duplex、MTU、介面媒介、RX/TX、驅動、韌體、PCI、NUMA
#    2. 網卡健康：carrier_changes（線路抖動）、RX/TX 錯誤與丟包、自動協商與支援模式
#    3. Bond：模式、成員、狀態、Active Slave、Hash Policy、LACP Rate
#    4. Linux Bridge：綁定 Port、VLAN-aware、vlan_protocol、default_pvid、STP、IP
#    5. Open vSwitch：OVS Bridge / Port / Bond / IntPort
#    6. VLAN：VLAN 子介面、bridge vlan 逐 Port 檢視（含 PVID/untagged）
#    7. VLAN 對帳：VM/CT 使用的 VLAN vs Bridge Uplink 實際放行的 VLAN
#    8. VM/CT 網卡對應：tap/veth 介面 ←→ VMID、名稱、bridge、tag、MTU、firewall
#    9. PVE SDN：zones / vnets / subnets / controllers
#   10. 叢集網路：corosync 環網、pvecm status
#   11. IP / 路由 / DNS / hosts / 鄰居表（IPv4 + IPv6）
#   12. PVE 防火牆狀態
#   13. LLDP：交換器名稱與 Port
#   14. /etc/network/interfaces 持久化設定
#   15. 實體網卡 LED 定位
#
# 用法：
#   pve-network-audit.sh              互動選單
#   pve-network-audit.sh --report     非互動，直接輸出完整盤查報告（可排進 cron）
#   pve-network-audit.sh --self-test  只跑內建自檢，不碰系統狀態
#   pve-network-audit.sh --help       說明
#
# 適用：Proxmox VE / Debian
#
# ============================================================================

set -uo pipefail

VERSION="02.002.001"
SAMPLE_SECONDS="${SAMPLE_SECONDS:-3}"
BLINK_SECONDS="${BLINK_SECONDS:-10}"
REPORT_DIR="${REPORT_DIR:-/root}"
REPORT_FILE=""
# 清單類輸出的顯示上限（超過時會明說截掉幾筆，不靜默截斷）
LIST_LIMIT="${LIST_LIMIT:-50}"

# PVE 設定路徑（可由環境覆寫，方便離線以複本測試）
PVE_CONF_ROOT="${PVE_CONF_ROOT:-/etc/pve}"
NET_CONF_FILE="${NET_CONF_FILE:-/etc/network/interfaces}"
NET_CONF_DIR="${NET_CONF_DIR:-/etc/network/interfaces.d}"
SYS_NET_ROOT="${SYS_NET_ROOT:-/sys/class/net}"
PROC_BONDING_DIR="${PROC_BONDING_DIR:-/proc/net/bonding}"

USE_COLOR=1

declare -a PHYSICAL_NICS=()
declare -A RX_DIFF=()
declare -A TX_DIFF=()

# ethtool 輸出快取：一張網卡的每種輸出只取一次
declare -A ETHTOOL_OUT=()
declare -A ETHTOOL_DRV=()
declare -A ETHTOOL_MOD=()
declare -A ETHTOOL_MOD_TRIED=()

# ── 顏色 ──────────────────────────────────────────────────────────────────

setup_colors() {
    if [[ "$USE_COLOR" == "1" ]]; then
        RED=$'\033[0;31m'
        GREEN=$'\033[0;32m'
        YELLOW=$'\033[0;33m'
        BLUE=$'\033[0;34m'
        CYAN=$'\033[0;36m'
        BOLD=$'\033[1m'
        NC=$'\033[0m'
    else
        RED=""
        GREEN=""
        YELLOW=""
        BLUE=""
        CYAN=""
        BOLD=""
        NC=""
    fi
}

[[ -t 1 ]] || USE_COLOR=0
setup_colors

# ── 顯示寬度與欄位補白 ────────────────────────────────────────────────────
#
# [CHANGE] printf "%-Ns" 是按 byte 補白，對 CJK 會錯位（「已接線」佔 9 bytes 卻只顯示
#          6 欄）。此處依「終端顯示寬度」補白：UTF-8 下 CJK 全形字為 3 bytes / 1 char
#          且顯示佔 2 欄，故 顯示寬度 = 字元數 + (byte 數 - 字元數) / 2。
#          非 UTF-8 locale 下 ${#s} 直接回 byte 數，公式自動退化為 byte 對齊（不會更糟）。

str_width() {
    local s="$1" chars bytes saved
    chars=${#s}

    saved="${LC_ALL-}"
    LC_ALL=C
    bytes=${#s}
    if [[ -n "$saved" ]]; then LC_ALL="$saved"; else unset LC_ALL; fi

    if ((bytes <= chars)); then
        printf '%s' "$chars"
        return
    fi
    printf '%s' "$(( chars + (bytes - chars) / 2 ))"
}

# pad <字串> <欄寬>：靠左對齊補到指定顯示寬度
pad() {
    local s="$1" width="$2" w p
    w=$(str_width "$s")
    p=$((width - w))
    ((p < 0)) && p=0
    printf '%s%*s' "$s" "$p" ''
}

# padc <字串> <欄寬> <顏色>：同 pad，但只對文字著色（補白不著色，避免顏色碼算進寬度）
padc() {
    local s="$1" width="$2" color="${3:-}" w p
    w=$(str_width "$s")
    p=$((width - w))
    ((p < 0)) && p=0
    printf '%s%s%s%*s' "$color" "$s" "$NC" "$p" ''
}

# ── 終端寬度與版面選擇 ────────────────────────────────────────────────────
#
# 寬表格在 80 欄終端會折行，對齊整個毀掉——PVE 網頁主控台（noVNC）預設就落在這個
# 寬度附近，而網卡愈多、看得愈久，這問題愈明顯。故依實際終端寬度自動切換版面：
# 夠寬用表格，不夠寬改用逐張區塊（欄位垂直排列，永遠不會折行）。
#
# 報告檔不受此影響：輸出不是 tty 時一律視為寬螢幕。同一份報告在不同機器上讀，
# 內容必須一致，版面不該由「產生當下的終端多大」決定。

TABLE_MIN_WIDTH_NICS=132        # render_physical_nics 的表格實測 131 欄
TABLE_MIN_WIDTH_HEALTH=135      # render_nic_health   的表格實測 134 欄
TABLE_MIN_WIDTH_GUEST=130       # render_guest_nics   的表格實測 128 欄

term_width() {
    # 顯式指定優先（供測試與使用者強制指定）
    if [[ -n "${TERM_WIDTH:-}" ]]; then
        printf '%s' "$TERM_WIDTH"
        return
    fi

    # [CHANGE] v02.002.000：判「是否有終端可問」而非只看 stdout。
    # 互動檢視會把輸出接給 pager，此時 stdout 是 pipe，但使用者面前仍然是一個
    # 有固定寬度的終端——若只看 stdout 就會誤判成寬螢幕，窄終端的區塊版永遠
    # 不會被觸發。stdout 與 stderr 皆非 tty 才是真正的報告／管線情境。
    if [[ ! -t 1 && ! -t 2 ]]; then
        printf '%s' 9999
        return
    fi

    # 同理，寬度要向 /dev/tty 問，不能問已被接走的 stdout
    local w=""
    if command_exists tput; then
        w=$(tput cols 2>/dev/null < /dev/tty || true)
        [[ "$w" =~ ^[0-9]+$ ]] || w=$(tput cols 2>/dev/null || true)
    fi
    [[ "$w" =~ ^[0-9]+$ ]] || w="${COLUMNS:-}"
    [[ "$w" =~ ^[0-9]+$ ]] || w=80
    printf '%s' "$w"
}

# use_table <表格所需最小寬度> → rc=0 表示可用表格版
use_table() {
    local need="$1" have
    have=$(term_width)
    [[ "$have" =~ ^[0-9]+$ ]] || have=80
    ((have >= need))
}

# ── 分頁輸出 ──────────────────────────────────────────────────────────────
#
# PVE 上 guest 一多，輸出動輒上百行——實測 30 台 VM 時 bridge vlan 就 91 行
# （整理版 34 行 ＋ bridge vlan show 原始輸出 57 行），直接印會整頁刷過去。
# 故互動檢視一律交給 pager：
#   -S  長行不折行，改用左右方向鍵橫向捲動（寬表格不必犧牲欄位）
#   -R  保留 ANSI 顏色
#   -X  離開後不清畫面，內容留在螢幕上
# 另外 less 內建的 / 搜尋在「30 台 VM 裡找某個 VLAN」這種場景特別有用。
#
# 報告模式（非 tty）與 NO_PAGER=1 一律原樣輸出，不經 pager。

pager_available() {
    [[ -t 1 ]] || return 1
    [[ "${NO_PAGER:-}" != "1" ]] || return 1
    command_exists less || command_exists more
}

page_output() {
    if ! pager_available; then
        cat
        return
    fi

    if command_exists less; then
        less -SRX
    else
        more
    fi
}

hr() {
    local width="${1:-100}"
    printf '%*s\n' "$width" '' | tr ' ' '='
}

thin_hr() {
    local width="${1:-100}"
    printf '%*s\n' "$width" '' | tr ' ' '-'
}

# ── 通用工具 ──────────────────────────────────────────────────────────────

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# [CHANGE] 舊版判準是 [[ -r "$path" ]]（檔案可讀）。sysfs 有「可讀但讀取失敗」的情形：
#          介面 admin-down 時讀 carrier 回 EINVAL ⇒ 舊版回空字串而非預設值，且 cat 的
#          錯誤訊息會外洩（報告模式帶 2>&1，會被寫進報告檔）。改為判「讀取是否成功」。
read_sysfs() {
    local path="$1"
    local default_value="${2:-N/A}"
    local value=""

    if value=$(cat -- "$path" 2>/dev/null) && [[ -n "$value" ]]; then
        printf '%s' "$value"
    else
        printf '%s' "$default_value"
    fi
}

require_root() {
    if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
        echo -e "${RED}請使用 root 權限執行此腳本。${NC}" >&2
        exit 1
    fi
}

pause_screen() {
    echo
    read -r -p "按 Enter 返回主選單..." _
}

clear_screen() {
    if command_exists clear; then
        clear
    else
        printf '\033c'
    fi
}

print_header() {
    echo -e "${BOLD}${CYAN}PVE 互動式網路盤查工具${NC}  v${VERSION}"
    echo "主機名稱：$(hostname)"
    echo "執行時間：$(date '+%Y-%m-%d %H:%M:%S')"
    echo
}

section() {
    echo -e "${BOLD}${CYAN}$1${NC}"
    echo
}

subsection() {
    echo -e "${BOLD}$1${NC}"
}

kv() {
    local key="$1" value="$2"
    printf '%s：%s\n' "$(pad "$key" 16)" "$value"
}

note() {
    echo -e "${YELLOW}$1${NC}"
}

# [CHANGE] v02.000.001：印出 stdin，超過上限時截斷並「明說」截掉多少。
#          v02.000.000 用 `| head -50` 直接截斷，讀報告的人會以為那就是全部——
#          盤查報告裡的靜默截斷等同給出錯誤結論。
print_limited() {
    local limit="$1" unit="${2:-筆}" content total
    content=$(cat)
    [[ -n "$content" ]] || return 0

    total=$(wc -l <<< "$content")
    if ((total > limit)); then
        head -n "$limit" <<< "$content"
        note "⋯ 以上為前 ${limit} ${unit}，實際共 ${total} ${unit}（未顯示 $((total - limit)) ${unit}；調整上限請設 LIST_LIMIT）"
    else
        printf '%s\n' "$content"
    fi
}

# ── ethtool 快取層 ────────────────────────────────────────────────────────
#
# [CHANGE] 舊版每張網卡呼叫 ethtool 7 次（get_port_type 內就 3 次）。ethtool -m 走 i2c
#          讀 SFP EEPROM，慢且對部分驅動有副作用，尤其不該重複呼叫。

ethtool_out() {
    local nic="$1"
    if [[ -z "${ETHTOOL_OUT[$nic]+x}" ]]; then
        if command_exists ethtool; then
            ETHTOOL_OUT["$nic"]=$(ethtool "$nic" 2>/dev/null || true)
        else
            ETHTOOL_OUT["$nic"]=""
        fi
    fi
    printf '%s' "${ETHTOOL_OUT[$nic]}"
}

ethtool_drv() {
    local nic="$1"
    if [[ -z "${ETHTOOL_DRV[$nic]+x}" ]]; then
        if command_exists ethtool; then
            ETHTOOL_DRV["$nic"]=$(ethtool -i "$nic" 2>/dev/null || true)
        else
            ETHTOOL_DRV["$nic"]=""
        fi
    fi
    printf '%s' "${ETHTOOL_DRV[$nic]}"
}

ethtool_mod() {
    local nic="$1"
    if [[ -z "${ETHTOOL_MOD_TRIED[$nic]+x}" ]]; then
        ETHTOOL_MOD_TRIED["$nic"]=1
        if command_exists ethtool; then
            ETHTOOL_MOD["$nic"]=$(ethtool -m "$nic" 2>/dev/null || true)
        else
            ETHTOOL_MOD["$nic"]=""
        fi
    fi
    printf '%s' "${ETHTOOL_MOD[$nic]:-}"
}

reset_caches() {
    ETHTOOL_OUT=()
    ETHTOOL_DRV=()
    ETHTOOL_MOD=()
    ETHTOOL_MOD_TRIED=()
}

# [CHANGE] v02.000.001：快取預熱。
#
# 上面那些 ethtool_*() 只有在「於父行程執行」時才真的存得住快取。表格輸出是以
#   pad "$(get_speed "$nic")" 12
# 這種形式呼叫的，而 command substitution `$( )` 會開 subshell——subshell 繼承的
# 變數可【讀】，但它對 ETHTOOL_OUT 等關聯陣列的【寫入不會回傳父行程】。於是每個
# 欄位都各自重跑一次 ethtool，快取一次都沒命中。
#
# 這個缺陷在 v02.000.000 沒被發現，因為當時只看程式碼結構就宣稱「已改為每種輸出
# 各取一次」，沒有實際數過呼叫次數。用計數用的假 ethtool 實測，當時是每張卡 6 次
# （v01 為 7 次）——幾乎沒有改善。
#
# 修法：在每個會逐卡輸出的迴圈裡「直接呼叫」本函式（不可包在 $( ) 內），先在父
# 行程把該卡的 ethtool 輸出填進快取；之後那些 $( ) 內的取值就會讀到快取。
#
# ⚠ 改動這裡或迴圈中的呼叫時，MUST 用假 ethtool 實際數呼叫次數，不可只看結構。
prime_nic_cache() {
    local nic="$1"

    [[ -n "${ETHTOOL_OUT[$nic]+x}" ]] || {
        if command_exists ethtool; then
            ETHTOOL_OUT["$nic"]=$(ethtool "$nic" 2>/dev/null || true)
        else
            ETHTOOL_OUT["$nic"]=""
        fi
    }

    [[ -n "${ETHTOOL_DRV[$nic]+x}" ]] || {
        if command_exists ethtool; then
            ETHTOOL_DRV["$nic"]=$(ethtool -i "$nic" 2>/dev/null || true)
        else
            ETHTOOL_DRV["$nic"]=""
        fi
    }

    # ethtool -m 走 i2c 讀 SFP EEPROM，慢且對部分驅動有副作用，故僅在該卡不是
    # RJ45 電口時才讀——純電口主機完全不會碰到 EEPROM（已實測 -m 呼叫 0 次）。
    if [[ -z "${ETHTOOL_MOD_TRIED[$nic]+x}" ]]; then
        ETHTOOL_MOD_TRIED["$nic"]=1
        ETHTOOL_MOD["$nic"]=""
        if command_exists ethtool &&
            [[ "$(field_value "${ETHTOOL_OUT[$nic]}" "Port")" != "Twisted Pair" ]]; then
            ETHTOOL_MOD["$nic"]=$(ethtool -m "$nic" 2>/dev/null || true)
        fi
    fi
}

# 從 "Key: Value" 形式的輸出取出指定欄位的「值」（只取值部分，不回傳整行）
field_value() {
    local text="$1" key="$2"
    awk -v k="$key" '
        {
            line = $0
            sub(/^[[:space:]]+/, "", line)
            idx = index(line, ":")
            if (idx == 0) next
            name = substr(line, 1, idx - 1)
            val  = substr(line, idx + 1)
            gsub(/[[:space:]]+$/, "", name)
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", val)
            if (name == k) { print val; exit }
        }' <<< "$text"
}

# ── 實體網卡 ──────────────────────────────────────────────────────────────

refresh_physical_nics() {
    PHYSICAL_NICS=()

    local path nic
    for path in "$SYS_NET_ROOT"/*; do
        [[ -e "$path" ]] || continue
        nic=$(basename "$path")

        [[ "$nic" == "lo" ]] && continue

        # 實體 PCI/USB 網卡具有 device 連結；tap/veth/bridge/bond/vlan 皆無。
        if [[ -e "$path/device" ]]; then
            PHYSICAL_NICS+=("$nic")
        fi
    done

    if ((${#PHYSICAL_NICS[@]} > 0)); then
        mapfile -t PHYSICAL_NICS < <(printf '%s\n' "${PHYSICAL_NICS[@]}" | sort -V)
    fi
}

get_carrier()   { read_sysfs "$SYS_NET_ROOT/$1/carrier" "N/A"; }
get_mac()       { read_sysfs "$SYS_NET_ROOT/$1/address" "N/A"; }
get_operstate() { read_sysfs "$SYS_NET_ROOT/$1/operstate" "unknown"; }
get_mtu()       { read_sysfs "$SYS_NET_ROOT/$1/mtu" "N/A"; }

get_carrier_changes() {
    read_sysfs "$SYS_NET_ROOT/$1/carrier_changes" "N/A"
}

get_numa_node() {
    local v
    v=$(read_sysfs "$SYS_NET_ROOT/$1/device/numa_node" "N/A")
    [[ "$v" == "-1" ]] && v="無"
    printf '%s' "$v"
}

get_link_plain() {
    case "$(get_carrier "$1")" in
        1) echo "已接線" ;;
        0) echo "未接線" ;;
        *) echo "未知" ;;
    esac
}

link_color() {
    case "$(get_carrier "$1")" in
        1) printf '%s' "$GREEN" ;;
        0) printf '%s' "$RED" ;;
        *) printf '%s' "$YELLOW" ;;
    esac
}

normalize_unknown() {
    case "$1" in
        ""|"Unknown!"|"Unknown"|"-1") echo "N/A" ;;
        *) echo "$1" ;;
    esac
}

get_speed()  { normalize_unknown "$(field_value "$(ethtool_out "$1")" "Speed")"; }
get_duplex() { normalize_unknown "$(field_value "$(ethtool_out "$1")" "Duplex")"; }
get_autoneg() { normalize_unknown "$(field_value "$(ethtool_out "$1")" "Auto-negotiation")"; }

get_driver() {
    local v
    v=$(field_value "$(ethtool_drv "$1")" "driver")
    printf '%s' "${v:-N/A}"
}

get_fw_version() {
    local v
    v=$(field_value "$(ethtool_drv "$1")" "firmware-version")
    printf '%s' "${v:-N/A}"
}

get_bus_info() {
    local v
    v=$(field_value "$(ethtool_drv "$1")" "bus-info")
    printf '%s' "${v:-N/A}"
}

# [CHANGE] 媒介判定重寫。
#
#   舊版：grep -Eqi 'LC|SC|MPO|MTP|optical|laser|Base-SR|…' <<< "$connector $module_dump …"
#         — 未錨定的雙字母 alternation 掃「整份」ethtool -m 輸出。實測命中片段為 "sc"，
#           來源是 ethtool -m 必然出現的欄位名 "Tran(sc)eiver"；"Optical diagnostics
#           support : No" 這行連 DAC 也有，同樣命中 "Optical"。
#         ⇒ 只要插了 SFP/QSFP 模組，除非 EEPROM 恰好含 "copper pigtail" 等字被前一段
#           先攔下，一律誤判為「光纖」。
#
#   新版三段判準，由確定性最高者優先：
#     (1) ethtool 的 Port 欄位為 Twisted Pair ⇒ RJ45 電口（銅纜直出，不需看模組）
#     (2) 模組線長欄位：Length (Copper) > 0 而各光纖長度欄位皆為 0 ⇒ DAC/AOC 銅纜；
#         反之任一光纖長度欄位 > 0 ⇒ 光纖。這是 SFF-8472 的結構化欄位，最不易誤判。
#     (3) 退回 Connector / Transceiver type 等「欄位值」（非整份 dump）的錨定詞比對。
get_port_type() {
    local nic="$1"
    local eth_out mod_dump port connector xcvr_type cable_tech transceiver
    local len_copper=0 len_smf_km=0 len_smf=0 len_om1=0 len_om2=0 len_om3=0 len_om4=0
    local optical_len=0

    eth_out=$(ethtool_out "$nic")
    port=$(field_value "$eth_out" "Port")
    transceiver=$(field_value "$eth_out" "Transceiver")

    # (1) 電口可直接判定，且不必去讀 SFP EEPROM
    if [[ "$port" == "Twisted Pair" ]]; then
        echo "RJ45 電口"
        return
    fi

    case "$port" in
        "Backplane") echo "背板介面"; return ;;
        "AUI"|"MII") echo "電口"; return ;;
    esac

    mod_dump=$(ethtool_mod "$nic")

    if [[ -n "$mod_dump" ]]; then
        connector=$(field_value "$mod_dump" "Connector")
        xcvr_type=$(field_value "$mod_dump" "Transceiver type")
        cable_tech=$(field_value "$mod_dump" "Cable technology")
        [[ -z "$cable_tech" ]] && cable_tech=$(field_value "$mod_dump" "Device technology")

        # (2a) 銅口 SFP 模組（1000BASE-T / 10GBASE-T）：Connector 為 RJ45，而
        #      Length (Copper) 會填 100m。MUST 排在下面的線長判準之前，否則
        #      「銅纜長度 > 0 且光纖長度 = 0」會把它判成 DAC——實測確為如此。
        if grep -Eqi '(^|[^[:alnum:]])RJ45([^[:alnum:]]|$)' <<< "$connector" ||
            grep -Eqi 'BASE-T([^[:alnum:]]|$)' <<< "$xcvr_type"; then
            echo "RJ45 電口"
            return
        fi

        # (2b) 線長欄位（SFF-8472 結構化欄位）
        len_copper=$(numeric_prefix "$(field_value "$mod_dump" "Length (Copper)")")
        len_smf_km=$(numeric_prefix "$(field_value "$mod_dump" "Length (SMF,km)")")
        len_smf=$(numeric_prefix "$(field_value "$mod_dump" "Length (SMF)")")
        len_om1=$(numeric_prefix "$(field_value "$mod_dump" "Length (62.5um)")")
        len_om2=$(numeric_prefix "$(field_value "$mod_dump" "Length (50um)")")
        len_om3=$(numeric_prefix "$(field_value "$mod_dump" "Length (OM3)")")
        len_om4=$(numeric_prefix "$(field_value "$mod_dump" "Length (OM4)")")
        optical_len=$((len_smf_km + len_smf + len_om1 + len_om2 + len_om3 + len_om4))

        if ((len_copper > 0 && optical_len == 0)); then
            if grep -Eqi 'active' <<< "$cable_tech"; then
                echo "AOC 主動線纜"
            else
                echo "DAC 銅纜"
            fi
            return
        fi

        if ((optical_len > 0)); then
            echo "光纖"
            return
        fi

        # (3) 只比對「欄位值」，且用錨定詞
        if grep -Eqi '(^|[^[:alnum:]])(passive cable|copper pigtail|direct attach|copper cable|twinax)([^[:alnum:]]|$)' \
            <<< "$connector $cable_tech $xcvr_type"; then
            echo "DAC 銅纜"
            return
        fi

        if grep -Eqi '(^|[^[:alnum:]])active( optical)? cable([^[:alnum:]]|$)' <<< "$cable_tech $xcvr_type"; then
            echo "AOC 主動線纜"
            return
        fi

        if grep -Eqi '(^|[^[:alnum:]])(LC|SC|MPO|MTP|MPO 1x12|optical pigtail)([^[:alnum:]]|$)' <<< "$connector" ||
            grep -Eqi 'Base-(SR|LR|ER|ZR|LX|SX|PSM|CWDM|DWDM)' <<< "$xcvr_type"; then
            echo "光纖"
            return
        fi

        # RJ45 已於 (2a) 攔下；Copper Pigtail 屬 DAC 接頭，已在上面的 DAC 分支處理。
        echo "SFP/QSFP 模組"
        return
    fi

    case "$port" in
        "FIBRE"|"Fiber")            echo "光纖" ;;
        "Direct Attach Copper")     echo "DAC 銅纜" ;;
        "Other")
            if [[ "$transceiver" == "external" ]]; then
                echo "外接模組/未知"
            else
                echo "未知"
            fi
            ;;
        *) echo "${port:-未知}" ;;
    esac
}

# 取字串開頭的整數（"3m" → 3、"0km" → 0、"" → 0）
numeric_prefix() {
    local s="${1:-}"
    s="${s##[[:space:]]}"
    if [[ "$s" =~ ^([0-9]+) ]]; then
        printf '%s' "${BASH_REMATCH[1]}"
    else
        printf '0'
    fi
}

get_stat() {
    read_sysfs "$SYS_NET_ROOT/$1/statistics/$2" "0"
}

sample_traffic() {
    local nic rx_after tx_after
    declare -A rx_before=()
    declare -A tx_before=()

    RX_DIFF=()
    TX_DIFF=()

    refresh_physical_nics
    ((${#PHYSICAL_NICS[@]} > 0)) || return 0

    for nic in "${PHYSICAL_NICS[@]}"; do
        rx_before["$nic"]=$(get_stat "$nic" rx_bytes)
        tx_before["$nic"]=$(get_stat "$nic" tx_bytes)
    done

    echo -e "${CYAN}正在取樣 RX/TX 流量 ${SAMPLE_SECONDS} 秒...${NC}"
    sleep "$SAMPLE_SECONDS"

    for nic in "${PHYSICAL_NICS[@]}"; do
        rx_after=$(get_stat "$nic" rx_bytes)
        tx_after=$(get_stat "$nic" tx_bytes)

        RX_DIFF["$nic"]=$((rx_after - rx_before["$nic"]))
        TX_DIFF["$nic"]=$((tx_after - tx_before["$nic"]))

        ((RX_DIFF["$nic"] < 0)) && RX_DIFF["$nic"]=0
        ((TX_DIFF["$nic"] < 0)) && TX_DIFF["$nic"]=0
    done

    # [CHANGE] 舊版最後一個指令是 ((… < 0))，值為 0 時回 rc=1，使整個函式在正常情況失敗。
    return 0
}

traffic_plain() {
    if (( ${1:-0} > 0 )); then echo "有流量"; else echo "無流量"; fi
}

traffic_color() {
    if (( ${1:-0} > 0 )); then printf '%s' "$GREEN"; else printf '%s' "$RED"; fi
}

render_physical_nics() {
    refresh_physical_nics

    if ((${#PHYSICAL_NICS[@]} == 0)); then
        note "找不到實體網卡。"
        return
    fi

    if ! command_exists ethtool; then
        note "未安裝 ethtool，速率、Duplex、驅動、韌體與媒介類型無法取得。"
        echo "安裝指令：apt update && apt install -y ethtool"
        echo
    fi

    sample_traffic
    echo

    # [CHANGE] v02.001.000：窄終端自動改用逐張區塊，詳 term_width() 的註解。
    if use_table "$TABLE_MIN_WIDTH_NICS"; then
        render_physical_nics_table
    else
        render_physical_nics_blocks
    fi

    echo
    echo "說明：RX/TX 表示在 ${SAMPLE_SECONDS} 秒取樣期間計數器是否增加；無流量不代表網路異常。"
}

render_physical_nics_table() {
    pad "介面" 14;  pad "MAC Address" 19; pad "Link" 9;  pad "速率" 12
    pad "Duplex" 9; pad "MTU" 7;          pad "媒介" 16; pad "RX" 9
    pad "TX" 9;     pad "驅動" 13;        pad "PCI 位址" 14; echo
    hr 131

    local nic
    for nic in "${PHYSICAL_NICS[@]}"; do
        # MUST 在此直接呼叫（不可包進 $( )），否則下面每個欄位都會各自重跑一次
        # ethtool——詳 prime_nic_cache 的註解。
        prime_nic_cache "$nic"

        pad  "$nic" 14
        pad  "$(get_mac "$nic")" 19
        padc "$(get_link_plain "$nic")" 9 "$(link_color "$nic")"
        pad  "$(get_speed "$nic")" 12
        pad  "$(get_duplex "$nic")" 9
        pad  "$(get_mtu "$nic")" 7
        pad  "$(get_port_type "$nic")" 16
        padc "$(traffic_plain "${RX_DIFF[$nic]:-0}")" 9 "$(traffic_color "${RX_DIFF[$nic]:-0}")"
        padc "$(traffic_plain "${TX_DIFF[$nic]:-0}")" 9 "$(traffic_color "${TX_DIFF[$nic]:-0}")"
        pad  "$(get_driver "$nic")" 13
        pad  "$(get_bus_info "$nic")" 14
        echo
    done
}

render_physical_nics_blocks() {
    local nic
    for nic in "${PHYSICAL_NICS[@]}"; do
        prime_nic_cache "$nic"      # 同表格版，MUST 直接呼叫

        echo -e "${BOLD}── ${CYAN}${nic}${NC}${BOLD} ──${NC}"
        printf '%s：%s\n' "$(pad "MAC" 8)" "$(get_mac "$nic")"
        printf '%s：%s  %s：%s\n' \
            "$(pad "Link" 8)" "$(padc "$(get_link_plain "$nic")" 9 "$(link_color "$nic")")" \
            "速率" "$(get_speed "$nic")"
        printf '%s：%s  %s：%s\n' \
            "$(pad "MTU" 8)" "$(pad "$(get_mtu "$nic")" 9)" \
            "媒介" "$(get_port_type "$nic")"
        # 這是行末，不補白——補了只會留下看不見的尾隨空白
        printf '%s：%s%s%s / %s%s%s\n' \
            "$(pad "RX/TX" 8)" \
            "$(traffic_color "${RX_DIFF[$nic]:-0}")" "$(traffic_plain "${RX_DIFF[$nic]:-0}")" "$NC" \
            "$(traffic_color "${TX_DIFF[$nic]:-0}")" "$(traffic_plain "${TX_DIFF[$nic]:-0}")" "$NC"
        printf '%s：%s  %s：%s\n' \
            "$(pad "驅動" 8)" "$(pad "$(get_driver "$nic")" 9)" \
            "PCI" "$(get_bus_info "$nic")"
        echo
    done
}

render_nic_health() {
    refresh_physical_nics

    if ((${#PHYSICAL_NICS[@]} == 0)); then
        note "找不到實體網卡。"
        return
    fi

    subsection "網卡健康指標"
    echo

    # [CHANGE] v02.001.000：窄終端自動改用逐張區塊。
    if use_table "$TABLE_MIN_WIDTH_HEALTH"; then
        render_nic_health_table
    else
        render_nic_health_blocks
    fi

    echo
    echo "說明：Link 變動＝carrier_changes，開機後正常為 1～2；"
    echo "      持續增加代表線路或模組抖動。"
    echo "      CRC 錯誤非 0 幾乎必為實體層問題（線材、模組、對端 Port）。"
}

# 取一張網卡的健康數值放進 NH_* 供兩種版面共用。抽出來是為了不讓表格版與區塊版
# 各自取一次值——那正是舊版 show_*/report_* 兩套實作會漂移的老問題。
_load_nic_health() {
    local nic="$1"
    prime_nic_cache "$nic"

    NH_STATE=$(get_operstate "$nic")
    NH_CHANGES=$(get_carrier_changes "$nic")
    NH_AUTONEG=$(get_autoneg "$nic")
    NH_RX_ERR=$(get_stat "$nic" rx_errors)
    NH_RX_DROP=$(get_stat "$nic" rx_dropped)
    NH_TX_ERR=$(get_stat "$nic" tx_errors)
    NH_TX_DROP=$(get_stat "$nic" tx_dropped)
    NH_CRC=$(get_stat "$nic" rx_crc_errors)
    NH_NUMA=$(get_numa_node "$nic")
    NH_FW=$(get_fw_version "$nic")

    # carrier_changes 偏高代表線路抖動；開機後正常值為 1～2
    if [[ "$NH_CHANGES" =~ ^[0-9]+$ ]] && ((NH_CHANGES > 4)); then
        NH_CHANGES_COLOR="$YELLOW"
    else
        NH_CHANGES_COLOR=""
    fi

    if [[ "$NH_CRC" =~ ^[0-9]+$ ]] && ((NH_CRC > 0)); then
        NH_CRC_COLOR="$RED"
    else
        NH_CRC_COLOR=""
    fi
}

# 錯誤／丟包計數非 0 時標黃
_counter_color() {
    if [[ "${1:-}" =~ ^[0-9]+$ ]] && (($1 > 0)); then
        printf '%s' "$YELLOW"
    fi
}

render_nic_health_table() {
    pad "介面" 14;    pad "狀態" 10;      pad "Link 變動" 11; pad "自動協商" 11
    pad "RX 錯誤" 10; pad "RX 丟包" 10;   pad "TX 錯誤" 10;   pad "TX 丟包" 10
    pad "CRC 錯誤" 11; pad "NUMA" 6;      pad "韌體版本" 20; echo
    hr 134

    local nic v
    for nic in "${PHYSICAL_NICS[@]}"; do
        _load_nic_health "$nic"

        pad  "$nic" 14
        pad  "$NH_STATE" 10
        padc "$NH_CHANGES" 11 "$NH_CHANGES_COLOR"
        pad  "$NH_AUTONEG" 11

        for v in "$NH_RX_ERR" "$NH_RX_DROP" "$NH_TX_ERR" "$NH_TX_DROP"; do
            padc "$v" 10 "$(_counter_color "$v")"
        done

        padc "$NH_CRC" 11 "$NH_CRC_COLOR"
        pad  "$NH_NUMA" 6
        pad  "$NH_FW" 20
        echo
    done
}

render_nic_health_blocks() {
    local nic
    for nic in "${PHYSICAL_NICS[@]}"; do
        _load_nic_health "$nic"

        echo -e "${BOLD}── ${CYAN}${nic}${NC}${BOLD} ──${NC}"
        printf '%s：%s  %s：%s\n' \
            "$(pad "狀態" 10)" "$(pad "$NH_STATE" 10)" \
            "自動協商" "$NH_AUTONEG"
        printf '%s：%s  %s：%s%s%s\n' \
            "$(pad "Link 變動" 10)" "$(padc "$NH_CHANGES" 10 "$NH_CHANGES_COLOR")" \
            "CRC 錯誤" "$NH_CRC_COLOR" "$NH_CRC" "$NC"
        # 行末不補白
        printf '%s：RX %s%s%s / %s%s%s   TX %s%s%s / %s%s%s\n' \
            "$(pad "錯誤/丟包" 10)" \
            "$(_counter_color "$NH_RX_ERR")"  "$NH_RX_ERR"  "$NC" \
            "$(_counter_color "$NH_RX_DROP")" "$NH_RX_DROP" "$NC" \
            "$(_counter_color "$NH_TX_ERR")"  "$NH_TX_ERR"  "$NC" \
            "$(_counter_color "$NH_TX_DROP")" "$NH_TX_DROP" "$NC"
        printf '%s：%s  %s：%s\n' \
            "$(pad "NUMA" 10)" "$(pad "$NH_NUMA" 10)" \
            "韌體版本" "$NH_FW"
        echo
    done
}

render_nic_modules() {
    refresh_physical_nics

    local nic mod found=0
    for nic in "${PHYSICAL_NICS[@]}"; do
        prime_nic_cache "$nic"          # [CHANGE] 同上，MUST 直接呼叫
        mod="${ETHTOOL_MOD[$nic]:-}"
        [[ -n "$mod" ]] || continue
        found=1
        echo
        subsection "── $nic ── 判定媒介：$(get_port_type "$nic")"
        kv "廠商" "$(field_value "$mod" "Vendor name")"
        kv "料號" "$(field_value "$mod" "Vendor PN")"
        kv "序號" "$(field_value "$mod" "Vendor SN")"
        kv "接頭" "$(field_value "$mod" "Connector")"
        kv "模組型別" "$(field_value "$mod" "Transceiver type")"
        kv "線纜技術" "$(field_value "$mod" "Cable technology")"
        kv "銅纜長度" "$(field_value "$mod" "Length (Copper)")"
        kv "溫度" "$(field_value "$mod" "Module temperature")"
        kv "電壓" "$(field_value "$mod" "Module voltage")"
        kv "光發射功率" "$(field_value "$mod" "Laser output power")"
        kv "光接收功率" "$(field_value "$mod" "Receiver signal average optical power")"
    done

    if ((found == 0)); then
        note "沒有偵測到可讀取的 SFP/QSFP 模組（純 RJ45 電口網卡屬正常）。"
    fi
}

# ── Bond ──────────────────────────────────────────────────────────────────

render_bonds() {
    if ! compgen -G "$PROC_BONDING_DIR/*" >/dev/null; then
        note "目前沒有執行中的 Bond 介面。"
        return
    fi

    local bond_file bond body mode hash_policy bond_status active_slave primary_slave
    local lacp_rate min_links slaves slave_status

    for bond_file in "$PROC_BONDING_DIR"/*; do
        [[ -f "$bond_file" ]] || continue
        bond=$(basename "$bond_file")

        # [CHANGE] 整份讀一次即可，舊寫法每取一個欄位就 cat 一遍。
        # 注意 MII Status 在 bond 層與每個 slave 各出現一次，field_value 取第一個
        # 命中即返回，正好是 bond 層的值。
        body=$(cat "$bond_file")
        mode=$(field_value "$body" "Bonding Mode")
        hash_policy=$(field_value "$body" "Transmit Hash Policy")
        bond_status=$(field_value "$body" "MII Status")
        active_slave=$(field_value "$body" "Currently Active Slave")
        primary_slave=$(field_value "$body" "Primary Slave")
        slaves=$(awk -F': ' '
            /^Slave Interface:/ {
                if (result != "") result = result ", "
                result = result $2
            }
            END { print result }
        ' "$bond_file")

        lacp_rate=$(read_sysfs "$SYS_NET_ROOT/$bond/bonding/lacp_rate" "N/A")
        min_links=$(read_sysfs "$SYS_NET_ROOT/$bond/bonding/min_links" "N/A")

        hr 80
        echo -e "${BOLD}Bond 介面${NC}       ：${CYAN}${bond}${NC}"
        kv "Bond 模式" "${mode:-N/A}"
        kv "成員網卡" "${slaves:-N/A}"
        kv "Hash Policy" "${hash_policy:-N/A}"
        kv "目前 Active" "${active_slave:-N/A}"
        kv "Primary Slave" "${primary_slave:-N/A}"
        kv "LACP Rate" "${lacp_rate:-N/A}"
        kv "Minimum Links" "${min_links:-N/A}"
        kv "MTU" "$(get_mtu "$bond")"
        kv "IPv4" "$(get_addresses "$bond" 4)"
        kv "IPv6" "$(get_addresses "$bond" 6)"

        case "$bond_status" in
            up)   echo -e "$(pad "Bond Link" 16)：${GREEN}正常${NC}" ;;
            down) echo -e "$(pad "Bond Link" 16)：${RED}異常${NC}" ;;
            *)    echo -e "$(pad "Bond Link" 16)：${YELLOW}${bond_status:-未知}${NC}" ;;
        esac

        echo
        echo "成員狀態："

        while IFS='|' read -r slave status speed perm_mac aggregator_id; do
            [[ -n "$slave" ]] || continue
            case "$status" in
                up)   slave_status="${GREEN}正常${NC}" ;;
                down) slave_status="${RED}異常${NC}" ;;
                *)    slave_status="${YELLOW}${status:-未知}${NC}" ;;
            esac

            echo -e "  ${BOLD}${slave}${NC}"
            echo -e "    Link         ：${slave_status}"
            echo   "    Speed        ：${speed:-N/A}"
            echo   "    Permanent MAC：${perm_mac:-N/A}"
            [[ -n "$aggregator_id" ]] && echo "    Aggregator ID：$aggregator_id"
        done < <(
            awk '
                function flush() {
                    if (slave != "") print slave "|" status "|" speed "|" mac "|" agg
                }
                /^Slave Interface:/ { flush(); slave=$2; status=""; speed=""; mac=""; agg=""; next }
                /^MII Status:/           && slave != "" { status=$2; next }
                /^Speed:/                && slave != "" { speed=$2;  next }
                /^Permanent HW addr:/    && slave != "" { mac=$2;    next }
                /^Aggregator ID:/        && slave != "" { agg=$2;    next }
                END { flush() }
            ' FS=': ' "$bond_file"
        )
        echo
    done

    hr 80
}

# ── IP 位址 ───────────────────────────────────────────────────────────────

get_addresses() {
    local iface="$1" family="${2:-4}" addresses=""

    if command_exists ip; then
        addresses=$(ip -o "-$family" addr show dev "$iface" 2>/dev/null |
            awk '{print $4}' |
            paste -sd ',' -)
    fi

    printf '%s' "${addresses:--}"
}

# ── Linux Bridge ──────────────────────────────────────────────────────────

get_bridge_ports() {
    local bridge="$1" path="$SYS_NET_ROOT/$1/brif"

    if [[ -d "$path" ]]; then
        find "$path" -mindepth 1 -maxdepth 1 -printf '%f\n' 2>/dev/null |
            sort -V |
            paste -sd ',' -
    fi
}

list_bridges() {
    local bridge_path
    for bridge_path in "$SYS_NET_ROOT"/*/bridge; do
        [[ -d "$bridge_path" ]] || continue
        basename "$(dirname "$bridge_path")"
    done | sort -V
}

vlan_protocol_name() {
    case "$1" in
        0x8100) echo "802.1Q (0x8100)" ;;
        0x88a8|0x88A8) echo "802.1ad QinQ (0x88a8)" ;;
        *) echo "${1:-N/A}" ;;
    esac
}

render_bridges() {
    local -a bridges=()
    mapfile -t bridges < <(list_bridges)

    if ((${#bridges[@]} == 0)); then
        note "目前沒有執行中的 Linux Bridge。"
        return
    fi

    local bridge ports vlan_filtering stp_state proto pvid
    for bridge in "${bridges[@]}"; do
        ports=$(get_bridge_ports "$bridge")
        vlan_filtering=$(read_sysfs "$SYS_NET_ROOT/$bridge/bridge/vlan_filtering" "0")
        stp_state=$(read_sysfs "$SYS_NET_ROOT/$bridge/bridge/stp_state" "0")
        proto=$(read_sysfs "$SYS_NET_ROOT/$bridge/bridge/vlan_protocol" "")
        pvid=$(read_sysfs "$SYS_NET_ROOT/$bridge/bridge/default_pvid" "N/A")

        hr 80
        echo -e "${BOLD}Bridge${NC}          ：${CYAN}${bridge}${NC}"
        kv "綁定 Port" "${ports:-無}"
        kv "IPv4" "$(get_addresses "$bridge" 4)"
        kv "IPv6" "$(get_addresses "$bridge" 6)"
        kv "MTU" "$(get_mtu "$bridge")"
        kv "狀態" "$(get_operstate "$bridge")"

        if [[ "$vlan_filtering" == "1" ]]; then
            echo -e "$(pad "VLAN-aware" 16)：${GREEN}是${NC}"
            kv "VLAN 協定" "$(vlan_protocol_name "$proto")"
            kv "Default PVID" "$pvid"
        else
            echo -e "$(pad "VLAN-aware" 16)：${YELLOW}否${NC}"
        fi

        if [[ "$stp_state" == "1" ]]; then
            kv "STP" "啟用"
        else
            kv "STP" "停用"
        fi
        echo
    done

    hr 80
}

# ── Open vSwitch ──────────────────────────────────────────────────────────

render_ovs() {
    if ! command_exists ovs-vsctl; then
        note "未安裝 Open vSwitch（openvswitch-switch），略過。"
        echo "若此主機使用 Linux Bridge 建網，這是正常的。"
        return
    fi

    if ! ovs-vsctl show >/dev/null 2>&1; then
        note "ovs-vsctl 存在但無法連線 ovsdb（openvswitch-switch 服務可能未執行）。"
        echo "檢查指令：systemctl status openvswitch-switch"
        return
    fi

    local -a ovs_bridges=()
    mapfile -t ovs_bridges < <(ovs-vsctl list-br 2>/dev/null | sort -V)

    if ((${#ovs_bridges[@]} == 0)); then
        note "Open vSwitch 已安裝並執行，但沒有設定任何 OVS Bridge。"
        return
    fi

    local br port iface tag vlan_mode ports_line
    for br in "${ovs_bridges[@]}"; do
        hr 80
        echo -e "${BOLD}OVS Bridge${NC}      ：${CYAN}${br}${NC}"
        kv "MTU" "$(get_mtu "$br")"
        kv "IPv4" "$(get_addresses "$br" 4)"
        kv "IPv6" "$(get_addresses "$br" 6)"
        echo
        echo "  Port 明細："
        pad "  Port" 22; pad "VLAN Tag" 10; pad "VLAN 模式" 12; pad "成員介面" 40; echo
        thin_hr 84

        while read -r port; do
            [[ -n "$port" ]] || continue
            tag=$(ovs-vsctl get port "$port" tag 2>/dev/null | tr -d '\n')
            [[ "$tag" == "[]" || -z "$tag" ]] && tag="-"
            vlan_mode=$(ovs-vsctl get port "$port" vlan_mode 2>/dev/null | tr -d '\n')
            [[ "$vlan_mode" == "[]" || -z "$vlan_mode" ]] && vlan_mode="-"
            ports_line=$(ovs-vsctl list-ifaces "$port" 2>/dev/null | paste -sd ',' -)
            [[ -z "$ports_line" ]] && ports_line="$port"

            pad "  $port" 22; pad "$tag" 10; pad "$vlan_mode" 12; pad "$ports_line" 40; echo
        done < <(ovs-vsctl list-ports "$br" 2>/dev/null | sort -V)
        echo
    done

    hr 80

    if command_exists ovs-appctl; then
        local -a ovs_bonds=()
        mapfile -t ovs_bonds < <(ovs-appctl bond/list 2>/dev/null | awk 'NR>1 {print $1}')
        if ((${#ovs_bonds[@]} > 0)); then
            echo
            subsection "OVS Bond 狀態"
            local b
            for b in "${ovs_bonds[@]}"; do
                [[ -n "$b" ]] || continue
                echo
                echo "── $b ──"
                ovs-appctl bond/show "$b" 2>/dev/null || true
            done
        fi
    fi
}

# ── VLAN 子介面與 bridge vlan ─────────────────────────────────────────────

get_vlan_parent() {
    local vlan="$1" parent=""

    parent=$(ip -o link show "$vlan" 2>/dev/null |
        awk -F': ' '
            {
                name = $2
                gsub(/^[[:space:]]+|[[:space:]]+$/, "", name)
                if (name ~ /@/) { sub(/^.*@/, "", name); print name }
            }' |
        head -n1)

    printf '%s' "${parent:-N/A}"
}

get_vlan_id() {
    ip -d link show "$1" 2>/dev/null |
        awk '
            /vlan protocol/ {
                for (i = 1; i <= NF; i++) {
                    if ($i == "id") { print $(i + 1); exit }
                }
            }'
}

get_interface_type() {
    local iface="$1"

    if [[ -d "$SYS_NET_ROOT/$iface/bonding" ]]; then
        echo "Bond"
    elif [[ -d "$SYS_NET_ROOT/$iface/bridge" ]]; then
        echo "Linux Bridge"
    elif [[ -e "$SYS_NET_ROOT/$iface/device" ]]; then
        echo "實體網卡"
    elif [[ "$iface" == "N/A" || -z "$iface" ]]; then
        echo "未知"
    else
        echo "其他介面"
    fi
}

render_vlan_subinterfaces() {
    if ! command_exists ip; then
        note "找不到 ip 指令（iproute2）。"
        return
    fi

    local -a vlan_interfaces=()
    mapfile -t vlan_interfaces < <(
        ip -d -o link show type vlan 2>/dev/null |
            awk -F': ' '
                {
                    name = $2
                    gsub(/^[[:space:]]+|[[:space:]]+$/, "", name)
                    sub(/@.*/, "", name)
                    print name
                }' |
            sort -uV
    )

    subsection "傳統 VLAN 子介面"
    echo

    if ((${#vlan_interfaces[@]} == 0)); then
        note "目前沒有執行中的 VLAN 子介面。"
        return
    fi

    pad "VLAN 介面" 20; pad "VLAN ID" 10; pad "上層介面" 20
    pad "上層類型" 14;  pad "MTU" 7;      pad "狀態" 10; pad "IPv4" 22; echo
    hr 103

    local vlan parent
    for vlan in "${vlan_interfaces[@]}"; do
        parent=$(get_vlan_parent "$vlan")
        pad "$vlan" 20
        pad "$(get_vlan_id "$vlan")" 10
        pad "$parent" 20
        pad "$(get_interface_type "$parent")" 14
        pad "$(get_mtu "$vlan")" 7
        pad "$(get_operstate "$vlan")" 10
        pad "$(get_addresses "$vlan" 4)" 22
        echo
    done
}

# 展開 "100,200-203,300" → 逐個 VLAN ID（每行一個）
expand_vlan_list() {
    local list="${1:-}" part start end i
    [[ -n "$list" ]] || return 0

    local IFS=','
    for part in $list; do
        part="${part//[[:space:]]/}"
        [[ -n "$part" ]] || continue
        if [[ "$part" =~ ^([0-9]+)-([0-9]+)$ ]]; then
            start="${BASH_REMATCH[1]}"
            end="${BASH_REMATCH[2]}"
            for ((i = start; i <= end; i++)); do echo "$i"; done
        elif [[ "$part" =~ ^[0-9]+$ ]]; then
            echo "$part"
        fi
    done
}

# [ADD] v02.002.000：把逐個列出的 VLAN 壓回範圍表示。
#
# PVE 常見設定 `bridge-vids 2-4090`。當 bridge vlan show 是逐個列出（而非合併成
# 範圍）時，某個 port 的 VLAN 清單會串成 23432 字元的單行——實測即為此值。這一行
# 在終端會折行成約 300 行，把表頭與前面所有 port 全部推出畫面，使用者只看得到最後
# 一小段，前面的 VLAN 數字完全看不到。
#
# 壓縮後 23432 字元 → 10 字元（`1u,2-4090t`）。只有「連續且標記相同」才合併，
# 例如 1u,2u,3t 會壓成 1-2u,3t 而不會把 3t 併進去。
compress_vlan_list() {
    awk '
    # 解析單一 token。兩種形態都要支援：帶標記的 `100t`，以及去掉標記後的純數字
    # `100`（對帳走的是後者——bridge_vlan_for_port 會先把 u/t 濾掉）。
    # 抽成函式是因為主迴圈與內層前瞻都要做同一件事，各寫一次必然會漏掉其中一邊。
    function parse_item(item, res,   t, v) {
        t = substr(item, length(item), 1)
        v = substr(item, 1, length(item) - 1)
        if (t ~ /^[ut]$/ && v ~ /^[0-9]+$/) { res["vid"] = v + 0;    res["tag"] = t;  return 1 }
        if (item ~ /^[0-9]+$/)              { res["vid"] = item + 0; res["tag"] = ""; return 1 }
        return 0
    }
    {
        n = split($0, a, ",")
        out = ""; i = 1
        while (i <= n) {
            delete cur
            if (!parse_item(a[i], cur)) {
                # 其他形態（例如已經是範圍）原樣保留
                out = out (out == "" ? "" : ",") a[i]
                i++
                continue
            }

            tag = cur["tag"]; start = cur["vid"]; end = start; j = i + 1
            while (j <= n) {
                delete nxt
                if (!parse_item(a[j], nxt)) break
                if (nxt["tag"] != tag || nxt["vid"] != end + 1) break
                end = nxt["vid"]
                j++
            }

            out = out (out == "" ? "" : ",") (end > start ? start "-" end tag : start tag)
            i = j
        }
        print out
    }'
}

# 把逗號分隔清單折成多行，每行不超過指定寬度（VLAN 清單全為 ASCII，用位元組長度即可）。
# 壓縮過後仍可能很長——例如 100t,200t,300t… 這種不連續的清單壓不掉。
wrap_vlan_list() {
    local text="${1:--}" width="${2:-46}"
    awk -v w="$width" '
    {
        n = split($0, a, ",")
        line = ""
        for (i = 1; i <= n; i++) {
            item = a[i] (i < n ? "," : "")
            if (line != "" && length(line) + length(item) > w) {
                print line
                line = item
            } else {
                line = line item
            }
        }
        if (line != "") print line
    }' <<< "$text"
}

# 判斷某個 VLAN 是否落在清單內（清單可含 100 或 2-4090 這類範圍）。
#
# [CHANGE] v02.002.000：對帳改用本函式，不再把範圍展開成逐個值。
# 實測 `2-4090` 展開要 171 ms、建 4090 個關聯陣列鍵再花 586 ms，共約 757 ms，
# 而那是單一 bridge 單一 uplink 的成本；多 bridge 時會累加成數秒。
# 對帳實際只需查 guest 用到的那幾個 VLAN（通常不到 20 個），範圍比對即可。
vlan_in_list() {
    local vid="$1" list="${2:-}" part
    [[ "$vid" =~ ^[0-9]+$ ]] || return 1

    local IFS=','
    for part in $list; do
        part="${part//[[:space:]]/}"
        if [[ "$part" =~ ^([0-9]+)-([0-9]+)$ ]]; then
            ((vid >= BASH_REMATCH[1] && vid <= BASH_REMATCH[2])) && return 0
        elif [[ "$part" == "$vid" ]]; then
            return 0
        fi
    done
    return 1
}

# 判斷是否為 PVE 動態產生的 guest 介面（tap/veth/fw*）
is_guest_iface() {
    [[ "$1" =~ ^(tap|veth|fwbr|fwpr|fwln)[0-9] ]]
}

# 解析 stdin 上的 `bridge vlan show` 輸出。
# 該輸出是「首行帶 port 名，續行只有 VLAN」的縮排格式，且同一 port 的 VLAN 會跨多行。
# 輸出：port<TAB>vlan 清單（vid 後綴 u=Untagged / t=Tagged）<TAB>PVID
# 抽成獨立函式是為了能以已知輸入做自檢——這段格式解析沒有 rc 會變紅，錯了只會靜默少算。
parse_bridge_vlan() {
    awk '
        BEGIN { port = ""; vlans = ""; pvid = "-" }
        NR == 1 && $1 == "port" { next }
        {
            line = $0
            if (line ~ /^[^[:space:]]/) {
                if (port != "") print port "\t" vlans "\t" pvid
                split(line, f, /[[:space:]]+/)
                port = f[1]
                vlans = ""
                pvid = "-"
                rest = line
                # sub() 回傳替換次數；沒有第二欄時 rest 會原封不動，必須清空，
                # 否則 port 名會被當成 VLAN ID 收進清單。
                if (sub(/^[^[:space:]]+[[:space:]]+/, "", rest) == 0) rest = ""
            } else {
                rest = line
                gsub(/^[[:space:]]+/, "", rest)
            }
            if (rest == "") next
            split(rest, g, /[[:space:]]+/)
            vid = g[1]
            if (vid !~ /^[0-9]/) next
            if (rest ~ /PVID/) pvid = vid
            tag = (rest ~ /Untagged/) ? "u" : "t"
            vlans = (vlans == "") ? vid tag : vlans "," vid tag
        }
        END { if (port != "") print port "\t" vlans "\t" pvid }
    '
}

# 取出某個 port 在 `bridge vlan show` 輸出中放行的 VLAN（逗號分隔，保留 100-200 範圍寫法）
bridge_vlan_for_port() {
    local target="$1"
    awk -F'\t' -v t="$target" '$1 == t { print $2 }' |
        sed 's/[ut]\(,\|$\)/\1/g'
}

render_bridge_vlan() {
    subsection "Bridge VLAN Filter（逐 Port 放行清單）"
    echo

    if ! command_exists bridge; then
        note "找不到 bridge 指令，請確認已安裝 iproute2。"
        return
    fi

    local raw
    raw=$(bridge vlan show 2>/dev/null || true)

    if [[ -z "$raw" ]]; then
        note "目前沒有可顯示的 Bridge VLAN Filter 資訊。"
        echo "常見原因：所有 Linux Bridge 都未啟用 VLAN-aware（vlan_filtering=0）。"
        return
    fi

    # bridge vlan show 的輸出是「首行帶 port 名，續行只有 VLAN」的縮排格式，
    # 這裡整理成一行一個 port，並保留 PVID / Untagged 標記。
    pad "Port" 22; pad "類型" 14; pad "PVID" 7; pad "放行 VLAN" 46; echo
    hr 90

    local port_list
    port_list=$(parse_bridge_vlan <<< "$raw")

    local port vlans pvid ptype k
    local -a wrapped=()
    while IFS=$'\t' read -r port vlans pvid; do
        [[ -n "$port" ]] || continue
        if is_guest_iface "$port"; then
            ptype="Guest 介面"
        elif [[ -d "$SYS_NET_ROOT/$port/bridge" ]]; then
            ptype="Bridge 本身"
        else
            ptype="Uplink"
        fi

        # [CHANGE] v02.002.000：先壓成範圍再折行。
        # 舊版直接把整串 VLAN 塞進一個欄位，`bridge-vids 2-4090` 逐個列出時會是
        # 23432 字元的單行，在終端折成約 300 行把前面的內容全部推出畫面。
        vlans=$(compress_vlan_list <<< "${vlans:--}")
        mapfile -t wrapped < <(wrap_vlan_list "$vlans" 46)
        ((${#wrapped[@]} > 0)) || wrapped=("-")

        pad "$port" 22; pad "$ptype" 14; pad "$pvid" 7; printf '%s\n' "${wrapped[0]}"
        for ((k = 1; k < ${#wrapped[@]}; k++)); do
            printf '%s%s\n' "$(pad "" 43)" "${wrapped[k]}"
        done
    done <<< "$port_list"

    echo
    echo "說明：VLAN 後綴 u=Untagged、t=Tagged；PVID 欄為該 Port 的原生 VLAN。"
    echo "      連續的 VLAN 會壓成範圍顯示（例如 2-4090t），清單過長時折行續列。"
    echo "      「Uplink」指非 VM/CT 動態介面的實體網卡、Bond 或 VLAN 子介面。"
    echo
    subsection "bridge vlan show 原始輸出"
    echo
    printf '%s\n' "$raw"
}

# ── VM / CT 網卡對應 ──────────────────────────────────────────────────────
#
# PVE 的 guest 介面命名：VM = tap<vmid>i<n>、CT = veth<vmid>i<n>。
# 啟用 firewall=1 時實際接上 bridge 的是 fwpr<vmid>p<n>，guest 端接 fwbr<vmid>i<n>。
# 注意：guest conf 檔在第一個 [snapshot] 區段之後是快照內容，不是目前設定，必須截斷。

# 輸出：vmid<TAB>類型<TAB>名稱<TAB>netid<TAB>介面<TAB>MAC<TAB>bridge<TAB>tag<TAB>mtu<TAB>firewall
collect_guest_nics() {
    local conf vmid gname body line netid params iface
    local mac bridge tag mtu fw kind prefix

    local -a sources=()
    [[ -d "$PVE_CONF_ROOT/qemu-server" ]] && sources+=("qemu")
    [[ -d "$PVE_CONF_ROOT/lxc" ]] && sources+=("lxc")

    ((${#sources[@]} > 0)) || return 0

    local src dir
    for src in "${sources[@]}"; do
        if [[ "$src" == "qemu" ]]; then
            dir="$PVE_CONF_ROOT/qemu-server"; kind="VM"; prefix="tap"
        else
            dir="$PVE_CONF_ROOT/lxc"; kind="CT"; prefix="veth"
        fi

        for conf in "$dir"/*.conf; do
            [[ -f "$conf" ]] || continue
            vmid=$(basename "$conf" .conf)
            [[ "$vmid" =~ ^[0-9]+$ ]] || continue

            # 只取第一個 [snapshot] 之前的內容
            body=$(awk '/^\[/ { exit } { print }' "$conf" 2>/dev/null)
            gname=$(awk -F': *' '/^(name|hostname):/ { print $2; exit }' <<< "$body")

            while IFS= read -r line; do
                [[ -n "$line" ]] || continue
                netid="${line%%:*}"
                params="${line#*:}"
                params="${params# }"

                iface="${prefix}${vmid}i${netid#net}"
                mac=""; bridge=""; tag=""; mtu=""; fw="0"

                # [CHANGE] 改用 here-string 逐行解析，不動 IFS。函式內 local IFS 會影響
                #          整個函式 scope（bash 沒有 block scope），連帶影響外層 read。
                local kvpair k v
                while IFS= read -r kvpair; do
                    [[ -n "$kvpair" ]] || continue
                    k="${kvpair%%=*}"
                    v="${kvpair#*=}"
                    case "$k" in
                        bridge)   bridge="$v" ;;
                        tag)      tag="$v" ;;
                        mtu)      mtu="$v" ;;
                        firewall) fw="$v" ;;
                        hwaddr)   mac="$v" ;;
                        virtio|e1000|e1000e|rtl8139|vmxnet3|i82551|i82557b|i82559er|ne2k_pci|ne2k_isa|pcnet)
                            mac="$v" ;;
                    esac
                done <<< "$(tr ',' '\n' <<< "$params")"

                printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
                    "$vmid" "$kind" "${gname:--}" "$netid" "$iface" \
                    "${mac:--}" "${bridge:--}" "${tag:--}" "${mtu:--}" "$fw"
            done < <(grep -E '^net[0-9]+:' <<< "$body")
        done
    done
}

render_guest_nics() {
    if [[ ! -d "$PVE_CONF_ROOT" ]]; then
        note "找不到 $PVE_CONF_ROOT，此主機可能不是 Proxmox VE。"
        return
    fi

    local rows
    rows=$(collect_guest_nics | sort -t $'\t' -k1,1n -k4,4V)

    if [[ -z "$rows" ]]; then
        note "沒有找到任何已設定網卡的 VM 或 CT。"
        return
    fi

    subsection "VM / CT 網卡對應"
    echo

    # [CHANGE] v02.001.000：窄終端自動改用逐筆區塊。
    if use_table "$TABLE_MIN_WIDTH_GUEST"; then
        render_guest_nics_table <<< "$rows"
    else
        render_guest_nics_blocks <<< "$rows"
    fi

    echo
    echo "說明：「介面狀態」為該介面目前是否存在於 sysfs，即該 guest 是否正在執行。"
    echo "      防火牆啟用時，實際接上 bridge 的是 fwpr<vmid>p<n>，"
    echo "      guest 端接 fwbr<vmid>i<n>。"
}

# guest 介面是否已存在（即 guest 是否執行中）。回傳「狀態<TAB>顏色」。
_guest_iface_state() {
    if [[ -e "$SYS_NET_ROOT/$1" ]]; then
        printf '執行中\t%s' "$GREEN"
    else
        printf '未執行\t%s' "$YELLOW"
    fi
}

render_guest_nics_table() {
    pad "VMID" 7;    pad "類型" 7;  pad "名稱" 24; pad "網卡" 7
    pad "介面" 16;   pad "MAC" 19;  pad "Bridge" 11
    pad "VLAN Tag" 10; pad "MTU" 7; pad "防火牆" 9; pad "介面狀態" 11; echo
    hr 136

    local vmid kind gname netid iface mac bridge tag mtu fw state color
    while IFS=$'\t' read -r vmid kind gname netid iface mac bridge tag mtu fw; do
        [[ -n "$vmid" ]] || continue
        IFS=$'\t' read -r state color < <(_guest_iface_state "$iface")

        pad "$vmid" 7; pad "$kind" 7; pad "$gname" 24; pad "$netid" 7
        pad "$iface" 16; pad "$mac" 19; pad "$bridge" 11
        padc "$tag" 10 "$( [[ "$tag" != "-" ]] && printf '%s' "$CYAN" )"
        pad "$mtu" 7
        pad "$( [[ "$fw" == "1" ]] && echo "啟用" || echo "停用" )" 9
        padc "$state" 11 "$color"
        echo
    done
}

render_guest_nics_blocks() {
    local vmid kind gname netid iface mac bridge tag mtu fw state color
    while IFS=$'\t' read -r vmid kind gname netid iface mac bridge tag mtu fw; do
        [[ -n "$vmid" ]] || continue
        IFS=$'\t' read -r state color < <(_guest_iface_state "$iface")

        echo -e "${BOLD}── ${CYAN}${kind} ${vmid}${NC}${BOLD} ${gname} / ${netid} ──${NC}"
        # 每行最後一個欄位不補白，避免留下看不見的尾隨空白
        printf '%s：%s  %s：%s%s%s\n' \
            "$(pad "介面" 10)" "$(pad "$iface" 17)" "狀態" "$color" "$state" "$NC"
        printf '%s：%s\n' "$(pad "MAC" 10)" "$mac"
        printf '%s：%s  %s：%s%s%s\n' \
            "$(pad "Bridge" 10)" "$(pad "$bridge" 17)" \
            "VLAN Tag" "$( [[ "$tag" != "-" ]] && printf '%s' "$CYAN" )" "$tag" "$NC"
        printf '%s：%s  %s：%s\n' \
            "$(pad "MTU" 10)" "$(pad "$mtu" 17)" \
            "防火牆" "$( [[ "$fw" == "1" ]] && echo "啟用" || echo "停用" )"
        echo
    done
}

# ── VLAN 對帳：guest 用到的 VLAN vs Uplink 實際放行的 VLAN ────────────────

render_vlan_reconcile() {
    subsection "VLAN 對帳：Guest 使用的 VLAN vs Bridge Uplink 放行的 VLAN"
    echo

    if ! command_exists bridge; then
        note "找不到 bridge 指令，無法對帳。"
        return
    fi

    local raw
    raw=$(bridge vlan show 2>/dev/null || true)

    if [[ -z "$raw" ]]; then
        note "沒有 VLAN-aware Bridge，無需對帳。"
        echo "若你的 VLAN 是以「傳統 VLAN 子介面 + 每 VLAN 一個 Bridge」方式建置，這是正常的。"
        return
    fi

    # 收集每個 bridge 的 uplink 放行 VLAN。
    # [CHANGE] v02.002.000：保留原始清單字串（含 2-4090 這類範圍），不再展開成
    # 逐個值——展開 2-4090 要 171 ms、建 4090 個關聯陣列鍵再花 586 ms，而對帳
    # 實際只需查 guest 用到的那幾個 VLAN。
    declare -A UPLINK_VLAN_LIST=()
    declare -A UPLINK_PORTS=()

    local -a bridges=()
    mapfile -t bridges < <(list_bridges)

    # [CHANGE] 與 render_bridge_vlan 共用同一份 parse_bridge_vlan，不再各自解析一遍。
    #          兩套解析同一格式必然漂移，這正是舊版 show_*/report_* 的老問題。
    local parsed
    parsed=$(parse_bridge_vlan <<< "$raw")

    local bridge port vlans vid
    for bridge in "${bridges[@]}"; do
        [[ "$(read_sysfs "$SYS_NET_ROOT/$bridge/bridge/vlan_filtering" "0")" == "1" ]] || continue

        while read -r port; do
            [[ -n "$port" ]] || continue
            is_guest_iface "$port" && continue
            [[ "$port" == "$bridge" ]] && continue

            # 先壓成範圍再存：uplink 放行 2-4090 時，未壓縮的清單是 19342 字元，
            # vlan_in_list 對它每查一個 VLAN 就要迭代 4090 次。
            vlans=$(bridge_vlan_for_port "$port" <<< "$parsed" | compress_vlan_list)

            [[ -n "$vlans" ]] || continue
            UPLINK_PORTS["$bridge"]="${UPLINK_PORTS[$bridge]:+${UPLINK_PORTS[$bridge]},}$port"
            UPLINK_VLAN_LIST["$bridge"]="${UPLINK_VLAN_LIST[$bridge]:+${UPLINK_VLAN_LIST[$bridge]},}$vlans"
        done < <(get_bridge_ports "$bridge" | tr ',' '\n')
    done

    if ((${#UPLINK_PORTS[@]} == 0)); then
        note "VLAN-aware Bridge 上沒有可辨識的 Uplink Port（實體網卡／Bond／VLAN 子介面）。"
        return
    fi

    local rows
    rows=$(collect_guest_nics)

    if [[ -z "$rows" ]]; then
        note "沒有 guest 網卡可對帳。"
        return
    fi

    pad "Bridge" 12; pad "Uplink Port" 26; pad "Guest 用到的 VLAN" 24
    pad "Uplink 未放行" 22; pad "判定" 10; echo
    hr 96

    local vmid kind gname netid iface mac gbridge tag mtu fw
    local -A guest_vlans=()
    while IFS=$'\t' read -r vmid kind gname netid iface mac gbridge tag mtu fw; do
        [[ -n "$gbridge" && "$gbridge" != "-" ]] || continue
        [[ -n "$tag" && "$tag" != "-" ]] || continue
        guest_vlans["$gbridge|$tag"]="${guest_vlans[$gbridge|$tag]:+${guest_vlans[$gbridge|$tag]} }${vmid}"
    done <<< "$rows"

    local key b v used missing verdict color
    for bridge in "${bridges[@]}"; do
        [[ -n "${UPLINK_PORTS[$bridge]:-}" ]] || continue

        used=""; missing=""
        for key in "${!guest_vlans[@]}"; do
            b="${key%%|*}"; v="${key##*|}"
            [[ "$b" == "$bridge" ]] || continue
            used="${used:+$used,}$v"
            if ! vlan_in_list "$v" "${UPLINK_VLAN_LIST[$bridge]:-}"; then
                missing="${missing:+$missing,}${v}(VM ${guest_vlans[$key]})"
            fi
        done

        [[ -n "$used" ]] || used="-"
        used=$(tr ',' '\n' <<< "$used" | sort -uV | paste -sd ',' -)

        if [[ -n "$missing" ]]; then
            verdict="需檢查"; color="$RED"
        else
            verdict="相符"; color="$GREEN"
        fi

        pad "$bridge" 12
        pad "${UPLINK_PORTS[$bridge]}" 26
        pad "$used" 24
        pad "${missing:--}" 22
        padc "$verdict" 10 "$color"
        echo
    done

    echo
    echo "說明：「Uplink 未放行」列出 guest 設了 VLAN tag，但該 Bridge 的 Uplink Port 在"
    echo "      bridge vlan 放行清單中查無此 VLAN 的情形，是 VLAN 不通最常見的原因。"
    echo "      若你的交換器 Port 設為 access（不打 tag），guest 端不應再設 tag，屬另一種情形。"
}

# ── PVE SDN ───────────────────────────────────────────────────────────────

render_sdn() {
    local sdn_dir="$PVE_CONF_ROOT/sdn"

    if [[ ! -d "$sdn_dir" ]]; then
        note "找不到 $sdn_dir，此主機未使用 PVE SDN（或非 Proxmox VE）。"
        return
    fi

    local found=0 f
    for f in zones vnets subnets controllers ipams dns; do
        [[ -f "$sdn_dir/$f.cfg" ]] || continue
        [[ -s "$sdn_dir/$f.cfg" ]] || continue
        found=1
        echo
        subsection "── $f.cfg ──"
        grep -Ev '^[[:space:]]*(#|$)' "$sdn_dir/$f.cfg" 2>/dev/null || true
    done

    if ((found == 0)); then
        note "SDN 目錄存在但沒有任何設定內容。"
        return
    fi

    if command_exists pvesh; then
        echo
        subsection "SDN 執行期狀態（pvesh get /cluster/sdn）"
        pvesh get /cluster/sdn --output-format text 2>/dev/null ||
            note "無法取得 SDN 執行期狀態。"
    fi
}

# ── 叢集網路（corosync）───────────────────────────────────────────────────

render_corosync() {
    local conf="$PVE_CONF_ROOT/corosync.conf"

    if [[ ! -f "$conf" ]]; then
        note "找不到 $conf，此主機未加入叢集（單機 PVE 屬正常）。"
        return
    fi

    subsection "corosync 環網設定"
    echo
    awk '
        /^[[:space:]]*node[[:space:]]*{/ { in_node = 1; name = ""; r0 = ""; r1 = ""; nid = "" }
        in_node && /name:/       { gsub(/^[[:space:]]*name:[[:space:]]*/, ""); name = $0 }
        in_node && /nodeid:/     { gsub(/^[[:space:]]*nodeid:[[:space:]]*/, ""); nid = $0 }
        in_node && /ring0_addr:/ { gsub(/^[[:space:]]*ring0_addr:[[:space:]]*/, ""); r0 = $0 }
        in_node && /ring1_addr:/ { gsub(/^[[:space:]]*ring1_addr:[[:space:]]*/, ""); r1 = $0 }
        in_node && /^[[:space:]]*}/ {
            in_node = 0
            printf "  節點 %-16s nodeid=%-4s ring0=%-20s ring1=%s\n", name, nid, r0, (r1 == "" ? "（未設定）" : r1)
        }
        /^[[:space:]]*(cluster_name|transport|secauth|crypto_cipher|link_mode):/ {
            gsub(/^[[:space:]]+/, ""); print "  " $0
        }
    ' "$conf"

    echo
    if [[ -z "$(awk '/ring1_addr:/ {print}' "$conf")" ]]; then
        note "  ⚠ 未偵測到 ring1_addr：corosync 只有單一環網，該網路中斷即失去 quorum。"
    fi

    if command_exists corosync-cfgtool; then
        echo
        subsection "corosync 環網即時狀態"
        echo
        corosync-cfgtool -s 2>/dev/null || note "無法取得 corosync 環網狀態（服務可能未執行）。"
    fi

    if command_exists pvecm; then
        echo
        subsection "pvecm status"
        echo
        pvecm status 2>/dev/null || note "無法取得 pvecm status。"
    fi
}

# ── IP / 路由 / DNS / hosts / 鄰居 ────────────────────────────────────────

render_ip_routing() {
    if ! command_exists ip; then
        note "找不到 ip 指令（iproute2）。"
        return
    fi

    subsection "所有介面 IP 位址（IPv4）"
    echo
    ip -br -4 addr show 2>/dev/null || true

    echo
    subsection "所有介面 IP 位址（IPv6）"
    echo
    ip -br -6 addr show 2>/dev/null || true

    echo
    subsection "IPv4 路由表"
    echo
    ip -4 route show 2>/dev/null || true

    echo
    subsection "IPv6 路由表"
    echo
    ip -6 route show 2>/dev/null | print_limited "$LIST_LIMIT" "條路由"

    echo
    subsection "DNS 設定（/etc/resolv.conf）"
    echo
    if [[ -f /etc/resolv.conf ]]; then
        grep -Ev '^[[:space:]]*(#|$)' /etc/resolv.conf || true
    else
        note "找不到 /etc/resolv.conf。"
    fi

    echo
    subsection "/etc/hosts（PVE 叢集節點解析的依據）"
    echo
    if [[ -f /etc/hosts ]]; then
        grep -Ev '^[[:space:]]*(#|$)' /etc/hosts || true
    else
        note "找不到 /etc/hosts。"
    fi

    echo
    subsection "鄰居表（ARP / NDP，僅列 REACHABLE 與 STALE）"
    echo
    ip neigh show 2>/dev/null | grep -E 'REACHABLE|STALE' | print_limited "$LIST_LIMIT" "筆鄰居"
    echo
    echo "註：本表已先濾掉 FAILED / INCOMPLETE 等狀態，非完整鄰居表；"
    echo "    完整內容請執行 ip neigh show。"
}

# ── PVE 防火牆 ────────────────────────────────────────────────────────────

render_firewall() {
    if ! command_exists pve-firewall; then
        note "找不到 pve-firewall，此主機可能不是 Proxmox VE。"
        return
    fi

    subsection "pve-firewall status"
    echo
    pve-firewall status 2>/dev/null || note "無法取得防火牆狀態。"

    local fw_dir="$PVE_CONF_ROOT/firewall"
    if [[ -d "$fw_dir" ]]; then
        local f
        for f in "$fw_dir"/*.fw; do
            [[ -f "$f" ]] || continue
            echo
            subsection "── $f ──"
            grep -Ev '^[[:space:]]*(#|$)' "$f" 2>/dev/null || true
        done
    fi

    if [[ -f "$PVE_CONF_ROOT/local/host.fw" ]]; then
        echo
        subsection "── 本節點 host.fw ──"
        grep -Ev '^[[:space:]]*(#|$)' "$PVE_CONF_ROOT/local/host.fw" 2>/dev/null || true
    fi
}

# ── LLDP ──────────────────────────────────────────────────────────────────

render_lldp() {
    if ! command_exists lldpcli; then
        note "尚未安裝 lldpd，無法查詢交換器與 Port。"
        echo
        echo "安裝並啟用："
        echo "  apt update"
        echo "  apt install -y lldpd"
        echo "  systemctl enable --now lldpd"
        echo
        echo "交換器端也必須啟用 LLDP。"
        return
    fi

    if ! systemctl is-active --quiet lldpd 2>/dev/null; then
        note "lldpd 目前未執行。"
        echo "啟動指令：systemctl enable --now lldpd"
        echo
    fi

    local output
    output=$(lldpcli show neighbors details 2>/dev/null || true)

    if [[ -z "$output" ]]; then
        note "目前沒有收到 LLDP 鄰居資訊。"
        echo
        echo "請確認："
        echo "  1. lldpd 已執行"
        echo "  2. 交換器已啟用 LLDP"
        echo "  3. PVE 網卡直接連到交換器"
        return
    fi

    subsection "鄰居摘要"
    echo
    pad "本機介面" 16; pad "交換器名稱" 30; pad "對端 Port" 24; pad "Port 說明" 30; echo
    hr 100
    awk '
        /^Interface:/ {
            if (iface != "") printf "%s\t%s\t%s\t%s\n", iface, sysname, portid, portdesc
            split($0, f, /[,:]/)
            iface = f[2]
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", iface)
            sysname = ""; portid = ""; portdesc = ""
        }
        /^[[:space:]]*SysName:/  { v = $0; sub(/^[^:]*:[[:space:]]*/, "", v); if (sysname  == "") sysname  = v }
        /^[[:space:]]*PortID:/   { v = $0; sub(/^[^:]*:[[:space:]]*/, "", v); if (portid   == "") portid   = v }
        /^[[:space:]]*PortDescr:/{ v = $0; sub(/^[^:]*:[[:space:]]*/, "", v); if (portdesc == "") portdesc = v }
        END { if (iface != "") printf "%s\t%s\t%s\t%s\n", iface, sysname, portid, portdesc }
    ' <<< "$output" |
    while IFS=$'\t' read -r iface sysname portid portdesc; do
        [[ -n "$iface" ]] || continue
        pad "$iface" 16; pad "${sysname:--}" 30; pad "${portid:--}" 24; pad "${portdesc:--}" 30; echo
    done

    echo
    subsection "完整鄰居明細"
    echo
    printf '%s\n' "$output"
}

# ── /etc/network/interfaces ───────────────────────────────────────────────

render_persistent_config() {
    if [[ ! -f "$NET_CONF_FILE" ]]; then
        note "找不到 $NET_CONF_FILE。"
        return
    fi

    subsection "── $NET_CONF_FILE ──"
    grep -Ev '^[[:space:]]*(#|$)' "$NET_CONF_FILE" || true

    if [[ -d "$NET_CONF_DIR" ]]; then
        local file
        for file in "$NET_CONF_DIR"/*; do
            [[ -f "$file" ]] || continue
            echo
            subsection "── $file ──"
            grep -Ev '^[[:space:]]*(#|$)' "$file" || true
        done
    fi

    if [[ -f "$NET_CONF_FILE.new" ]]; then
        echo
        note "⚠ 偵測到 $NET_CONF_FILE.new：有網路設定已修改但尚未套用（需 reboot 或 ifreload -a）。"
    fi
}

# ── LED 定位（互動專用）───────────────────────────────────────────────────

# LED 定位的網卡選單。
#
# [CHANGE] v02.002.001：Link 欄補上顏色。
#   舊版直接印 get_link_plain（無色版），而其他所有表格都是 padc 搭 link_color 上色，
#   於是唯獨這一頁的「已接線／未接線」是白的——實地回報才發現。
#   抽成獨立函式是為了讓自檢測得到：identify_nic_led 本身要 read 使用者輸入，
#   自檢無法直接跑它，「有沒有上色」這件事就永遠沒有人守。
render_nic_pick_list() {
    local i nic
    for i in "${!PHYSICAL_NICS[@]}"; do
        nic="${PHYSICAL_NICS[$i]}"
        printf "  %2d) %s MAC=%s Link=%s%s%s\n" \
            "$((i + 1))" \
            "$(pad "$nic" 16)" \
            "$(pad "$(get_mac "$nic")" 19)" \
            "$(link_color "$nic")" "$(get_link_plain "$nic")" "$NC"
    done
}

identify_nic_led() {
    clear_screen
    print_header
    refresh_physical_nics

    if ! command_exists ethtool; then
        echo -e "${RED}需要 ethtool 才能執行網卡 LED 定位。${NC}"
        echo "安裝指令：apt update && apt install -y ethtool"
        pause_screen
        return
    fi

    if ((${#PHYSICAL_NICS[@]} == 0)); then
        echo -e "${RED}找不到實體網卡。${NC}"
        pause_screen
        return
    fi

    section "選擇要定位的實體網卡"

    render_nic_pick_list

    echo "   0) 返回"
    echo
    read -r -p "請輸入選項：" choice

    [[ "$choice" == "0" ]] && return

    if ! [[ "$choice" =~ ^[0-9]+$ ]] || ((choice < 1 || choice > ${#PHYSICAL_NICS[@]})); then
        echo -e "${RED}選項無效。${NC}"
        pause_screen
        return
    fi

    nic="${PHYSICAL_NICS[$((choice - 1))]}"

    echo
    echo -e "正在讓 ${CYAN}${nic}${NC} 的 LED 閃爍 ${BLINK_SECONDS} 秒（此期間畫面會停住）..."

    if ethtool -p "$nic" "$BLINK_SECONDS" 2>/dev/null; then
        echo -e "${GREEN}LED 定位完成。${NC}"
    else
        echo -e "${YELLOW}此網卡或驅動不支援 LED 定位。${NC}"
        echo "可使用另一個終端執行 ip monitor link，再由現場拔插線確認。"
    fi

    pause_screen
}

# ── 報告輸出 ──────────────────────────────────────────────────────────────

REPORT_SECTIONS=(
    "實體網卡狀態|render_physical_nics"
    "網卡健康指標|render_nic_health"
    "SFP/QSFP 模組明細|render_nic_modules"
    "Bond|render_bonds"
    "Linux Bridge|render_bridges"
    "Open vSwitch|render_ovs"
    "VLAN 子介面|render_vlan_subinterfaces"
    "Bridge VLAN Filter|render_bridge_vlan"
    "VM/CT 網卡對應|render_guest_nics"
    "VLAN 對帳|render_vlan_reconcile"
    "PVE SDN|render_sdn"
    "叢集網路 corosync|render_corosync"
    "IP / 路由 / DNS / hosts|render_ip_routing"
    "PVE 防火牆|render_firewall"
    "LLDP|render_lldp"
    "持久化設定 interfaces|render_persistent_config"
)

generate_full_report() {
    local quiet="${1:-0}"
    local saved_color="$USE_COLOR"

    mkdir -p "$REPORT_DIR" 2>/dev/null || {
        echo -e "${RED}無法建立報告目錄：$REPORT_DIR${NC}" >&2
        return 1
    }

    REPORT_FILE="${REPORT_DIR}/pve-network-audit-$(hostname)-$(date +%Y%m%d-%H%M%S).txt"

    # [CHANGE] v02.000.001：以 0600 建立報告檔。
    # 報告內含 corosync 叢集拓撲與各節點 IP、防火牆規則、/etc/hosts、完整路由表，
    # 屬敏感內容。REPORT_DIR 預設 /root（0700）雖安全，但一旦被指到 /var/log 這類
    # 0755 目錄，同機任何使用者都讀得到。故不倚賴目錄權限，直接釘死檔案權限。
    ( umask 077; : > "$REPORT_FILE" ) || {
        echo -e "${RED}無法建立報告檔：$REPORT_FILE${NC}" >&2
        return 1
    }
    chmod 600 "$REPORT_FILE" 2>/dev/null || true

    # [CHANGE] 報告一律不著色（舊版在 tty 下產生報告時顏色變數仍有值）
    USE_COLOR=0
    setup_colors
    reset_caches

    {
        echo "PVE 網路完整盤查報告"
        echo "主機名稱：$(hostname)"
        echo "核心版本：$(uname -r)"
        echo "PVE 版本：$(command_exists pveversion && pveversion 2>/dev/null | head -1 || echo 'N/A')"
        echo "產生時間：$(date '+%Y-%m-%d %H:%M:%S')"
        echo "工具版本：$VERSION"
    } > "$REPORT_FILE"

    local entry title fn
    for entry in "${REPORT_SECTIONS[@]}"; do
        title="${entry%%|*}"
        fn="${entry##*|}"

        [[ "$quiet" == "1" ]] || echo "  產生中：$title"

        {
            echo
            echo "################################################################################"
            echo "# $title"
            echo "################################################################################"
            echo
            "$fn"
        } >> "$REPORT_FILE" 2>&1
    done

    USE_COLOR="$saved_color"
    setup_colors

    echo
    echo -e "${GREEN}完整盤查報告已產生：${NC}"
    echo "$REPORT_FILE"
}

# ── 內建自檢 ──────────────────────────────────────────────────────────────
#
# 量測工具本身也可能有缺陷，故對「有已知正確答案」的純函式做比對，
# 讓判定邏輯的迴歸在使用前就會被發現，而不是在盤查報告裡以錯誤結論呈現。

# 自檢用的模擬 ethtool -m 輸出。刻意保留真實輸出中會出現的 "Transceiver" 與
# "Optical diagnostics support" 兩個欄位——v01 的整份 grep 就是被這兩者誤導的。
sample_module_dump() {
    case "$1" in
        dac)
            cat <<'EOF'
	Identifier                                : 0x03 (SFP)
	Connector                                 : 0x23 (No separable connector)
	Transceiver codes                         : 0x00 0x00 0x00 0x01
	Transceiver type                          : 10G Ethernet: 10G Base-CR
	Encoding                                  : 0x00 (unspecified)
	Length (SMF,km)                           : 0km
	Length (SMF)                              : 0m
	Length (50um)                             : 0m
	Length (62.5um)                           : 0m
	Length (Copper)                           : 3m
	Length (OM3)                              : 0m
	Vendor name                               : FS
	Vendor PN                                 : SFP-H10GB-CU3M
	Optical diagnostics support               : No
EOF
            ;;
        fiber)
            cat <<'EOF'
	Identifier                                : 0x03 (SFP)
	Connector                                 : 0x07 (LC)
	Transceiver type                          : 10G Ethernet: 10G Base-SR
	Encoding                                  : 0x06 (64B/66B)
	Length (SMF,km)                           : 0km
	Length (SMF)                              : 0m
	Length (50um)                             : 80m
	Length (62.5um)                           : 30m
	Length (Copper)                           : 0m
	Length (OM3)                              : 300m
	Vendor name                               : FS
	Vendor PN                                 : SFP-10GSR-85
	Optical diagnostics support               : Yes
	Laser output power                        : 0.5623 mW / -2.50 dBm
EOF
            ;;
        aoc)
            cat <<'EOF'
	Identifier                                : 0x0d (QSFP+)
	Connector                                 : 0x23 (No separable connector)
	Transceiver type                          : 40G Ethernet: 40G Active Cable (XLPPI)
	Cable technology                          : Active Cable
	Length (SMF,km)                           : 0km
	Length (OM3)                              : 0m
	Length (Copper)                           : 10m
	Vendor name                               : FS
	Vendor PN                                 : QSFP-AO10
EOF
            ;;
        rj45sfp)
            # 1000BASE-T SFP 銅口模組：Connector 是 RJ45，Length (Copper) 填 100m。
            # 若不先攔 RJ45，線長判準會把它判成 DAC（v02 開發過程實測確認過）。
            cat <<'EOF'
	Identifier                                : 0x03 (SFP)
	Connector                                 : 0x22 (RJ45)
	Transceiver type                          : Ethernet: 1000BASE-T
	Length (SMF,km)                           : 0km
	Length (SMF)                              : 0m
	Length (50um)                             : 0m
	Length (62.5um)                           : 0m
	Length (Copper)                           : 100m
	Length (OM3)                              : 0m
	Vendor name                               : FS
	Vendor PN                                 : SFP-GB-GE-T
EOF
            ;;
        rj45sfp_bare)
            # Connector 是 RJ45 但 Transceiver type 欄位缺失（EEPROM 不完整的模組）。
            # (2a) 有兩個條件（Connector 為 RJ45／type 含 BASE-T），上面的 rj45sfp
            # 樣本兩者都滿足 ⇒ 拿掉任一個都不會讓測試變紅。這個樣本只滿足前者。
            cat <<'EOF'
	Identifier                                : 0x03 (SFP)
	Connector                                 : 0x22 (RJ45)
	Length (SMF,km)                           : 0km
	Length (SMF)                              : 0m
	Length (50um)                             : 0m
	Length (62.5um)                           : 0m
	Length (Copper)                           : 100m
	Length (OM3)                              : 0m
	Vendor PN                                 : SFP-GB-GE-T
EOF
            ;;
        baset_noconn)
            # 反面：type 含 10GBASE-T 但 Connector 不是 RJ45，只滿足 (2a) 的後者。
            cat <<'EOF'
	Identifier                                : 0x03 (SFP+)
	Connector                                 : 0x23 (No separable connector)
	Transceiver type                          : 10G Ethernet: 10GBASE-T
	Length (Copper)                           : 30m
EOF
            ;;
        dac_nolen)
            # 線長欄位全部缺失的 DAC，只能靠 Cable technology 判定。
            # 這個案例是「optical_len > 0 的 > 0」唯一會被觸及的路徑：
            # 少了它，把該條件放寬成 >= 0 的突變不會讓任何測試變紅。
            cat <<'EOF'
	Identifier                                : 0x0d (QSFP+)
	Connector                                 : 0x23 (No separable connector)
	Transceiver type                          : 40G Ethernet: 40G Base-CR4
	Cable technology                          : Passive Cable
	Vendor name                               : FS
	Vendor PN                                 : QSFP-PC005
EOF
            ;;
    esac
}

self_test() {
    local pass=0 fail=0 skipped=0

    # 平台不支援而無法驗證的項目，MUST 明確標為 SKIP 並計數——不可讓「驗不了」
    # 靜靜混進「全部通過」，那會讓一項從未被檢查的判準看起來像已經過關。
    skip() {
        printf '  [SKIP] %s%s\n' "$(pad "$1" 46)" "$2"
        skipped=$((skipped + 1))
    }

    check() {
        local name="$1" expected="$2" actual="$3"
        if [[ "$expected" == "$actual" ]]; then
            printf '  [ OK ] %s= %s\n' "$(pad "$name" 46)" "$actual"
            pass=$((pass + 1))
        else
            printf '  [FAIL] %s預期=[%s] 實得=[%s]\n' "$(pad "$name" 46)" "$expected" "$actual"
            fail=$((fail + 1))
        fi
    }

    echo "PVE 網路盤查工具 v${VERSION} — 內建自檢"
    echo

    subsection "1. 顯示寬度計算（CJK 全形計 2 欄）"
    check "str_width 'Link'"          "4"  "$(str_width "Link")"
    check "str_width '已接線'"        "6"  "$(str_width "已接線")"
    check "str_width '未知'"          "4"  "$(str_width "未知")"
    check "str_width 'RJ45 電口'"     "9"  "$(str_width "RJ45 電口")"
    check "str_width 'SFP/QSFP 模組'" "13" "$(str_width "SFP/QSFP 模組")"
    check "pad 補白後總寬（欄寬 10）" "10" "$(str_width "$(pad "已接線" 10)")"
    check "pad 超寬不截斷"            "13" "$(str_width "$(pad "SFP/QSFP 模組" 10)")"

    echo
    subsection "2. VLAN 清單展開"
    check "expand_vlan_list '100'"           "100"                 "$(expand_vlan_list "100" | paste -sd ',' -)"
    check "expand_vlan_list '10,20-23,30'"   "10,20,21,22,23,30"   "$(expand_vlan_list "10,20-23,30" | paste -sd ',' -)"
    check "expand_vlan_list ''（空輸入）"    ""                    "$(expand_vlan_list "" | paste -sd ',' -)"

    echo
    subsection "3. 欄位值擷取（只取值，不回整行）"
    local sample=$'Identifier      : 0x03 (SFP)\nConnector       : 0x07 (LC)\nTransceiver type: 10G Ethernet: 10G Base-SR'
    check "field_value Connector"        "0x07 (LC)"                    "$(field_value "$sample" "Connector")"
    check "field_value 'Transceiver type'" "10G Ethernet: 10G Base-SR"  "$(field_value "$sample" "Transceiver type")"
    check "field_value 不存在的欄位"     ""                             "$(field_value "$sample" "NoSuchField")"

    echo
    subsection "4. 數值前綴擷取"
    check "numeric_prefix '3m'"    "3" "$(numeric_prefix "3m")"
    check "numeric_prefix '0km'"   "0" "$(numeric_prefix "0km")"
    check "numeric_prefix ''"      "0" "$(numeric_prefix "")"
    check "numeric_prefix 'N/A'"   "0" "$(numeric_prefix "N/A")"

    echo
    subsection "5. read_sysfs 讀取失敗時回預設值（不外洩錯誤）"
    local td err
    td=$(mktemp -d)
    mkdir -p "$td/not_a_file"
    err=$(read_sysfs "$td/not_a_file" "N/A" 2>&1 >/dev/null)
    check "可讀但讀取失敗 → 回預設值" "N/A" "$(read_sysfs "$td/not_a_file" "N/A" 2>/dev/null)"
    check "不存在的路徑 → 回預設值"   "N/A" "$(read_sysfs "$td/nope" "N/A" 2>/dev/null)"
    check "stderr 無外洩"             ""    "$err"
    printf 'hello\n' > "$td/real"
    check "正常檔案 → 回內容（陽性對照）" "hello" "$(read_sysfs "$td/real" "N/A")"
    rm -rf "$td"

    echo
    subsection "6. Guest 介面命名判定"
    check "tap100i0 為 guest 介面"  "yes" "$(is_guest_iface "tap100i0"  && echo yes || echo no)"
    check "veth101i0 為 guest 介面" "yes" "$(is_guest_iface "veth101i0" && echo yes || echo no)"
    check "fwbr100i0 為 guest 介面" "yes" "$(is_guest_iface "fwbr100i0" && echo yes || echo no)"
    check "vmbr0 非 guest 介面"     "no"  "$(is_guest_iface "vmbr0"     && echo yes || echo no)"
    check "eno1 非 guest 介面"      "no"  "$(is_guest_iface "eno1"      && echo yes || echo no)"
    check "bond0 非 guest 介面"     "no"  "$(is_guest_iface "bond0"     && echo yes || echo no)"

    echo
    subsection "7. VLAN 協定代碼"
    check "0x8100 → 802.1Q" "802.1Q (0x8100)"       "$(vlan_protocol_name "0x8100")"
    check "0x88a8 → QinQ"   "802.1ad QinQ (0x88a8)" "$(vlan_protocol_name "0x88a8")"

    echo
    subsection "8. 媒介判定（v01 誤判缺陷的回歸測試）"

    # 把模擬輸出注入快取，get_port_type 就不會去呼叫真的 ethtool。
    ETHTOOL_OUT["__t_rj45"]=$'\tPort: Twisted Pair\n\tSpeed: 1000Mb/s'
    ETHTOOL_MOD_TRIED["__t_rj45"]=1; ETHTOOL_MOD["__t_rj45"]=""

    ETHTOOL_OUT["__t_dac"]=$'\tPort: Direct Attach Copper\n\tTransceiver: external'
    ETHTOOL_MOD_TRIED["__t_dac"]=1; ETHTOOL_MOD["__t_dac"]="$(sample_module_dump dac)"

    ETHTOOL_OUT["__t_fiber"]=$'\tPort: FIBRE\n\tTransceiver: external'
    ETHTOOL_MOD_TRIED["__t_fiber"]=1; ETHTOOL_MOD["__t_fiber"]="$(sample_module_dump fiber)"

    ETHTOOL_OUT["__t_aoc"]=$'\tPort: Other\n\tTransceiver: external'
    ETHTOOL_MOD_TRIED["__t_aoc"]=1; ETHTOOL_MOD["__t_aoc"]="$(sample_module_dump aoc)"

    ETHTOOL_OUT["__t_bp"]=$'\tPort: Backplane'
    ETHTOOL_MOD_TRIED["__t_bp"]=1; ETHTOOL_MOD["__t_bp"]=""

    ETHTOOL_OUT["__t_none"]=""
    ETHTOOL_MOD_TRIED["__t_none"]=1; ETHTOOL_MOD["__t_none"]=""

    ETHTOOL_OUT["__t_rj45sfp"]=$'\tPort: Other\n\tTransceiver: external'
    ETHTOOL_MOD_TRIED["__t_rj45sfp"]=1; ETHTOOL_MOD["__t_rj45sfp"]="$(sample_module_dump rj45sfp)"

    ETHTOOL_OUT["__t_dacnl"]=$'\tPort: Other\n\tTransceiver: external'
    ETHTOOL_MOD_TRIED["__t_dacnl"]=1; ETHTOOL_MOD["__t_dacnl"]="$(sample_module_dump dac_nolen)"

    check "RJ45 電口（Twisted Pair）"        "RJ45 電口"    "$(get_port_type "__t_rj45")"
    check "DAC 銅纜（★v01 誤判為光纖）"     "DAC 銅纜"     "$(get_port_type "__t_dac")"
    check "光模組 10G-SR（陽性對照）"       "光纖"         "$(get_port_type "__t_fiber")"
    check "AOC 主動線纜"                    "AOC 主動線纜" "$(get_port_type "__t_aoc")"
    check "背板介面"                        "背板介面"     "$(get_port_type "__t_bp")"
    check "無 ethtool 資料"                 "未知"         "$(get_port_type "__t_none")"
    check "1000BASE-T SFP 銅口模組"         "RJ45 電口"    "$(get_port_type "__t_rj45sfp")"
    check "DAC 但線長欄位全缺"              "DAC 銅纜"     "$(get_port_type "__t_dacnl")"

    # (2a) 的兩個條件各補一個「只滿足其一」的樣本，否則拿掉任一條件都不會變紅。
    ETHTOOL_OUT["__t_rj45bare"]=$'\tPort: Other\n\tTransceiver: external'
    ETHTOOL_MOD_TRIED["__t_rj45bare"]=1
    ETHTOOL_MOD["__t_rj45bare"]="$(sample_module_dump rj45sfp_bare)"

    ETHTOOL_OUT["__t_basetnc"]=$'\tPort: Other\n\tTransceiver: external'
    ETHTOOL_MOD_TRIED["__t_basetnc"]=1
    ETHTOOL_MOD["__t_basetnc"]="$(sample_module_dump baset_noconn)"

    check "RJ45 接頭但無 type 欄位（僅靠接頭）" "RJ45 電口" "$(get_port_type "__t_rj45bare")"
    check "10GBASE-T 但接頭非 RJ45（僅靠型別）" "RJ45 電口" "$(get_port_type "__t_basetnc")"

    # 反事實對照：證明 DAC 那筆的判定確實來自線長欄位，而非「總是回 DAC」。
    # 把 Length (Copper) 改為 0、OM3 改為 300 之後，同一筆必須翻成光纖。
    ETHTOOL_MOD["__t_dac"]=$(sample_module_dump dac |
        sed -e 's/Length (Copper)             : 3m/Length (Copper)             : 0m/' \
            -e 's/Length (Copper)                           : 3m/Length (Copper)                           : 0m/' \
            -e 's/Length (OM3)                              : 0m/Length (OM3)                              : 300m/')
    check "同筆改線長欄位後翻為光纖（反事實）" "光纖" "$(get_port_type "__t_dac")"

    unset 'ETHTOOL_OUT[__t_rj45]' 'ETHTOOL_OUT[__t_dac]' 'ETHTOOL_OUT[__t_fiber]' \
          'ETHTOOL_OUT[__t_aoc]' 'ETHTOOL_OUT[__t_bp]' 'ETHTOOL_OUT[__t_none]'

    echo
    subsection "9. bridge vlan show 解析"

    local bv_sample bv_parsed
    bv_sample=$(cat <<'EOF'
port              vlan-id
vmbr0             1 PVID Egress Untagged
                  100
                  200-203
eno1              1 PVID Egress Untagged
                  100
tap100i0          100 PVID Egress Untagged
EOF
)
    bv_parsed=$(parse_bridge_vlan <<< "$bv_sample")

    check "vmbr0 的 VLAN 清單" "1u,100t,200-203t" "$(awk -F'\t' '$1=="vmbr0"{print $2}' <<< "$bv_parsed")"
    check "vmbr0 的 PVID"      "1"                "$(awk -F'\t' '$1=="vmbr0"{print $3}' <<< "$bv_parsed")"
    check "eno1 的 VLAN 清單"  "1u,100t"          "$(awk -F'\t' '$1=="eno1"{print $2}'  <<< "$bv_parsed")"
    check "tap100i0 的 PVID"   "100"              "$(awk -F'\t' '$1=="tap100i0"{print $3}' <<< "$bv_parsed")"
    check "解析出的 port 筆數" "3"                "$(wc -l <<< "$bv_parsed" | tr -d ' ')"
    check "表頭列未被當成 port" ""                "$(awk -F'\t' '$1=="port"{print $1}' <<< "$bv_parsed")"
    check "去標記後可餵給展開器" "1,100,200-203"  "$(bridge_vlan_for_port vmbr0 <<< "$bv_parsed")"
    check "uplink eno1 展開後含 100" "1,100"      "$(expand_vlan_list "$(bridge_vlan_for_port eno1 <<< "$bv_parsed")" | paste -sd ',' -)"

    # port 名獨佔一行（VLAN 全在續行）的格式，且刻意用「數字開頭」的介面名。
    # parse_bridge_vlan 有兩道防線：rest 清空、以及 vid 必須為數字開頭。
    # 介面名以字母開頭時第二道就擋掉了，兩道無從區分——實測移除第一道時，
    # 字母開頭樣本的輸出完全不變，只有數字開頭樣本會把 port 名收成 VLAN
    # （得 "10gbe0t,1u,50t"）。缺這個案例，移除第一道的突變不會讓任何測試變紅。
    local bv_split
    bv_split=$(printf '%s\n' \
        "port              vlan-id" \
        "10gbe0" \
        "                  1 PVID Egress Untagged" \
        "                  50")
    check "port 名獨佔一行時不被當成 VLAN" "1u,50t" \
        "$(parse_bridge_vlan <<< "$bv_split" | awk -F'\t' '$1=="10gbe0"{print $2}')"

    echo
    subsection "10. ethtool 快取（v02.000.000 快取失效的回歸測試）"

    # 記錄缺陷形態本身：經 $( ) 取值時，快取寫入留在 subshell 裡，父行程看不到。
    # 這一項「預期為 0」不是在要求快取失效，而是在釘住「為什麼非得有 prime_nic_cache」。
    reset_caches
    local _discard
    _discard=$(get_speed "__t_cacheprobe")
    check "經 \$( ) 取值不會留下快取（缺陷形態）" "0" "${#ETHTOOL_OUT[@]}"

    # 正解：於父行程直接呼叫 prime_nic_cache，快取才存得住。
    reset_caches
    prime_nic_cache "__t_cacheprobe"
    check "prime_nic_cache 於父行程填入快取"     "1" "${#ETHTOOL_OUT[@]}"
    check "prime 同時填入 driver 快取"           "1" "${#ETHTOOL_DRV[@]}"
    check "prime 同時標記 module 已嘗試"         "1" "${#ETHTOOL_MOD_TRIED[@]}"
    _discard=$(get_speed "__t_cacheprobe")
    check "prime 後快取仍在（$( ) 只讀不寫）"    "1" "${#ETHTOOL_OUT[@]}"
    reset_caches
    check "reset_caches 清空"                    "0" "${#ETHTOOL_OUT[@]}"

    echo
    subsection "11. 清單截斷會明說截掉多少（不靜默截斷）"

    local long_list
    long_list=$(seq 1 60)
    check "未超過上限時不加註記" "50" "$(seq 1 50 | print_limited 50 "筆" | wc -l | tr -d ' ')"
    check "超過上限時輸出被限制" "51" "$(print_limited 50 "筆" <<< "$long_list" | wc -l | tr -d ' ')"
    check "超量時明說實際總數"   "yes" \
        "$(print_limited 50 "筆" <<< "$long_list" | grep -q '實際共 60 筆' && echo yes || echo no)"
    check "超量時明說未顯示筆數" "yes" \
        "$(print_limited 50 "筆" <<< "$long_list" | grep -q '未顯示 10 筆' && echo yes || echo no)"
    check "空輸入不產生輸出"     "0" "$(printf '' | print_limited 50 "筆" | wc -c | tr -d ' ')"

    echo
    subsection "12. ethtool 實際呼叫次數（守住快取確實生效）"

    # 第 10 段只驗 prime_nic_cache 這個函式的行為，守不住「render 迴圈裡到底有沒有
    # 呼叫它」——而 v02.000.000 的缺陷正是出在呼叫形態，不是函式內容。
    # 這一段用自建的假 ethtool 與假 sysfs 實際跑一遍 render_physical_nics 並數次數，
    # 任何人把迴圈裡的 prime_nic_cache 拿掉，這裡就會變紅。
    # 量測基準：v01 每卡 7 次、v02.000.000 每卡 6 次（快取未生效）、修正後 3 次。
    # 以指定的 Port 型別跑一遍 render_physical_nics，把呼叫次數放進 EC_* 全域變數。
    count_ethtool_calls() {
        local port_value="$1" td b l
        td=$(mktemp -d); b="$td/bin"; l="$td/calls.log"
        mkdir -p "$b" "$td/net/nic0/statistics" "$td/net/nic0/device"
        : > "$l"
        printf '00:11:22:33:44:55\n' > "$td/net/nic0/address"
        printf '1\n'    > "$td/net/nic0/carrier"
        printf '1500\n' > "$td/net/nic0/mtu"
        printf 'up\n'   > "$td/net/nic0/operstate"
        printf '0\n'    > "$td/net/nic0/statistics/rx_bytes"
        printf '0\n'    > "$td/net/nic0/statistics/tx_bytes"

        {
            echo '#!/usr/bin/env bash'
            echo "echo \"\$*\" >> \"$l\""
            echo 'case "$1" in'
            echo '  -m) echo "	Connector : 0x07 (LC)"; echo "	Length (OM3) : 300m" ;;'
            echo '  -i) echo "driver: selftest" ;;'
            echo "  *)  echo \"	Port: $port_value\"; echo \"	Speed: 10000Mb/s\" ;;"
            echo 'esac'
        } > "$b/ethtool"
        chmod +x "$b/ethtool"

        local sp="$PATH" sr="$SYS_NET_ROOT" ss="$SAMPLE_SECONDS"
        PATH="$b:$PATH"; SYS_NET_ROOT="$td/net"; SAMPLE_SECONDS=0
        reset_caches
        render_physical_nics >/dev/null 2>&1
        PATH="$sp"; SYS_NET_ROOT="$sr"; SAMPLE_SECONDS="$ss"

        EC_TOTAL=$(wc -l < "$l" | tr -d ' ')
        EC_PLAIN=$(grep -cvE '^-' "$l")
        EC_I=$(grep -c '^-i' "$l")
        EC_M=$(grep -c '^-m' "$l")
        rm -rf "$td"
        reset_caches
        refresh_physical_nics
    }

    count_ethtool_calls "FIBRE"
    check "光纖網卡的 ethtool 呼叫次數"           "3" "$EC_TOTAL"
    check "  └ 其中一般輸出（ethtool <nic>）"     "1" "$EC_PLAIN"
    check "  └ 其中 ethtool -i"                   "1" "$EC_I"
    check "  └ 其中 ethtool -m"                   "1" "$EC_M"

    # RJ45 電口不該去讀 SFP EEPROM：ethtool -m 走 i2c，慢且對部分驅動有副作用。
    # 缺這個案例的話，把 prime_nic_cache 的 Twisted Pair 判斷拿掉不會讓任何測試變紅
    # （上面的樣本是 FIBRE，本來就要讀 -m）。
    count_ethtool_calls "Twisted Pair"
    check "RJ45 電口的 ethtool 呼叫次數"          "2" "$EC_TOTAL"
    check "  └ 不讀 SFP EEPROM（-m 應為 0）"      "0" "$EC_M"

    echo
    subsection "13. 報告檔以 0600 建立（內含叢集拓撲與防火牆規則）"

    local td_p probe
    td_p=$(mktemp -d)
    # 陽性對照：先確認這個平台的 chmod 真的能設出 0600，再談驗不驗得了。
    : > "$td_p/probe"
    chmod 600 "$td_p/probe" 2>/dev/null || true
    probe=$(stat -c '%a' "$td_p/probe" 2>/dev/null || echo "N/A")

    if [[ "$probe" == "600" ]]; then
        ( umask 077; : > "$td_p/rep" )
        chmod 600 "$td_p/rep" 2>/dev/null || true
        check "umask 077 + chmod 600 建立的檔案" "600" "$(stat -c '%a' "$td_p/rep")"
    else
        skip "報告檔 0600" "本平台 chmod 設不出 0600（探針得 ${probe}）⇒ 此項未驗證，需在 Linux 上覆驗"
    fi
    rm -rf "$td_p"

    echo
    subsection "14. 版本字樣三處同步（檔頭／VERSION 變數／CHANGELOG）"

    # 變更紀錄自 v02.000.001 起獨立成 CHANGELOG.md。版本字樣一旦散落在三個檔案／
    # 位置，最可能發生的就是改了其中一處而另兩處留在舊版——而這種漂移不會有任何
    # rc 變紅，只會讓後人讀到互相矛盾的版本。故在此實際比對。
    local self_file hdr_ver chg_file chg_ver
    self_file="${BASH_SOURCE[0]:-}"

    if [[ -f "$self_file" ]]; then
        hdr_ver=$(awk '/^# 版本：v/ { sub(/^# 版本：v/, ""); gsub(/[[:space:]]/, ""); print; exit }' "$self_file")
        check "檔頭「版本：」字樣 == VERSION 變數" "$VERSION" "$hdr_ver"

        chg_file="$(dirname "$self_file")/CHANGELOG.md"
        if [[ -f "$chg_file" ]]; then
            # [CHANGE] 2026-08-02：由「最上方那個版本 == VERSION」改為「CHANGELOG
            # 內存在本版的條目」。
            #
            # 原判準隱含一個前提：**一個 repo 只有一條版本軸線**，所以最新的條目
            # 必然就是我這一版。Python 重寫之後這個前提消失了——同一份 CHANGELOG
            # 同時服務 bash v02 與 Python v03，最上方是 v03，而本檔仍是 v02。
            #
            # 這種紅不是「程式壞了」，是「判準守的世界已經不存在」。把 CHANGELOG
            # 的 v03 條目往下挪可以讓它變綠，但那是為了配合判準去說謊。
            #
            # 新判準保留原本的意圖（註解寫的是「改了其中一處而另兩處留在舊版」）：
            # 只要本版在 CHANGELOG 裡找得到條目，就沒有漂移。它不再管誰在最上方。
            #
            # ★ 這條只在**公開版**真的跑得到：內部版腳本在 old/ 底下，
            #   dirname 取到的是 old/，那裡沒有 CHANGELOG.md ⇒ 走 skip。
            #   也就是說它的失敗只會在發版當下現形，跑內部測試看不到。
            chg_ver=$(awk -v want="$VERSION" \
                '$0 ~ "^## v" want "([（ ]|$)" { print want; exit }' "$chg_file")
            check "CHANGELOG 含本版（v$VERSION）條目" "$VERSION" "$chg_ver"
        else
            skip "CHANGELOG 版本比對" "找不到 $chg_file"
        fi
    else
        skip "版本三處同步" "取不到腳本自身路徑（BASH_SOURCE 未定義）"
    fi

    echo
    subsection "15. 窄終端自動切換版面"

    local saved_tw="${TERM_WIDTH:-}"

    TERM_WIDTH=80
    check "TERM_WIDTH 覆寫生效"          "80"  "$(term_width)"
    check "  └ 80 欄不用 132 欄的表格"   "no"  "$(use_table 132 && echo yes || echo no)"
    check "  └ 80 欄可用 70 欄的表格"    "yes" "$(use_table 70  && echo yes || echo no)"
    TERM_WIDTH=140
    check "140 欄可用 132 欄的表格"      "yes" "$(use_table 132 && echo yes || echo no)"
    TERM_WIDTH=""
    # 報告模式＝stdout 與 stderr 都不是 tty。此時版面不該由產生當下的終端大小
    # 決定（同一份報告在不同機器上讀，內容必須一致），故一律視為寬螢幕。
    check "報告模式（stdout/stderr 皆非 tty）視為寬螢幕" "9999" "$(term_width 2>/dev/null)"

    # 用假 sysfs 實際跑一遍兩種版面並量寬度——只驗 use_table 的布林值守不住
    # 「render 有沒有真的照它切換」，而版面正是使用者會看到的東西。
    local td_w b_w narrow_w narrow_head wide_head
    td_w=$(mktemp -d); b_w="$td_w/bin"
    mkdir -p "$b_w" "$td_w/net/nic0/statistics" "$td_w/net/nic0/device"
    printf '00:11:22:33:44:55\n' > "$td_w/net/nic0/address"
    printf '1\n'    > "$td_w/net/nic0/carrier"
    printf '1500\n' > "$td_w/net/nic0/mtu"
    printf 'up\n'   > "$td_w/net/nic0/operstate"
    printf '0\n'    > "$td_w/net/nic0/statistics/rx_bytes"
    printf '0\n'    > "$td_w/net/nic0/statistics/tx_bytes"
    {
        echo '#!/usr/bin/env bash'
        echo 'case "$1" in'
        echo '  -m) exit 1 ;;'
        echo '  -i) echo "driver: selftest"; echo "bus-info: 0000:01:00.0" ;;'
        echo '  *)  echo "	Port: Twisted Pair"; echo "	Speed: 1000Mb/s"; echo "	Duplex: Full" ;;'
        echo 'esac'
    } > "$b_w/ethtool"
    chmod +x "$b_w/ethtool"

    local sp_w="$PATH" sr_w="$SYS_NET_ROOT" ss_w="$SAMPLE_SECONDS"
    PATH="$b_w:$PATH"; SYS_NET_ROOT="$td_w/net"; SAMPLE_SECONDS=0
    reset_caches

    TERM_WIDTH=80
    narrow_w=$(render_physical_nics 2>/dev/null |
        awk '{n=0; for(i=1;i<=length($0);i++){c=substr($0,i,1); n+=(c ~ /[ -~]/)?1:2} if(n>m)m=n} END{print m+0}')
    narrow_head=$(render_physical_nics 2>/dev/null | grep -c 'MAC Address')
    TERM_WIDTH=200
    wide_head=$(render_physical_nics 2>/dev/null | grep -c 'MAC Address')

    PATH="$sp_w"; SYS_NET_ROOT="$sr_w"; SAMPLE_SECONDS="$ss_w"
    rm -rf "$td_w"
    reset_caches
    refresh_physical_nics

    check "窄終端實際輸出寬度不超過 80" "yes" "$( ((narrow_w <= 80)) && echo yes || echo no )"
    check "  └ 窄版不印表格表頭"        "0"   "$narrow_head"
    check "寬終端印出表格表頭"          "1"   "$wide_head"

    if [[ -n "$saved_tw" ]]; then TERM_WIDTH="$saved_tw"; else TERM_WIDTH=""; fi

    echo
    subsection "16. LED 定位選單的 Link 著色"

    # 實地回報：LED 定位那一頁的 Link 是白的，其他表格都有顏色。
    # 這一段守的是「顏色有沒有真的送出去」——用假 sysfs 造一張已接線與一張未接線
    # 的網卡，直接跑選單產生函式並檢查 ANSI 碼。
    local td_l saved_root_l saved_color_l
    td_l=$(mktemp -d)
    local n st
    for n in up0 down0; do
        mkdir -p "$td_l/net/$n/statistics" "$td_l/net/$n/device"
        printf '00:11:22:33:44:55\n' > "$td_l/net/$n/address"
        printf '1500\n' > "$td_l/net/$n/mtu"
        printf '0\n' > "$td_l/net/$n/statistics/rx_bytes"
    done
    printf '1\n' > "$td_l/net/up0/carrier";   printf 'up\n'   > "$td_l/net/up0/operstate"
    printf '0\n' > "$td_l/net/down0/carrier"; printf 'down\n' > "$td_l/net/down0/operstate"

    saved_root_l="$SYS_NET_ROOT"; saved_color_l="$USE_COLOR"
    SYS_NET_ROOT="$td_l/net"

    # 著色版與無色版都要在同一組 fixture 下取，兩者一起比才有意義
    local picklist_c picklist_p
    USE_COLOR=1; setup_colors
    refresh_physical_nics
    picklist_c=$(render_nic_pick_list)
    USE_COLOR=0; setup_colors
    picklist_p=$(render_nic_pick_list)

    SYS_NET_ROOT="$saved_root_l"
    USE_COLOR="$saved_color_l"; setup_colors
    rm -rf "$td_l"
    refresh_physical_nics

    check "選單列出兩張網卡"           "2" "$(wc -l <<< "$picklist_c" | tr -d ' ')"
    check "已接線那列帶綠色碼"         "1" "$(grep -c $'\033\[0;32m已接線' <<< "$picklist_c")"
    check "未接線那列帶紅色碼"         "1" "$(grep -c $'\033\[0;31m未接線' <<< "$picklist_c")"
    check "每列都有色碼重置"           "2" "$(grep -c $'\033\[0m' <<< "$picklist_c")"
    # 陰性對照：同一組 fixture 在無色模式下不可帶任何 ANSI 碼——否則報告檔會被汙染
    check "  └ 無色模式下 0 個 ANSI 碼" "0" "$(grep -c $'\033' <<< "$picklist_p")"
    check "  └ 無色模式仍列出兩張"     "2" "$(wc -l <<< "$picklist_p" | tr -d ' ')"

    echo
    subsection "17. 分頁輸出（pager）"

    local saved_np="${NO_PAGER:-}"

    NO_PAGER=1
    check "NO_PAGER=1 時不啟用 pager" "no" "$(pager_available && echo yes || echo no)"
    NO_PAGER=""
    # $( ) 內 stdout 非 tty ⇒ 不啟用 pager。報告模式若被 pager 接走會直接卡住，
    # 這一項守的是「排進 cron 的 --report 不會掛在那裡等人按鍵」。
    check "非 tty 時不啟用 pager"      "no" "$(pager_available && echo yes || echo no)"

    # pager 最該守的不是「有沒有啟用」，而是「內容有沒有被它改掉」——
    # 一個會吞行或改字的 pager，會讓盤查報告悄悄少掉東西。
    check "內容原樣通過（三行）"       "a|b|c" "$(printf 'a\nb\nc\n' | page_output | paste -sd '|' -)"
    check "空輸入不產生輸出"           "0"     "$(printf '' | page_output | wc -c | tr -d ' ')"
    check "含顏色碼的內容不被改動"     "1"     "$(printf '\033[0;31mred\033[0m\n' | page_output | grep -c $'\033\[0;31mred')"
    check "長行不被截斷"               "300"   "$(printf '%*s\n' 300 '' | page_output | wc -c | tr -d ' ' | awk '{print $1-1}')"

    if [[ -n "$saved_np" ]]; then NO_PAGER="$saved_np"; else NO_PAGER=""; fi

    echo
    subsection "18. VLAN 清單壓縮／折行／範圍判斷"

    # 起因是實地回報「bridge-vids 2-4090 時前面的 VLAN 數字看不到」。根因是某個
    # port 的 VLAN 被串成 23432 字元的單行，在終端折成約 300 行把前面推出畫面。
    check "帶標記：連續合併"       "1u,2-4t"     "$(echo '1u,2t,3t,4t'     | compress_vlan_list)"
    check "帶標記：不連續不合併"   "1u,2t,4-5t"  "$(echo '1u,2t,4t,5t'     | compress_vlan_list)"
    check "帶標記：標記不同不合併" "1-2u,3t"     "$(echo '1u,2u,3t'        | compress_vlan_list)"
    check "純數字：連續合併"       "1-4"         "$(echo '1,2,3,4'         | compress_vlan_list)"
    check "純數字：不連續不合併"   "1-2,4-5"     "$(echo '1,2,4,5'         | compress_vlan_list)"
    check "已是範圍者原樣保留"     "1u,2-4090t"  "$(echo '1u,2-4090t'      | compress_vlan_list)"
    check "單一值不加範圍符號"     "100"         "$(echo '100'             | compress_vlan_list)"

    # 這一項是本次缺陷的直接回歸測試：真實規模下必須壓成一個 token
    check "2-4090 逐個列出 → 壓成範圍" "1-4090" "$(seq 1 4090 | paste -sd ',' - | compress_vlan_list)"

    # wrap_vlan_list 的第一個參數是「文字內容」不是檔名——先取進變數再傳
    local long_vlans
    long_vlans=$(seq 100 100 4000 | sed 's/$/t/' | paste -sd ',' -)
    check "折行：短清單不折"       "1"   "$(wrap_vlan_list '1u,2-4090t' 46 | wc -l | tr -d ' ')"
    check "折行：長清單會折"       "yes" \
        "$( (( $(wrap_vlan_list "$long_vlans" 46 | wc -l) > 1 )) && echo yes || echo no )"
    check "折行後每行不超過寬度+1" "yes" \
        "$( [[ -z "$(wrap_vlan_list "$long_vlans" 46 | awk 'length($0) > 47')" ]] && echo yes || echo no )"

    check "範圍判斷：落在範圍內"   "yes" "$(vlan_in_list 100  '1,2-4090' && echo yes || echo no)"
    check "範圍判斷：範圍邊界"     "yes" "$(vlan_in_list 4090 '1,2-4090' && echo yes || echo no)"
    check "範圍判斷：超出範圍"     "no"  "$(vlan_in_list 4095 '1,2-4090' && echo yes || echo no)"
    check "範圍判斷：單值命中"     "yes" "$(vlan_in_list 1    '1,2-4090' && echo yes || echo no)"
    check "範圍判斷：空清單"       "no"  "$(vlan_in_list 100  ''         && echo yes || echo no)"

    # 交叉驗證：vlan_in_list（範圍比對）與 expand_vlan_list（逐個展開）是兩份
    # 獨立實作，對同一組輸入必須給出相同判斷。對帳用前者是為了效能，但正確性
    # 由後者背書——單靠一份實作自己驗自己沒有意義。
    # 先把展開結果落檔再查。MUST NOT 寫成 `expand_vlan_list … | grep -qx`——
    # grep -q 一命中就結束，上游收到 SIGPIPE，在 set -o pipefail 下整條管線 rc
    # 非 0，於是「命中」被讀成「未命中」。實測那樣寫會得到 00001100（只有靠後、
    # 上游已輸出完畢的探針才「成功」），看起來像被測物不一致，其實是量測裝置壞了。
    local xa="" xb="" probe expanded_f
    expanded_f=$(mktemp)
    expand_vlan_list "1,2-4090" > "$expanded_f"
    for probe in 1 2 50 100 4089 4090 4091 5000; do
        vlan_in_list "$probe" "1,2-4090" && xa+="1" || xa+="0"
        if grep -qx "$probe" "$expanded_f"; then xb+="1"; else xb+="0"; fi
    done
    rm -f "$expanded_f"
    check "與 expand_vlan_list 交叉驗證一致" "$xb" "$xa"
    check "  └ 該組探針非全中（裝置有鑑別力）" "yes" \
        "$( [[ "$xa" == *0* && "$xa" == *1* ]] && echo yes || echo no )"

    echo
    hr 60
    if ((fail == 0)); then
        if ((skipped > 0)); then
            echo -e "${GREEN}自檢通過 ${pass} 項${NC}，${YELLOW}另有 ${skipped} 項因平台限制未能驗證（見上方 [SKIP]）${NC}"
            echo -e "${YELLOW}⇒ 「未驗證」不等於「通過」，該項需在目標平台上覆驗。${NC}"
        else
            echo -e "${GREEN}自檢全部通過：${pass} 項。${NC}"
        fi
        return 0
    fi
    echo -e "${RED}自檢失敗：${fail} 項未通過（通過 ${pass} 項，另 ${skipped} 項未驗證）。${NC}"
    return 1
}

# ── 互動選單 ──────────────────────────────────────────────────────────────

# [CHANGE] v02.002.000：互動檢視改走 pager，詳 page_output() 的註解。
#
# 注意 `{ …; "$fn"; } | page_output` 會讓 "$fn" 在 subshell 中執行。這對
# prime_nic_cache 的快取無害——迴圈與預熱都在同一個 subshell 內，快取在該
# subshell 內仍然命中；只是不會傳回最外層，而每次進 view 本來就會重取。
view() {
    local title="$1" fn="$2"

    clear_screen

    if pager_available; then
        {
            print_header
            section "$title"
            "$fn"
            echo
            hr 60
            echo "（↑↓ 捲動　←→ 橫向捲動　/ 搜尋　q 返回主選單）"
        } | page_output
    else
        print_header
        section "$title"
        "$fn"
        pause_screen
    fi
}

view_all() {
    local entry title fn
    for entry in "${REPORT_SECTIONS[@]}"; do
        title="${entry%%|*}"
        fn="${entry##*|}"
        view "$title" "$fn"
    done
}

main_menu() {
    local choice
    while true; do
        clear_screen
        print_header
        reset_caches

        echo "請選擇盤查項目："
        echo
        echo -e "  ${BOLD}實體層${NC}"
        echo "   1) 實體網卡狀態與 RX/TX"
        echo "   2) 網卡健康：Link 抖動、錯誤與丟包、韌體"
        echo "   3) SFP/QSFP 模組明細"
        echo "   4) 實體網卡 LED 定位"
        echo
        echo -e "  ${BOLD}二層${NC}"
        echo "   5) Bond 設定與成員狀態"
        echo "   6) Linux Bridge"
        echo "   7) Open vSwitch"
        echo "   8) VLAN 子介面"
        echo "   9) Bridge VLAN Filter（逐 Port 放行清單）"
        echo "  10) VM/CT 網卡對應（tap/veth ←→ VMID）"
        echo "  11) VLAN 對帳（Guest VLAN vs Uplink 放行）"
        echo
        echo -e "  ${BOLD}三層與 PVE${NC}"
        echo "  12) IP / 路由 / DNS / hosts / 鄰居表"
        echo "  13) PVE SDN"
        echo "  14) 叢集網路（corosync）"
        echo "  15) PVE 防火牆"
        echo "  16) LLDP 交換器與 Port"
        echo "  17) /etc/network/interfaces 持久化設定"
        echo
        echo -e "  ${BOLD}整體${NC}"
        echo "  18) 依序檢視全部項目"
        echo "  19) 輸出完整盤查報告"
        echo "  20) 執行內建自檢"
        echo "   0) 離開"
        echo

        read -r -p "請輸入選項 [0-20]：" choice

        case "$choice" in
            1)  view "實體網卡狀態" render_physical_nics ;;
            2)  view "網卡健康指標" render_nic_health ;;
            3)  view "SFP/QSFP 模組明細" render_nic_modules ;;
            4)  identify_nic_led ;;
            5)  view "Bond 設定與執行狀態" render_bonds ;;
            6)  view "Linux Bridge" render_bridges ;;
            7)  view "Open vSwitch" render_ovs ;;
            8)  view "VLAN 子介面" render_vlan_subinterfaces ;;
            9)  view "Bridge VLAN Filter" render_bridge_vlan ;;
            10) view "VM/CT 網卡對應" render_guest_nics ;;
            11) view "VLAN 對帳" render_vlan_reconcile ;;
            12) view "IP / 路由 / DNS / hosts" render_ip_routing ;;
            13) view "PVE SDN" render_sdn ;;
            14) view "叢集網路 corosync" render_corosync ;;
            15) view "PVE 防火牆" render_firewall ;;
            16) view "LLDP 交換器鄰居資訊" render_lldp ;;
            17) view "持久化設定" render_persistent_config ;;
            18) view_all ;;
            19)
                clear_screen
                print_header
                generate_full_report 0
                pause_screen
                ;;
            20)
                clear_screen
                self_test
                pause_screen
                ;;
            0)
                echo "已離開。"
                exit 0
                ;;
            *)
                echo -e "${RED}無效選項。${NC}"
                sleep 1
                ;;
        esac
    done
}

# ── CLI ───────────────────────────────────────────────────────────────────

usage() {
    cat <<EOF
PVE 互動式網路盤查工具  v${VERSION}

用法：
  $(basename "$0")                 啟動互動選單
  $(basename "$0") --report        非互動，直接輸出完整盤查報告（適合排 cron）
  $(basename "$0") --self-test     只跑內建自檢，不讀取系統網路狀態
  $(basename "$0") --version       顯示版本
  $(basename "$0") --help          顯示本說明

環境變數：
  REPORT_DIR        報告輸出目錄（預設 /root）
  LIST_LIMIT        路由／鄰居等清單的顯示上限（預設 50，超量會明說截掉幾筆）
  SAMPLE_SECONDS    RX/TX 取樣秒數（預設 3）
  BLINK_SECONDS     LED 定位閃爍秒數（預設 10）
  PVE_CONF_ROOT     PVE 設定根目錄（預設 /etc/pve）

注意：報告內含 corosync 叢集拓撲與節點 IP、防火牆規則與 /etc/hosts，
      故以 0600 建立。若改用共用目錄存放，請自行確認目錄權限。

依賴：
  必要  iproute2（ip、bridge）
  建議  ethtool（速率／Duplex／媒介／韌體／LED）
        lldpd（交換器與 Port 對應）
  選用  openvswitch-switch（僅 OVS 環境需要）
EOF
}

main() {
    case "${1:-}" in
        --help|-h)
            usage
            exit 0
            ;;
        --version|-V)
            echo "$VERSION"
            exit 0
            ;;
        --self-test)
            self_test
            exit $?
            ;;
        --report)
            require_root
            USE_COLOR=0
            setup_colors
            generate_full_report 1
            exit $?
            ;;
        "")
            require_root
            main_menu
            ;;
        *)
            echo "未知選項：$1" >&2
            echo >&2
            usage >&2
            exit 2
            ;;
    esac
}

# [CHANGE] 以 source 方式載入時不執行 main，讓外部測試能直接呼叫個別函式。
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
