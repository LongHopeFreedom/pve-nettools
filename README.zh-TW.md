[English](README.md) · [繁體中文](README.zh-TW.md)

# pve-nettools

Proxmox VE 網路盤查工具。Python 重寫版的進入點為無副檔名、以 shebang 執行的 `pve-network-audit`，版本為 **v03.012.000**。

儲存庫：`github.com/LongHopeFreedom/pve-nettools`

授權：MIT，詳見 `LICENSE`  
負責人：LeeFreedom（秉迅資訊 BingXun InfoTech）

## 專案結構

| 路徑 | 內容 |
|---|---|
| `pve-network-audit` | Python 進入點 |
| `pve_nettools/` | Python 套件，共 48 個檔案、約 378 KB |
| `pve_nettools/collect/` | 資料收集子套件 |
| `pve_nettools/render/` | 輸出呈現子套件 |
| `pve-network-audit.sh` | Bash v02.002.001 —— **舊版備援**，凍結不再更新 |
| `CHANGELOG.md` | 版本沿革 |
| `LICENSE` | MIT 授權條款 |

## 安裝

Python v03 需要 Python 3.9 以上版本，而且只使用標準函式庫，不需 pip 或 venv。

Python v03 與 Bash v02 並存於本儲存庫，兩者都可直接取用：

```bash
git clone https://github.com/LongHopeFreedom/pve-nettools.git /opt/pve-nettools
cd /opt/pve-nettools
chmod +x pve-network-audit
sudo ./pve-network-audit
```

也可以直接下載儲存庫。一般盤查請以 root 執行。

### 該用哪一個

**請用 `pve-network-audit`（Python v03）——它是主線版本**，功能較多（選單 21–24 是 v03 新增的），也是後續唯一會更新的版本。

`pve-network-audit.sh` 是 **Bash v02.002.001，已凍結於該版不再更新**，保留在儲存庫裡有兩個用途：與 Python 版對照，以及在下方「驗證限度」列出的未涵蓋情境遇到問題時，還有一個已完整驗證過的版本可以退回使用。（未涵蓋的清單只寫在那一節，這裡不重複——兩份清單遲早會漂移。）

## 用法

```bash
./pve-network-audit              # 啟動互動選單
./pve-network-audit --report     # 非互動，輸出完整盤查報告
./pve-network-audit --self-test  # 內建自檢，不讀取系統網路狀態
./pve-network-audit --version
./pve-network-audit --help
```

一般盤查需 root；`--self-test` 不需 root。

## 語言切換

啟動時可在語言提示中選擇；進入選單後可按 `L` 即時切換，也可設定 `PVE_AUDIT_LANG=zh` 或 `PVE_AUDIT_LANG=en`。若未設定，程式依 `LC_ALL`、`LC_MESSAGES`、`LANG` 的順序推導語言；PVE 的 locale 多為 `C`，因此通常會顯示英文。

## 盤查項目

| # | 群組 | 項目 | 內容 |
|---|---|---|---|
| 0 | — | 離開 | 結束程式 |
| 1 | phys | 實體網卡狀態 | MAC、Link、速率、Duplex、MTU、媒介、RX/TX、驅動、PCI 位址 |
| 2 | phys | 網卡健康 | carrier_changes（線路抖動）、RX/TX 錯誤與丟包、CRC 錯誤、自動協商、NUMA、韌體版本 |
| 3 | phys | SFP/QSFP 模組明細 | 廠商、料號、序號、接頭、模組型別、溫度、電壓、光收發功率 |
| 4 | phys | 網卡 LED 定位 | `ethtool -p`，用於機房現場找線 |
| 5 | l2 | Bond | 模式、成員、Active Slave、Hash Policy、LACP Rate、Minimum Links、逐成員狀態 |
| 6 | l2 | Linux Bridge | 綁定 Port、VLAN-aware、vlan_protocol、default_pvid、STP、MTU、IPv4/v6 |
| 7 | l2 | Open vSwitch | OVS Bridge / Port / VLAN Tag / 成員介面 / Bond 狀態 |
| 8 | l2 | VLAN 子介面 | VLAN ID、上層介面與其型別、MTU、狀態、IPv4 |
| 9 | l2 | Bridge VLAN Filter | 逐 Port 放行清單，含 PVID 與 Untagged/Tagged 標記 |
| 10 | l2 | VM/CT 網卡對應 | `tap<vmid>i<n>` / `veth<vmid>i<n>` ←→ VMID、名稱、bridge、VLAN tag、MTU、防火牆、是否執行中 |
| 11 | l2 | VLAN 對帳 | Guest 使用的 VLAN vs Bridge Uplink 實際放行的 VLAN，列出未放行者 |
| 12 | l3 | IP / 路由 / DNS | IPv4+IPv6 位址與路由表、`/etc/resolv.conf`、`/etc/hosts`、鄰居表 |
| 13 | l3 | PVE SDN | zones / vnets / subnets / controllers 與執行期狀態 |
| 14 | l3 | 叢集網路 | corosync ring0/ring1、`corosync-cfgtool -s`、`pvecm status` |
| 15 | l3 | PVE 防火牆 | `pve-firewall status`、cluster.fw、host.fw |
| 16 | l3 | LLDP | 交換器名稱、對端 Port、Port 說明（鄰居摘要表＋完整明細） |
| 17 | l3 | 持久化設定 | `/etc/network/interfaces` 與 `interfaces.d/`，並偵測未套用的 `.new` |
| 18 | overall | 依序檢視全部項目 | 依序顯示所有可用盤查項目 |
| 19 | overall | 輸出完整盤查報告 | 寫入完整報告 |
| 20 | overall | 執行內建自檢 | 執行 Python 自檢 |
| 21 | added | sysctl 網路參數 | **v03 新增；Bash 版沒有此項** |
| 22 | added | conntrack 連線追蹤容量 | **v03 新增；Bash 版沒有此項** |
| 23 | added | 鄰居表容量（ARP／NDP gc_thresh） | **v03 新增；Bash 版沒有此項** |
| 24 | added | 開機自動啟用對帳（auto／hotplug） | **v03 新增；Bash 版沒有此項** |
| 25 | added | 網卡緩衝區與卸載功能 | **v03 新增；Bash 版沒有此項**。`ethtool -g` 的 RX/TX 環形緩衝區，以及 `ethtool -k` 的**全部**卸載功能（十項重點逐行顯示，其餘多欄排列） |

