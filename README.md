[English](README.md) · [繁體中文](README.zh-TW.md)

# pve-nettools

A Proxmox VE network audit tool. The Python rewrite uses the extensionless, shebang-based `pve-network-audit` entry point and is version **v03.023.001**.

Repository: `github.com/LongHopeFreedom/pve-nettools`

License: MIT — see `LICENSE`  
負責人：LeeFreedom（秉迅資訊 BingXun InfoTech）

## Project layout

| Path | Purpose |
|---|---|
| `pve-network-audit` | Python entry point |
| `pve_nettools/` | Python package: 50 files, approximately 458 KB |
| `pve_nettools/collect/` | Collection subpackage |
| `pve_nettools/render/` | Rendering subpackage |
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

### About versions

**Use `pve-network-audit` (Python v03) — as of v03.013.000 it is the only version published in this repository**, has more features (menu items 21–24 are new in v03), and is the only one that will receive further updates.

**The Bash version is no longer shipped as of v03.013.000.** `pve-network-audit.sh` (Bash v02.002.001, frozen at that version and no longer updated) has been removed from the latest release.

> ⚠ **This means the situations listed under "Verification limits" below no longer have an older version in this repository to fall back to.** Please read that section before adopting this tool.
>
> If you do need the Bash version, it is still obtainable: this removal applies **only to the latest version and does not rewrite existing history** — the file is present in every commit up to and including `v03.012.000`.

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
| 1 | phys | NIC and virtual interface status (with RX/TX) | MAC, link, speed, duplex, MTU, media/type, RX/TX, driver, PCI address, plus the **model** of each physical NIC listed below the table (from `lspci`; not shown for virtual interfaces). In the interactive view the virtual-interface table (bond, bridge, VLAN) has a **Physical NIC** column that lists the physical NIC(s) each interface ultimately connects to (for example `vmbr0` → `enp6s0`; `—` when none can be resolved; several are joined with `, `); on a narrow terminal the same information moves to one line per interface below the table. The full report is unchanged. *This column has not been verified on a real host in this public release.* **Since v03.016.000 this includes bond, vmbr and VLAN interfaces**: the interface kind (Bond/Bridge/VLAN) appears in the media column. Such interfaces are **not** queried with `ethtool`, so these four fields — speed, duplex, driver and PCI address — are reported as N/A instead; `ethtool` reports a fabricated speed for a software bridge, so claiming a number there would be dishonest |
| 2 | phys | NIC health | Link flaps, RX/TX errors and drops, CRC errors, autonegotiation, NUMA, firmware |
| 3 | phys | SFP/QSFP module details | Vendor, part and serial numbers, connector, module type, temperature, voltage, optical power |
| 4 | phys | Physical NIC LED identification | Uses `ethtool -p` for on-site cable identification |
| 5 | l2 | Bond configuration and member state | Mode, members, active slave, hash policy, LACP rate, minimum links |
| 6 | l2 | Linux Bridge | Ports, VLAN awareness, vlan_protocol, default_pvid, STP, MTU, IPv4/v6. In the interactive view each bridge is shown in two parts: an upper part with virtual NIC information (the bridge itself plus its non-guest members) and a lower part with the guests attached to it, split into a VM zone and an LXC zone. The helper bridges PVE creates for firewalled guest NICs (`fwbr…`) are hidden in the interactive view, with a note giving how many were hidden; the full report (`--report`, menu 19) is unchanged and still lists them. *The two-part view and the `fwbr` hiding have not been verified on a real host in this public release.* |
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
| Recommended | `pciutils` (`lspci`) | The NIC model in menu 1 shows N/A, with an explanatory line |
| Optional | `openvswitch-switch` | Needed only for OVS environments |

```bash
apt update && apt install -y ethtool lldpd pciutils
systemctl enable --now lldpd
```

## Environment variables

