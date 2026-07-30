# pve-nettools

Proxmox VE 網路盤查工具。

> **English summary** — An interactive network audit tool for Proxmox VE hosts.
> Inspects physical NICs (link, speed, MTU, media type, firmware, error counters,
> carrier flapping), bonds, Linux bridges, Open vSwitch, VLANs and `bridge vlan`
> filters, VM/CT interface mapping (`tap`/`veth` ↔ VMID), PVE SDN, corosync rings,
> firewall status, routing/DNS/hosts — and reconciles VLANs used by guests against
> those actually permitted on the bridge uplink.
> Runs as an interactive menu, or non-interactively via `--report` for scheduled audits.
> Bash only; needs `iproute2`, with `ethtool` and `lldpd` recommended.
> Documentation below is in Traditional Chinese.
>
> ```bash
> git clone https://github.com/LongHopeFreedom/pve-nettools.git
> cd pve-nettools
> ./pve-network-audit.sh --self-test   # offline self-check, no root needed
> sudo ./pve-network-audit.sh          # interactive menu
> ```
>
> ⚠ **Not yet verified on real Proxmox VE hardware** — see 「驗證限度」 below.

授權：MIT ・ 作者：LeeFreedom（秉迅資訊）

| 檔案 | 內容 |
|---|---|
| `pve-network-audit.sh` | 主程式 |
| `README.md` | 本檔——用法、盤查項目、依賴、判讀提示、驗證限度 |
| `CHANGELOG.md` | 版本沿革與各版修了什麼、為什麼 |
| `LICENSE` | MIT |

版本號採 `XX.XXX.XXX` 慣例，現行版以 `./pve-network-audit.sh --version` 為準。
版本字樣共三處（腳本檔頭、`VERSION` 變數、`CHANGELOG.md` 最上方），三者是否一致
由 `--self-test` 實際比對，漂移會讓自檢變紅。

## pve-network-audit.sh

互動式盤查 PVE 主機的實體網卡與網路設定，也可非互動輸出完整報告排進巡檢。

### 安裝

```bash
git clone https://github.com/LongHopeFreedom/pve-nettools.git /opt/pve-nettools
cd /opt/pve-nettools
./pve-network-audit.sh --self-test   # 先跑內建自檢（不需 root，不碰系統狀態）
```

### 用法

```bash
./pve-network-audit.sh              # 互動選單
./pve-network-audit.sh --report     # 非互動，直接輸出完整盤查報告（可排 cron）
./pve-network-audit.sh --self-test  # 只跑內建自檢，不讀取系統網路狀態
./pve-network-audit.sh --help
./pve-network-audit.sh --version
```

需 root（`ethtool -m` 讀 SFP EEPROM、`ethtool -p` LED 定位、`/etc/pve` 讀取皆需要）。
`--self-test` 不需 root。

### 盤查項目

| # | 項目 | 內容 |
|---|---|---|
| 1 | 實體網卡狀態 | MAC、Link、速率、Duplex、MTU、媒介、RX/TX、驅動、PCI 位址 |
| 2 | 網卡健康 | carrier_changes（線路抖動）、RX/TX 錯誤與丟包、CRC 錯誤、自動協商、NUMA、韌體版本 |
| 3 | SFP/QSFP 模組明細 | 廠商、料號、序號、接頭、模組型別、溫度、電壓、光收發功率 |
| 4 | 網卡 LED 定位 | `ethtool -p`，用於機房現場找線 |
| 5 | Bond | 模式、成員、Active Slave、Hash Policy、LACP Rate、Minimum Links、逐成員狀態 |
| 6 | Linux Bridge | 綁定 Port、VLAN-aware、vlan_protocol、default_pvid、STP、MTU、IPv4/v6 |
| 7 | Open vSwitch | OVS Bridge / Port / VLAN Tag / 成員介面 / Bond 狀態 |
| 8 | VLAN 子介面 | VLAN ID、上層介面與其型別、MTU、狀態、IPv4 |
| 9 | Bridge VLAN Filter | 逐 Port 放行清單，含 PVID 與 Untagged/Tagged 標記 |
| 10 | VM/CT 網卡對應 | `tap<vmid>i<n>` / `veth<vmid>i<n>` ←→ VMID、名稱、bridge、VLAN tag、MTU、防火牆、是否執行中 |
| 11 | VLAN 對帳 | Guest 使用的 VLAN vs Bridge Uplink 實際放行的 VLAN，列出未放行者 |
| 12 | IP / 路由 / DNS | IPv4+IPv6 位址與路由表、`/etc/resolv.conf`、`/etc/hosts`、鄰居表 |
| 13 | PVE SDN | zones / vnets / subnets / controllers 與執行期狀態 |
| 14 | 叢集網路 | corosync ring0/ring1、`corosync-cfgtool -s`、`pvecm status` |
| 15 | PVE 防火牆 | `pve-firewall status`、cluster.fw、host.fw |
| 16 | LLDP | 交換器名稱、對端 Port、Port 說明（鄰居摘要表＋完整明細） |
| 17 | 持久化設定 | `/etc/network/interfaces` 與 `interfaces.d/`，並偵測未套用的 `.new` |