## 依賴

| 類別 | 套件 | 缺少時的行為 |
|---|---|---|
| 必要 | `iproute2`（`ip`、`bridge`） | 相關章節顯示提示並略過 |
| 建議 | `ethtool` | 速率／Duplex／韌體／LED 顯示 N/A，媒介顯示「未知」 |
| 建議 | `lldpd` | 無法查詢交換器與 Port |
| 選用 | `openvswitch-switch` | 僅 OVS 環境需要 |

```bash
apt update && apt install -y ethtool lldpd
systemctl enable --now lldpd
```

## 環境變數

| 變數 | 預設值／優先序 | 用途 |
|---|---|---|
| `REPORT_DIR` | `/root` | 報告輸出目錄 |
| `LIST_LIMIT` | `50` | 路由與鄰居清單的顯示上限；超量會說明截去筆數 |
| `SAMPLE_SECONDS` | `3` | RX/TX 取樣秒數 |
| `BLINK_SECONDS` | `10` | LED 定位閃爍秒數 |
| `PVE_CONF_ROOT` | `/etc/pve` | PVE 設定根目錄 |
| `PVE_AUDIT_LANG` | `zh` 或 `en` | 指定介面語言 |
| `NO_PAGER` | 設為 `1` 時啟用 | 不使用 `less`／`more` 分頁 |
| `TERM_WIDTH` | 寬度來源第一優先 | 強制指定版面寬度 |
| `COLUMNS` | 優先序次於 `TERM_WIDTH` | 提供版面寬度 |
| `LC_ALL` / `LC_MESSAGES` / `LANG` | 依此順序後備 | 未指定 `PVE_AUDIT_LANG` 時推導語言 |

### 分頁與橫向捲動

互動檢視的輸出會交給 `less`：

| 按鍵 | 作用 |
|---|---|
| `↑` `↓` `PgUp` `PgDn` | 上下捲動 |
| `←` `→` | **橫向捲動**（長行不折行） |
| `/關鍵字` | 搜尋（在幾十台 VM 裡找某個 VLAN 很好用） |
| `q` | 返回主選單 |

要關掉分頁可使用 `NO_PAGER=1 ./pve-network-audit`。報告模式（`--report`）不會將輸出交給 pager。

### VLAN 清單顯示

連續的 VLAN 會壓縮成範圍顯示。`bridge-vids 2-4090` 這種設定，即使 `bridge vlan show` 逐個列出 4089 行，表上也只會顯示為 `2-4090t`；後綴 `u` 代表 untagged，`t` 代表 tagged。清單過長時會折行到後續列顯示。

### 多網卡與窄終端

實體網卡、網卡健康、VM/CT 網卡對應這三項會一次列出每張網卡，每張一列；SFP/QSFP 模組明細採逐張區塊，且只顯示有模組的網卡（自動略過 RJ45 電口）；LED 定位則以選單供使用者挑選一張網卡。

