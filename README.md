[English](README.md) · [繁體中文](README.zh-TW.md)

# pve-nettools

A Proxmox VE network audit tool. The Python rewrite uses the extensionless, shebang-based `pve-network-audit` entry point and is version **v03.012.000**.

Repository: `github.com/LongHopeFreedom/pve-nettools`

License: MIT — see `LICENSE`  
負責人：LeeFreedom（秉迅資訊 BingXun InfoTech）

## Project layout

| Path | Purpose |
|---|---|
| `pve-network-audit` | Python entry point |
| `pve_nettools/` | Python package: 48 files, approximately 378 KB |
| `pve_nettools/collect/` | Collection subpackage |
| `pve_nettools/render/` | Rendering subpackage |
| `pve-network-audit.sh` | Bash v02.002.001 — **legacy fallback**, frozen and no longer updated |
| `CHANGELOG.md` | Version history |
| `LICENSE` | MIT licence |

## Installation

Python v03 requires Python 3.9 or newer and uses only the standard library: no pip installation or virtual environment is needed.

Python v03 and the Bash v02 implementation both live in this repository and are ready to use:

```bash
git clone https://github.com/LongHopeFreedom/pve-nettools.git /opt/pve-nettools
cd /opt/pve-nettools
chmod +x pve-network-audit
sudo ./pve-network-audit
```

You may also download the repository instead of cloning it. Run the audit as root.

### Which one to use

**Use `pve-network-audit` (Python v03) — it is the main version**, has more features (menu items 21–24 are new in v03), and is the only one that will receive further updates.

`pve-network-audit.sh` is **Bash v02.002.001, frozen at that version and no longer updated**. It is kept in the repository for two reasons: to compare against the Python version, and to give you a fully verified fallback should you hit trouble in any of the situations listed under "Verification limits" below. (That list lives in one place only; repeating it here would guarantee the two copies drift.)

## Usage

```bash
./pve-network-audit              # interactive menu
./pve-network-audit --report     # write a complete non-interactive report
./pve-network-audit --self-test  # built-in self-test; does not read network state
./pve-network-audit --version
./pve-network-audit --help
```

Normal audits require root; `--self-test` does not.

## Language selection

Choose a language at the startup prompt, press `L` in the menu to switch live, or set `PVE_AUDIT_LANG=zh` or `PVE_AUDIT_LANG=en`. Without that variable, language is inferred from `LC_ALL`, then `LC_MESSAGES`, then `LANG`. PVE locales are often `C`, which normally selects English.

## Audit menu

| # | Group | Item | Details |
|---|---|---|---|
| 0 | — | Exit | Exit the program |
| 1 | phys | Physical NIC status and RX/TX | MAC, link, speed, duplex, MTU, media, RX/TX, driver, PCI address |
| 2 | phys | NIC health | Link flaps, RX/TX errors and drops, CRC errors, autonegotiation, NUMA, firmware |
| 3 | phys | SFP/QSFP module details | Vendor, part and serial numbers, connector, module type, temperature, voltage, optical power |
| 4 | phys | Physical NIC LED identification | Uses `ethtool -p` for on-site cable identification |
| 5 | l2 | Bond configuration and member state | Mode, members, active slave, hash policy, LACP rate, minimum links |
| 6 | l2 | Linux Bridge | Ports, VLAN awareness, vlan_protocol, default_pvid, STP, MTU, IPv4/v6 |
| 7 | l2 | Open vSwitch | OVS bridges, ports, VLAN tags, interfaces, and bond status |
| 8 | l2 | VLAN sub-interfaces | VLAN ID, parent interface and type, MTU, state, IPv4 |
| 9 | l2 | Bridge VLAN filter | Per-port allowed list with PVID and tagged/untagged markers |
| 10 | l2 | VM/CT NIC mapping | `tap<vmid>i<n>` / `veth<vmid>i<n>` to VMID, name, bridge, VLAN tag, MTU, firewall, running state |
| 11 | l2 | VLAN reconciliation | Guest VLANs versus VLANs allowed on the bridge uplink |
| 12 | l3 | IP / routes / DNS / hosts / neighbour table | IPv4/IPv6 addresses and routes, resolv.conf, hosts, neighbours |
| 13 | l3 | PVE SDN | Zones, vnets, subnets, controllers, and runtime state |
| 14 | l3 | Cluster network (corosync) | ring0/ring1, `corosync-cfgtool -s`, `pvecm status` |
| 15 | l3 | PVE firewall | `pve-firewall status`, cluster.fw, host.fw |
| 16 | l3 | LLDP switch and port | Switch name, remote port, port description, summary and details |
| 17 | l3 | Persistent network configuration | `/etc/network/interfaces`, `interfaces.d/`, and unapplied `.new` files |
| 18 | overall | View all available items in sequence | Display every available audit item in order |
| 19 | overall | Write a complete audit report | Write the complete report |
| 20 | overall | Run the built-in self-test | Run the Python self-test |
| 21 | added | sysctl networking parameters | **New in v03; absent from the Bash version** |
| 22 | added | conntrack capacity | **New in v03; absent from the Bash version** |
| 23 | added | Neighbour table capacity (ARP/NDP gc_thresh) | **New in v03; absent from the Bash version** |
| 24 | added | Autostart reconciliation (auto/hotplug) | **New in v03; absent from the Bash version** |
| 25 | added | NIC ring buffers and offload features | **New in v03; absent from the Bash version.** RX/TX ring buffers from `ethtool -g` and **every** offload feature from `ethtool -k` (ten key ones row by row, the rest in aligned columns) |