| Variable | Default or priority | Purpose |
|---|---|---|
| `REPORT_DIR` | `/root` | Report output directory |
| `LIST_LIMIT` | `50` | Display limit for route and neighbour lists; truncation is reported |
| `SAMPLE_SECONDS` | `10` | RX/TX sampling period in seconds |
| `BLINK_SECONDS` | `10` | LED identification duration in seconds |
| `COMMAND_TIMEOUT` | `15` | External command timeout in seconds; a timeout is reported as a timeout, never as "not installed" |
| `PROBE_LINK` | enabled | Set to `0`/`no`/`off` to disable bringing NICs up for link probing. **This is the only action that changes host state** |
| `PROBE_WAIT` | `5` | Seconds to wait for auto-negotiation while probing; raise it for slow optics |
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

NIC and virtual interface status, NIC health, and VM/CT NIC mapping list every interface at once, one per row (**since v03.016.000 the first of these also covers bond, vmbr and VLAN interfaces**; the other two still list physical NICs only). SFP/QSFP module details use per-card blocks and show only cards with modules, automatically skipping RJ45 copper ports. LED identification presents a menu for selecting one NIC.

The three wide tables need approximately 132 columns. On a narrower terminal, they automatically fall back to per-card blocks with fields arranged vertically. The default width of the PVE web console (noVNC) is near this boundary. Use `TERM_WIDTH=200 ./pve-network-audit` to force the width.

Report files always use the table layout regardless of terminal width.

## Reports and scheduling

Reports contain the corosync cluster topology and node IPs, firewall rules, and `/etc/hosts`, and are created with mode 0600. If using a shared report directory, verify its permissions yourself.

```bash
install -d -m 0700 /var/log/pve-audit
0 6 * * 1 REPORT_DIR=/var/log/pve-audit /opt/pve-nettools/pve-network-audit --report
```

## Built-in self-test

`--self-test` currently runs 13 groups with 72 checks in total (v03.020.000, measured by running `python -m pve_nettools --self-test` in the `pve_nettools` package directory); use the check count printed by the command as the authority:

- Display width (CJK full-width counts as 2 columns): ASCII, CJK, and mixed display width, padding, and truncation.
- VLAN list expansion and compression: expansion, empty input, round trips, and membership checks.
- VM/CT interface config parsing: guest fields, key/value parsing, and valid/invalid MAC checks.
- Interface config file parsing: joining, stanzas, comments, blanks, and `auto` handling.
- Bilingual message table alignment: translation differences, empty values, and supported languages.
- sysfs read failure and empty-value handling.
- Network media semantic field decisions.
- `bridge vlan show` indented-output parsing.
- `ethtool` command cache (actual call counts).
- List truncation disclosure.
- Report file creation permissions.
- NIC model (`lspci`) parsing and missing-`lspci` handling.
- Bond vs member sampling mismatch decision.

The self-test covers only the pure functions and small known-answer cases listed above; it does not run the full rendering of each section and does not read the real system.

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

