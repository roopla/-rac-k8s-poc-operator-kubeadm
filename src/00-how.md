## How to use this guide

This guide builds a **second lab, the operator lab**, next to the manual lab you already have. It follows the manual guide's Phases 0 and 3–6 step by step, with its own names, addresses and ports, so the two labs never overwrite each other. The RAC database itself will come from Oracle's database operator in the later phases, instead of the hand-run installs of the manual lab's Phases 8–14.

**Copy every block exactly as it is.** Each block's label says where it runs, and the **connect** line shows how to get there. Blocks labelled `# PowerShell` run in a PowerShell window on your PC, never in Git Bash.

**This lab's output** blocks after a **Check** show what this lab's own run printed, so you can compare your screen line by line. Long logs are cut to the lines that matter (`…` marks a cut); where a step first went wrong, that output is shown too, labelled, next to the corrected run. IDs, UUIDs, image IDs and times will differ on your build. Steps without such a block weren't captured during this run (most of Phases 4 and 5).

| | Manual lab (unchanged) | **Operator lab (this guide)** |
| --- | --- | --- |
| VM names and host names | `controlplane`, `worker1`, `worker2` | **`op-controlplane`, `op-worker1`, `op-worker2`** |
| IPs on `k8s-public` 10.0.1.0/24 | .10, .11, .12 | **.20, .21, .22** |
| SSH from Windows | 2210, 2211, 2212 | **2220, 2221, 2222** |
| VM and disk folder | `D:\VMs\rac-poc` | **`D:\VMs\rac-op`** |
| Shared ASM disks | `rac-poc\shared\asm1.vdi`, `asm2.vdi`: one disk group `DATA` | **`rac-op\shared\vote1.vdi` (10 GB), `asm1.vdi`, `asm2.vdi`**: disk groups `VOTEDG`, `DATA`, `FRA` |
| Private networks (VirtualBox internal) | `rac-priv1`, `rac-priv2` | **`op-priv1`, `op-priv2`**, same subnets 10.0.11/12.0/24 |
| Kubernetes cluster name | `rac-poc` | **`rac-op`** |
| Golden VM `ol98-golden` (2205, 10.0.1.5) | shared | shared: only the clone source; nothing changes in it |
| NAT Network `k8s-public` | shared | shared: the operator lab only adds its own SSH forwards |

**Skipped phases:** Phases 1 and 2 built the golden VM, which both labs share. Phase 7 (ASM disks as Kubernetes volumes) and everything after it depend on what the operator expects, so they come after reading Oracle's operator documentation.

**One lab at a time.** Each lab needs about 48 GB of the PC's 64 GB, and both use the same NAT Network. Before you start the operator lab, the manual lab must be powered off, and the other way round:

```powershell
# PowerShell
$VB = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
& $VB list runningvms
```

**Check:** before working on the operator lab, nothing is listed, or only `op-*` VMs.

**Switching labs later** (after both are built):

```powershell
# PowerShell
$VB = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
# stop the manual lab (stop Grid in its pods first, as in "how to shut down")
foreach ($n in "worker2","worker1","controlplane") { & $VB controlvm $n acpipowerbutton 2>$null }
# start the operator lab
foreach ($n in "op-controlplane","op-worker1","op-worker2") { & $VB startvm $n --type headless }
```

Before stopping the operator lab, stop Clusterware in its pods first, as in the runbook in 14.6. To go back, swap the two lists: stop `op-worker2`, `op-worker1`, `op-controlplane`, then start `controlplane`, `worker1`, `worker2`.