### 依賴

| 類別 | 套件 | 缺少時的行為 |
|---|---|---|
| 必要 | `iproute2`（`ip`、`bridge`） | 相關章節顯示提示並略過 |
| 建議 | `ethtool` | 速率／Duplex／媒介／韌體／LED 顯示 N/A |
| 建議 | `lldpd` | 無法查詢交換器與 Port |
| 選用 | `openvswitch-switch` | 僅 OVS 環境需要；Linux Bridge 環境不裝屬正常 |

```bash
apt update && apt install -y ethtool lldpd
systemctl enable --now lldpd
```

### 環境變數

| 變數 | 預設 | 用途 |
|---|---|---|
| `REPORT_DIR` | `/root` | 報告輸出目錄 |
| `TERM_WIDTH` | 自動偵測 | 強制指定終端寬度，決定用表格版還是區塊版 |
| `LIST_LIMIT` | `50` | 路由／鄰居等清單的顯示上限（超量會明說截掉幾筆） |
| `SAMPLE_SECONDS` | `3` | RX/TX 取樣秒數 |
| `BLINK_SECONDS` | `10` | LED 定位閃爍秒數 |
| `PVE_CONF_ROOT` | `/etc/pve` | PVE 設定根目錄 |
| `SYS_NET_ROOT` | `/sys/class/net` | sysfs 網路根目錄（供離線測試指向 fixture） |

### 分頁與橫向捲動

互動檢視的輸出會交給 `less`：

| 按鍵 | 作用 |
|---|---|
| `↑` `↓` `PgUp` `PgDn` | 上下捲動 |
| `←` `→` | **橫向捲動**（長行不折行） |
| `/關鍵字` | 搜尋（在幾十台 VM 裡找某個 VLAN 很好用） |
| `q` | 返回主選單 |

要關掉分頁用 `NO_PAGER=1 ./pve-network-audit.sh`。報告模式（`--report`）不受影響，
不會被 pager 接走。

### VLAN 清單顯示

連續的 VLAN 會壓成範圍顯示。`bridge-vids 2-4090` 這種設定，即使 `bridge vlan show`
是逐個列出 4089 行，表上也只會顯示成 `2-4090t`（後綴 `u`=Untagged、`t`=Tagged）。
清單過長時折行續列，不會擠成一長條把前面的內容推出畫面。

### 多網卡與窄終端

實體網卡、網卡健康、VM/CT 網卡對應這三項會把**所有網卡一次列出**（一列一張）；
SFP/QSFP 模組明細是**逐張區塊**且只印有模組的（RJ45 電口自動跳過）；LED 定位則是
**列成選單讓你挑一張**。

三張寬表格需要約 132 欄。終端不夠寬時會**自動改用逐張區塊**，欄位垂直排列，不會
折行——PVE 網頁主控台（noVNC）預設寬度就在這個邊界附近。要強制指定用
`TERM_WIDTH=200 ./pve-network-audit.sh`。