## Dependencies

| Class | Package | Behaviour when missing |
|---|---|---|
| Required | `iproute2` (`ip`, `bridge`) | Affected sections show a notice and are skipped |
| Recommended | `ethtool` | Speed, duplex, firmware, and LED data show N/A; media shows "Unknown" |
| Recommended | `lldpd` | Switch and port mapping is unavailable |
| Optional | `openvswitch-switch` | Needed only for OVS environments |

```bash
apt update && apt install -y ethtool lldpd
systemctl enable --now lldpd
```

## Environment variables

| Variable | Default or priority | Purpose |
|---|---|---|
| `REPORT_DIR` | `/root` | Report output directory |
| `LIST_LIMIT` | `50` | Display limit for route and neighbour lists; truncation is reported |
| `SAMPLE_SECONDS` | `3` | RX/TX sampling period in seconds |
| `BLINK_SECONDS` | `10` | LED identification duration in seconds |
| `PVE_CONF_ROOT` | `/etc/pve` | PVE configuration root |
| `PVE_AUDIT_LANG` | `zh` or `en` | Interface language |
| `NO_PAGER` | enabled when set to `1` | Disable `less`/`more` paging |
| `TERM_WIDTH` | first width source | Force layout width |
| `COLUMNS` | after `TERM_WIDTH` | Supply layout width |
| `LC_ALL` / `LC_MESSAGES` / `LANG` | fallback in this order | Infer language when `PVE_AUDIT_LANG` is unset |

### Paging and horizontal scrolling

Interactive output is sent to `less`:

| Key | Action |
|---|---|
| `↑` `↓` `PgUp` `PgDn` | Scroll vertically |
| `←` `→` | **Scroll horizontally** without wrapping long lines |
| `/keyword` | Search, for example for a VLAN among dozens of VMs |
| `q` | Return to the main menu |

Use `NO_PAGER=1 ./pve-network-audit` to disable paging. Report mode (`--report`) does not send its output to the pager.

### VLAN list display

Consecutive VLANs are collapsed into ranges. A `bridge-vids 2-4090` configuration is shown as `2-4090t` even when `bridge vlan show` lists 4,089 individual lines. The suffix `u` means untagged and `t` means tagged. Long lists wrap onto continuation rows.

### Multiple NICs and narrow terminals

Physical NIC status, NIC health, and VM/CT NIC mapping list every NIC at once, one per row. SFP/QSFP module details use per-card blocks and show only cards with modules, automatically skipping RJ45 copper ports. LED identification presents a menu for selecting one NIC.