- **Bond**, **SFP/QSFP modules**, and **VLAN sub-interfaces**: the host had none, so only the "correctly reports no data" path was exercised—not the rendering of actual data (this refers to the host verified on 2026-08-03; later real-host observations of bonds are in the v03.016.000 and v03.019.000 items below)
- **ethtool failure messages**: all three ethtool queries succeeded, so the four cause-specific messages and the "the following fields will show N/A" line never appeared
- **Multi-node clusters** and **hosts with several physical NICs**
- **The bond/vmbr/VLAN traffic rows added in v03.016.000**: almost all verification ran against a fake sysfs on Windows. Of the three things only a real host can settle, only one has real-host evidence: whether bond counters are the sum of their members. On 2026-10-06, on one Proxmox VE host (one bond, two member NICs), the `statistics` counters were read directly twice, 3 seconds apart: the two members' RX grew by 180 and 238, the bond's RX grew by 418; TX growth was 0 on all three; in both readings the bond equaled the sum of the two members. Limits: one host, one bond, bond mode not recorded, and TX showed no growth during the observation (so the TX growth sum was not observed in that direct counter reading; in the v03.019.000 real-host check, the displayed values matched the member sums even where TX had grown, see the next item). The other two: the actual `DEVTYPE` values were not recorded separately (in the v03.019.000 real-host check the Bond/Bridge/VLAN type classification was displayed correctly); whether bridge counters exclude port-to-port forwarding (⇒ VM-to-VM traffic is invisible on `vmbr0`) remains unverified on a real host
- **v03.019.000 real-host check**: run on one PVE host; the deployed version was confirmed as 03.019.000 with `--version`. All four checks on menu item 1 matched: the sampling notice said "10 seconds", the RX/TX columns carried values, the three model lines under the table matched expectations, and the table did not degrade to the block layout. On that host the displayed RX/TX of two bonds matched the sum of their members, including a case where TX had grown; the Bond/Bridge/VLAN type classification was displayed correctly. **Not covered**: the note shown when bond and member sampling disagree. It was not triggered in that check (bond and members agreed), so its real output has not yet appeared on a real host and was verified only against a fake sysfs on Windows. Adjacent reads have run on a real host; this check adds no new information on the duration of the two read passes. A real host once showed bond0 TX with traffic while both member NICs showed none; it was not reproduced and the cause is unconfirmed. This version narrows the read gap and leaves numbers behind if the mismatch recurs; it does not guarantee the mismatch is gone, and it cannot show that the read gap was the cause. For menu items other than 1, this check adds no new verification; the statements above stand
- **Added in v03.020.000:** v03.020.000 is **not deployed and has not been run on a real host**. The `-`/`unknown` display rule for the Speed and Duplex columns, the rename of menu 1's title, and the two new `--self-test` groups (NIC model; bond vs member sampling mismatch) were verified only on Windows, with unit tests, the self-test, and mutation testing (using a fake ethtool and fake sysfs); only `Unknown!` and `Unknown! (255)` have samples of how ethtool says "no value" across drivers, and any wording that does not start with `Unknown` is shown as-is.
- **Added in v03.021.000 through v03.023.001:** v03.023.001 is **not deployed and has not been run on a real host**. The following were verified only on Windows, with unit tests and mutation testing (using a fake sysfs, fake config files and a fake `ip`): the Physical/Virtual zones of menu 1 with its bridge-relation sub-lines and guest NIC summary, and the VM/LXC split of menu 10 (v03.021.000); the two-part layout of menu 6 (virtual NIC information / guest information) (v03.022.000); hiding the `fwbr` guest pipeline bridges in menu 6 (v03.022.001); and the **Physical NIC** column in the virtual-interface table of menu 1 (added in v03.023.000, renamed in v03.023.001). The narrow-terminal behavior of that column was checked only against simulated widths.

For the first run in your own environment: execute `--self-test` → inspect each menu item while comparing it with raw `ip` / `ethtool` output → schedule recurring reports only after the results are confirmed.

## Interpretation notes

- **The note about bond and member sample mismatch**: when a bond and its member NICs disagree during the sample window — one side advanced and the other did not (RX and TX are judged separately) — an extra line appears below the table with the bond delta, the members' total delta and how long each of the two read passes took. Counters of different interfaces are not read at the same instant (a bond and its members are now read back to back to shrink the gap, but never simultaneously), so packets at the edge of the sample window may be counted on only one side. Both sides advancing by different amounts is normal on a busy bond and prints nothing.
- **`-`, `unknown` and `N/A` in the Speed and Duplex columns:** `-` means the NIC is confirmed unwired and ethtool negotiated no value (previously ethtool's raw `Unknown!` / `Unknown! (255)` was shown); `unknown` means ethtool answered Unknown while the link is not "unwired" (wired, or the link state itself is unknown) — there `unknown` only relays ethtool's answer and is not a diagnosis; `N/A` means the ethtool query failed or the field is absent (always N/A for virtual interfaces). The Traditional Chinese interface shows `—`/`未知`/`N/A`. A real value from ethtool is shown as-is and is not hidden because of the link state.
- **Media column:** Determination uses SFF-8472 structured fields in this priority order: `Port: Twisted Pair` → whether the connector is RJ45 or the type is BASE-T → copper and fibre cable-length fields → anchor words in the connector and cable-technology fields. The program does not keyword-scan the entire `ethtool -m` output because field names such as `Transceiver` and `Optical diagnostics support` would cause false positives for DAC.
- A continuously increasing `carrier_changes` value may indicate link, module, or remote-port flapping.
- Non-zero CRC errors normally point to a physical-layer issue.
- An uplink that does not allow a guest VLAN is a common cause of loss of connectivity; an access-port design is a separate case.
- Bridge and guest MTU mismatches may fail only with large packets and should be compared during each audit.