報告檔不受終端寬度影響，恆為表格版。

### 報告檔含敏感內容

報告會納入 **corosync 叢集拓撲與各節點 IP、防火牆規則、`/etc/hosts`、完整路由表**。
腳本以 `umask 077` 建立並顯式 `chmod 600`，但**目錄權限仍是你的責任**——若把
`REPORT_DIR` 指到 0755 的共用目錄，其他人雖讀不到檔案內容，仍看得到檔名與時間。

### 排進定期巡檢

```bash
# 報告含叢集拓撲與防火牆規則，目錄權限務必設 0700
install -d -m 0700 /var/log/pve-audit

# 每週一 06:00 產出報告
0 6 * * 1 REPORT_DIR=/var/log/pve-audit /opt/pve-nettools/pve-network-audit.sh --report
```

### 內建自檢

`--self-test` 對有已知正確答案的判定邏輯做比對，涵蓋顯示寬度計算、VLAN 清單展開、
欄位值擷取、sysfs 讀取失敗處理、guest 介面命名判定、媒介判定、`bridge vlan show`
解析、**ethtool 實際呼叫次數**、清單截斷的揭露、報告檔權限。
每次改動判定邏輯後應先跑一次；rc 非 0 即代表有判定迴歸。

自檢本身以突變測試驗證過鑑別力——分別破壞線長判準、顯示寬度演算法、`bridge vlan`
解析的 rest 清空保護、`read_sysfs` 判準、VLAN 範圍展開、光纖分支條件、RJ45 接頭判斷、
BASE-T 型別判斷、迴圈中的快取預熱、截斷揭露，每一處都會讓自檢變紅；未突變的原檔為綠。

**未能驗證的項目會標成 `[SKIP]` 並單獨計數，不會混進「全部通過」。** 例如在 Windows
開發機上 `chmod` 設不出 0600，報告檔權限那項就會標為未驗證而非通過。

### ⚠ 驗證限度

**本工具尚未在真正的 Proxmox VE 主機上執行過。** 目前所有驗證都在開發機以模擬的
sysfs 與 PVE 設定檔進行，自檢樣本是依 SFF-8472 等規格**構造**的，不是真機擷取。

以下部分完全沒有真機驗證，首次上線請對照實際輸出確認：

- `ethtool` / `ethtool -m` 的實際輸出格式與 SFP EEPROM 內容
- `bridge vlan show` 在該版 iproute2 的實際格式
- `lldpcli show neighbors details` 的解析
- Open vSwitch 全部功能
- `corosync-cfgtool` / `pvecm` / `pvesh` / `pve-firewall`
- `/proc/net/bonding/*` 的解析
- 報告檔 0600 權限

建議首次執行順序：`--self-test` → 選單逐項檢視並與 `ip` / `ethtool` 原始輸出對照 →
確認無誤後才排進定期巡檢。

## 判讀提示

**媒介欄**依 SFF-8472 的結構化欄位判定，優先序為：`Port: Twisted Pair` → 模組接頭是否
RJ45／型別是否 BASE-T → 銅纜與光纖線長欄位 → 接頭與線纜技術的錨定詞。不掃整份
`ethtool -m` 輸出，因為其中的 `Transceiver`、`Optical diagnostics support` 等欄位名會讓
關鍵詞比對對 DAC 產生假陽性。

**Link 變動（carrier_changes）** 開機後正常值為 1～2。持續增加代表線路、模組或對端
Port 抖動，是最容易被「目前 Link 正常」掩蓋的故障。

**CRC 錯誤**非 0 幾乎必為實體層問題（線材、模組、對端 Port），與上層設定無關。

**VLAN 對帳**的「Uplink 未放行」是 VLAN 不通最常見的原因。但若交換器 Port 設為
access（不打 tag），guest 端本就不應再設 tag，屬另一種情形，不在此判準射程內。

**MTU** 不一致（例如 bridge 1500 而 guest 9000）在一般流量下不會報錯，只在大封包時
才失敗，屬於典型的間歇性故障來源，建議每次盤查都比對。