這三張寬表格需要約 132 欄。終端不夠寬時會自動改用逐張區塊的垂直欄位版面；PVE 網頁主控台（noVNC）的預設寬度位於這個邊界附近。可使用 `TERM_WIDTH=200 ./pve-network-audit` 強制指定寬度。

報告檔不受終端寬度影響，一律使用表格版面。

## 報告與定期巡檢

報告包含 corosync 叢集拓撲與節點 IP、防火牆規則及 `/etc/hosts`，並以 0600 建立。若改用共用目錄，仍須自行確認目錄權限。

```bash
install -d -m 0700 /var/log/pve-audit
0 6 * * 1 REPORT_DIR=/var/log/pve-audit /opt/pve-nettools/pve-network-audit --report
```

## 內建自檢

`--self-test` 只涵蓋下列五個群組；實際檢查總數以該次指令輸出為準：

- `group_width`：ASCII、CJK、混合字元寬度，以及填補與截斷。
- `group_vlan`：VLAN 展開、空清單、往返轉換與包含判定。
- `group_guest`：Guest 欄位、鍵值、MAC 格式及錯誤 MAC 判定。
- `group_netconf`：網路設定的接合、stanza、註解、空白與 `auto` 判定。
- `group_i18n`：翻譯差異、空值與支援語言判定。

每次改動判定邏輯後應先執行自檢；傳回碼非 0 代表有判定失敗。

### ⚠ 驗證限度

**Python v03 已在實際的 Proxmox VE 主機上執行過**（PVE 9.2.5、kernel 7.0.6-2-pve，2026-08-03）。下面的涵蓋範圍與限度請一起讀——只讀其中一半會得到錯誤的印象。

**驗證涵蓋**：

- **2026-08-05 追加**：`--report` 完整報告在真機產出，**目前的 21 個區段全部有輸出**——含「網卡緩衝區與卸載功能」在報告版面（固定寬度，與互動版面是**不同的一條路徑**）的產出（2026-08-03 首次驗證時為當時的 20 個區段）
- 實體網卡各欄位取到真實數值（速率、Duplex、MTU、媒介、驅動、PCI 位址、韌體版本、自動協商），與 `ethtool` 原始輸出一致
- 內建自檢 56 項全數通過；完整測試 686 條在該主機上全數通過（其中 3 條與符號連結防護有關的測試只有 Linux 跑得到）
- VM/CT 網卡對應在有十餘個實際 guest 的環境下產出
- **2026-08-04 追加（v03.009.000）**：完整測試 **761 條**在該主機全數通過且**略過 0 條**。這一點是關鍵——報告建檔的安全性判準（不跟隨符號連結、**父目錄也不跟隨**、POSIX 權限實際為 0600、撞名不覆寫）在開發機上**結構上執行不到**，那 5 條在該主機是**實際執行並通過**的。內建自檢的建檔旗標檢查也第一次取到真值而非 0
- **2026-08-04 追加**：「網卡緩衝區與卸載功能」在該主機實際產出——`ethtool -k` 的 **63 項卸載功能全部顯示**，`ethtool -g` 的 6 個其餘欄位（含兩個真值）亦全部顯示

**未涵蓋**（那台主機沒有這些設備，或沒有進入這些狀態）：

- **Bond**、**SFP/QSFP 模組**、**VLAN 子介面**：主機上都沒有，因此只驗到「正確顯示沒有資料」，沒有驗到有資料時的呈現是否正確
- **ethtool 查詢失敗時的訊息**：三道 ethtool 查詢全部成功，四句成因訊息與「以下欄位將顯示 N/A」那一行都沒有機會出現
- **多節點叢集**與**多張實體網卡**的情境

首次在自己的環境執行時，仍請依序：`--self-test` → 在選單逐項檢視並與原始 `ip` / `ethtool` 輸出比較 → 確認無誤後才排進定期巡檢。

## 判讀提示

- **媒介欄**：依 SFF-8472 的結構化欄位判定，優先序為 `Port: Twisted Pair` → 接頭是否為 RJ45／類型是否為 BASE-T → 銅纜與光纖線長欄位 → 接頭與線纜技術的錨定詞。程式不會對整份 `ethtool -m` 輸出做關鍵字掃描，因為 `Transceiver`、`Optical diagnostics support` 等欄位名會導致 DAC 假陽性。
- **Link 變動（carrier_changes）**：持續增加可能表示線路、模組或對端 Port 抖動。
- **CRC 錯誤**：非 0 通常指向線材、模組或對端 Port 等實體層問題。
- **VLAN 對帳**：Uplink 未放行是 VLAN 不通的常見原因；交換器 access Port 則是不同情境。
- **MTU**：bridge 與 guest 不一致可能只在大封包時失敗，應於盤查時比對。