The three wide tables need approximately 132 columns. On a narrower terminal, they automatically fall back to per-card blocks with fields arranged vertically. The default width of the PVE web console (noVNC) is near this boundary. Use `TERM_WIDTH=200 ./pve-network-audit` to force the width.

Report files always use the table layout regardless of terminal width.

## Reports and scheduling

Reports contain the corosync cluster topology and node IPs, firewall rules, and `/etc/hosts`, and are created with mode 0600. If using a shared report directory, verify its permissions yourself.

```bash
install -d -m 0700 /var/log/pve-audit
0 6 * * 1 REPORT_DIR=/var/log/pve-audit /opt/pve-nettools/pve-network-audit --report
```

## Built-in self-test

`--self-test` covers exactly these five groups; use the check count printed by the command rather than a hardcoded count:

- `group_width`: ASCII, CJK, and mixed display width, padding, and truncation.
- `group_vlan`: VLAN expansion, empty input, round trips, and membership checks.
- `group_guest`: guest fields, key/value parsing, and valid/invalid MAC checks.
- `group_netconf`: joining network configuration, stanzas, comments, blanks, and `auto` handling.
- `group_i18n`: translation differences, empty values, and supported languages.

Run it after changing decision logic. A non-zero return code indicates a failed decision check.

## Verification limits

**Python v03 has been run on a real Proxmox VE host** (PVE 9.2.5, kernel 7.0.6-2-pve, 2026-08-03). Read the coverage and the limits below together—reading only one half gives the wrong impression.

**Verified coverage:**

- **Added 2026-08-05:** the full `--report` was produced on real hardware and **all 21 sections emitted output**, including "NIC ring buffers and offload features" in the report layout (fixed width, a **different code path** from the interactive one). The first run on 2026-08-03 covered the 20 sections that existed then
- Physical NIC fields carried real values (speed, duplex, MTU, media, driver, PCI address, firmware version, auto-negotiation) and matched raw `ethtool` output
- All 56 built-in self-test checks passed; all 686 tests passed on that host (3 of them, covering symlink protection, can only run on Linux)
- The VM/CT interface mapping was produced in an environment with a dozen or so live guests
- **Added 2026-08-04 (v03.009.000):** all **761** tests passed on that host with **zero skipped**. That matters: the report-creation safety criteria (do not follow a symlink, **do not follow a symlinked parent directory**, real POSIX mode 0600, never overwrite on a filename collision) cannot execute at all on the development machine; those 5 tests really ran and passed there. The built-in self-test's create-flag check also received a real value instead of 0 for the first time
- **Added 2026-08-04:** "NIC ring buffers and offload features" was produced on that host—all **63** offload features from `ethtool -k` were displayed, as were the 6 remaining `ethtool -g` fields (two of which carry real values)

**Not covered** (that host has no such hardware, or never entered these states):

- **Bond**, **SFP/QSFP modules**, and **VLAN sub-interfaces**: the host had none, so only the "correctly reports no data" path was exercised—not the rendering of actual data
- **ethtool failure messages**: all three ethtool queries succeeded, so the four cause-specific messages and the "the following fields will show N/A" line never appeared
- **Multi-node clusters** and **hosts with several physical NICs**

For the first run in your own environment: execute `--self-test` → inspect each menu item while comparing it with raw `ip` / `ethtool` output → schedule recurring reports only after the results are confirmed.

## Interpretation notes

- **Media column:** Determination uses SFF-8472 structured fields in this priority order: `Port: Twisted Pair` → whether the connector is RJ45 or the type is BASE-T → copper and fibre cable-length fields → anchor words in the connector and cable-technology fields. The program does not keyword-scan the entire `ethtool -m` output because field names such as `Transceiver` and `Optical diagnostics support` would cause false positives for DAC.
- A continuously increasing `carrier_changes` value may indicate link, module, or remote-port flapping.
- Non-zero CRC errors normally point to a physical-layer issue.
- An uplink that does not allow a guest VLAN is a common cause of loss of connectivity; an access-port design is a separate case.
- Bridge and guest MTU mismatches may fail only with large packets and should be compared during each audit.
