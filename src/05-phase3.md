## Phase 3: Clone the three operator-lab nodes

**Result of this phase:** three VMs (`op-controlplane`, `op-worker1`, `op-worker2`) cloned from the same golden image as the manual lab, the workers with two data disks each and their private NICs on `op-priv1` / `op-priv2`, and three new disks that **both** workers share for ASM: 10 GB for `VOTEDG`, 50 GB each for `DATA` and `FRA`.

### 3.1 Check that the golden VM is still sealed

**Why:** clones must come from the **sealed** golden image: no machine ID, no SSH host keys. You sealed it before cloning the manual lab. If the golden VM has been started since then, it has made itself a new machine ID and host keys, and every clone would share them. Kubernetes refuses to join nodes with the same machine ID.

**How to tell without starting it:** VirtualBox records when a VM last changed state. If the golden VM's last change (its power-off after sealing) is **older** than the manual lab's clones, nobody has started it since.

```powershell
# PowerShell
$VB = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"; $g = "ol98-golden"
$info = & $VB showvminfo $g --machinereadable
$state = ($info | Select-String '^VMState="(.*)"').Matches[0].Groups[1].Value
$raw = ($info | Select-String '^VMStateChangeTime="(.*)"').Matches[0].Groups[1].Value
$changed = [datetime]::SpecifyKind([datetime]::ParseExact($raw.Substring(0,19), 'yyyy-MM-ddTHH:mm:ss', $null), 'Utc')   # VirtualBox writes UTC
$cpCfg = (& $VB showvminfo controlplane --machinereadable | Select-String '^CfgFile="(.*)"').Matches[0].Groups[1].Value
$cloned = (Get-Item (Split-Path $cpCfg)).CreationTimeUtc   # when the manual lab's controlplane was cloned
"manual lab folder:    $(Split-Path $cpCfg)"
"golden state:         $state"
"golden last changed:  $($changed.ToString('u'))"
"manual lab cloned:    $($cloned.ToString('u'))"
if ($state -eq 'poweroff' -and $changed -lt $cloned) { "OK: still sealed, not started since the manual lab was cloned" } else { "STOP: golden VM was started after the seal; reseal it (below)" }
& $VB snapshot $g list
```

**Check:** the line says `OK: still sealed…`, and the snapshot list shows the `pre-seal` snapshot. Then go straight to 3.2. The block finds the manual lab's folder from VirtualBox itself, wherever it is on your disk.

**This lab's output:**

```text
manual lab folder:    D:\\VMs\\rac-poc\\k8s-rac-manual\\controlplane\
golden state:         poweroff
golden last changed:  2026-10-25 12:08:16Z
manual lab cloned:    2026-10-25 12:08:31Z
OK: still sealed, not started since the manual lab was cloned
   Name: pre-seal (UUID: 50fb527d-13b9-4e6b-94bb-49208269b5ff) *
   Description: Prepared golden image before sealing
```

**This lab's output (the first version of the check, before it was fixed: it assumed the manual lab was in D:\VMs\rac-poc\controlplane, got no clone time and gave a false STOP. The current block asks VirtualBox for the folder instead):**

```text
$cloned = (Get-Item "D:\VMs\rac-poc\controlplane").CreationTimeUtc
Get-Item : Cannot find path 'D:\VMs\rac-poc\controlplane' because it does not exist.
golden state:         poweroff
golden last changed:  2026-10-25 12:08:16Z
manual lab cloned:
STOP: golden VM was started after the seal; reseal it (below)
```

**Only if it says STOP:** seal it again, in place. Don't restore the `pre-seal` snapshot: fixes made to the golden image after that snapshot would be lost. Starting the golden VM gives it a new machine ID and host keys for a moment; the seal block removes them again and powers it off.

```powershell
# PowerShell  (only after a STOP in the check above)
& "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe" startvm ol98-golden --type headless
ssh-keygen -R "[127.0.0.1]:2205" 2>$null
```

```bash
# golden VM  (the last command powers it off; don't start it again before cloning; connect: ssh -p 2205 root@127.0.0.1)
dnf clean all
rm -f /etc/ssh/ssh_host_*
truncate -s 0 /etc/machine-id
rm -f /var/lib/dbus/machine-id
rm -rf /tmp/* /var/tmp/*
journalctl --rotate; journalctl --vacuum-time=1s
rm -f /root/.bash_history; history -c
poweroff
```

If SSH warns that the host key for port 2205 has changed, run `ssh-keygen -R "[127.0.0.1]:2205"` in PowerShell and connect again.

### 3.2 Clone and size the nodes

**Why these sizes:** the same as the manual lab. op-controlplane gets 2 vCPU and 4 GB with no private NICs; each worker gets 4 vCPU and 22 GB, an 80 GB disk for `/scratch` and a 100 GB disk for `/var/lib/containers`.

**What's different:** the workers' second and third NICs move from the manual lab's internal networks `rac-priv1` / `rac-priv2` to the operator lab's `op-priv1` / `op-priv2`. The clones inherit the golden VM's NIC settings, including the "Allow All" promiscuous mode Multus needs; only the network names change.

```powershell
# PowerShell
$VB = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"; $Base = "D:\VMs\rac-op"; $g = "ol98-golden"
while ("$(& $VB showvminfo $g --machinereadable | Select-String '^VMState=')" -notmatch 'poweroff') { Start-Sleep 3 }
foreach ($n in "op-controlplane","op-worker1","op-worker2") { & $VB clonevm $g --name $n --basefolder $Base --mode machine --register }
& $VB modifyvm op-controlplane --cpus 2 --memory 4096 --nic2 none --nic3 none
foreach ($w in "op-worker1","op-worker2") {
  & $VB modifyvm $w --cpus 4 --memory 22528 --intnet2 op-priv1 --intnet3 op-priv2
  & $VB createmedium disk --filename "$Base\$w\$w-scratch.vdi" --size 81920 --variant Standard
  & $VB createmedium disk --filename "$Base\$w\$w-containers.vdi" --size 102400 --variant Standard
  & $VB storageattach $w --storagectl SATA --port 1 --device 0 --type hdd --medium "$Base\$w\$w-scratch.vdi"
  & $VB storageattach $w --storagectl SATA --port 2 --device 0 --type hdd --medium "$Base\$w\$w-containers.vdi"
}
foreach ($n in "op-controlplane","op-worker1","op-worker2") { "--- $n"; & $VB showvminfo $n --machinereadable | Select-String '^(cpus|memory|nic[123]|nat-network1|intnet[23])='; & $VB showvminfo $n | Select-String '^NIC [23]:' }
```

**Check:**

- **op-controlplane:** `cpus=2`, `memory=4096`, `nic1="natnetwork"` with `nat-network1="k8s-public"`, and `nic2="none"`, `nic3="none"`;
- **each worker:** `cpus=4`, `memory=22528`, `nat-network1="k8s-public"`, `intnet2="op-priv1"`, `intnet3="op-priv2"`, and two `NIC 2:` / `NIC 3:` lines that include **`Promisc Policy: allow-all`**, each with its own MAC address. (The machine-readable output has no promiscuous-mode line on this VirtualBox version, so the check reads it from the normal output.)

**This lab's output:**

```text
Machine has been successfully cloned as "op-controlplane"
Machine has been successfully cloned as "op-worker1"
Machine has been successfully cloned as "op-worker2"
Medium created. UUID: a6d01e0b-…        (op-worker1 scratch)
Medium created. UUID: cb7bdfad-…        (op-worker1 containers)
Medium created. UUID: 2d09717f-…        (op-worker2 scratch)
Medium created. UUID: b4ca77a0-…        (op-worker2 containers)
--- op-controlplane
memory=4096
cpus=2
nat-network1="k8s-public"
nic1="natnetwork"
nic2="none"
nic3="none"
--- op-worker1
memory=22528
cpus=4
nat-network1="k8s-public"
nic1="natnetwork"
intnet2="op-priv1"
nic2="intnet"
intnet3="op-priv2"
nic3="intnet"
--- op-worker2
(same as op-worker1)
--- op-worker1
NIC 2:   MAC: 080027C33702, Attachment: Internal Network 'op-priv1', … Promisc Policy: allow-all, …
NIC 3:   MAC: 08002743BD30, Attachment: Internal Network 'op-priv2', … Promisc Policy: allow-all, …
--- op-worker2
NIC 2:   MAC: 0800279D8872, Attachment: Internal Network 'op-priv1', … Promisc Policy: allow-all, …
NIC 3:   MAC: 0800279E4885, Attachment: Internal Network 'op-priv2', … Promisc Policy: allow-all, …
```

### 3.3 The shared ASM disks

**What:** three disks attached to **both** workers at once, one per ASM disk group:

| Disk | Size | SATA port | Disk group | Holds |
| --- | --- | --- | --- | --- |
| `vote1.vdi` | 10 GB | 5 | `VOTEDG` | the cluster's own files: voting file, OCR, the ASM password file and spfile |
| `asm1.vdi` | 50 GB | 3 | `DATA` | the database's data files, control files and redo logs |
| `asm2.vdi` | 50 GB | 4 | `FRA` | the fast recovery area: archived logs, flashback logs, backups |

**Why three disk groups instead of one:** keeping the cluster's files apart from the database makes each easier to size, move and repair; a full `FRA` can't stop the cluster, and the clusterware disk group stays small. The manual lab put everything into one `DATA` disk group.

**Why port 5:** the SATA controller has six ports (0–5). Port 5 carries the golden VM's empty DVD drive, which the clones inherited and nothing uses; the block removes it and puts `vote1` there.

**Why fixed size and `shareable`:** RAC is a shared-disk database, so both nodes need the same block devices; VirtualBox only allows the shareable type on fixed-size disks, and without it refuses to attach the second VM. These are **new, empty** disks in `D:\VMs\rac-op\shared`; the manual lab's disks stay with the manual lab. Don't snapshot the workers: VirtualBox can't snapshot a VM with shareable disks. Creating the fixed disks takes a few minutes.

```powershell
# PowerShell
$VB = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"; $Base = "D:\VMs\rac-op"
New-Item -ItemType Directory -Force -Path "$Base\shared" | Out-Null
foreach ($w in "op-worker1","op-worker2") { & $VB storageattach $w --storagectl SATA --port 5 --device 0 --medium none }
foreach ($disk in @(@{n="asm1";gb=50;port=3}, @{n="asm2";gb=50;port=4}, @{n="vote1";gb=10;port=5})) {
  $f = "$Base\shared\$($disk.n).vdi"
  & $VB createmedium disk --filename $f --size ($disk.gb*1024) --variant Fixed
  & $VB modifymedium disk $f --type shareable
  foreach ($w in "op-worker1","op-worker2") { & $VB storageattach $w --storagectl SATA --port $disk.port --device 0 --type hdd --medium $f --mtype shareable }
}
foreach ($d in "vote1","asm1","asm2") { & $VB showmediuminfo disk "$Base\shared\$d.vdi" | Select-String '^(UUID|Location|Type|Capacity|In use by VMs):|op-worker' }
```

**Check:** for **each** of the three disks, `Type: shareable`, a `Location` under `D:\VMs\rac-op\shared`, the right `Capacity` (10240 MBytes for `vote1`, 51200 for the others), and both `op-worker1` and `op-worker2` under "In use by VMs".

**This lab's output:**

```text
Medium created. UUID: 74717f76-da51-4430-87ce-3b192212f46e      (asm1)
Medium created. UUID: 204551ec-9ae3-4871-b2b9-8c68f5569e80      (asm2)
Medium created. UUID: 67cb0647-d253-4702-8823-e8628f6c6980      (vote1)

UUID:           67cb0647-d253-4702-8823-e8628f6c6980
Type:           shareable
Capacity:       10240 MBytes
In use by VMs:  op-worker1 (UUID: 8164c82b-4b03-49a4-b193-671b310c6962)
                op-worker2 (UUID: 05c9cfea-2eba-4f10-8c54-9c1b2919b592)
UUID:           74717f76-da51-4430-87ce-3b192212f46e
Type:           shareable
Location:       D:\VMs\rac-op\shared\asm1.vdi
In use by VMs:  op-worker1 (UUID: 8164c82b-…)
                op-worker2 (UUID: 05c9cfea-…)
UUID:           204551ec-9ae3-4871-b2b9-8c68f5569e80
Type:           shareable
Location:       D:\VMs\rac-op\shared\asm2.vdi
In use by VMs:  op-worker1 (UUID: 8164c82b-…)
                op-worker2 (UUID: 05c9cfea-…)
```

In this lab `asm1` and `asm2` were created first, in an earlier version of this block, and `vote1` was added later to the running lab (below). The UUIDs are what 10.1 uses to find each disk inside the workers.

**Adding vote1 to a lab built with only asm1 and asm2** (what this lab did). Nothing may have been applied yet (`kubectl -n rac get racdatabase` says `No resources found`); the workers are powered off for the change.

```powershell
# PowerShell
$VB = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"; $Base = "D:\VMs\rac-op"; $f = "$Base\shared\vote1.vdi"
foreach ($w in "op-worker1","op-worker2") { & $VB controlvm $w acpipowerbutton }
foreach ($w in "op-worker1","op-worker2") { while ("$(& $VB showvminfo $w --machinereadable | Select-String '^VMState=')" -notmatch 'poweroff') { Start-Sleep 5 }; "$w is off" }
& $VB createmedium disk --filename $f --size 10240 --variant Fixed
& $VB modifymedium disk $f --type shareable
foreach ($w in "op-worker1","op-worker2") {
  & $VB storageattach $w --storagectl SATA --port 5 --device 0 --medium none
  & $VB storageattach $w --storagectl SATA --port 5 --device 0 --type hdd --medium $f --mtype shareable
}
& $VB showmediuminfo disk $f | Select-String '^(UUID|Type|Capacity|In use by VMs):|op-worker'
foreach ($w in "op-worker1","op-worker2") { & $VB startvm $w --type headless }
```

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
kubectl wait --for=condition=Ready node/op-worker1 node/op-worker2 --timeout=600s
kubectl -n oracle-database-operator-system get pods
kubectl -n kube-system get pods -o wide | grep -E 'multus|flannel|calico' | grep -v Running
```

**Check:** `Type: shareable`, `Capacity: 10240 MBytes`, both workers under "In use by VMs"; both nodes `condition met`, the operator pod `Running`, and nothing printed by the last line.

**This lab's output:**

```text
op-worker1 is off
op-worker2 is off
Medium created. UUID: 67cb0647-d253-4702-8823-e8628f6c6980
UUID:           67cb0647-d253-4702-8823-e8628f6c6980
Type:           shareable
Capacity:       10240 MBytes
In use by VMs:  op-worker1 (UUID: 8164c82b-4b03-49a4-b193-671b310c6962)
                op-worker2 (UUID: 05c9cfea-2eba-4f10-8c54-9c1b2919b592)
VM "op-worker1" has been successfully started.
VM "op-worker2" has been successfully started.
node/op-worker1 condition met
node/op-worker2 condition met
NAME                                                           READY   STATUS    RESTARTS   AGE
oracle-database-operator-controller-manager-54cf89dd45-f644n   1/1     Running   1          12h
```

The operator pod shows `RESTARTS 1` because it ran on a worker that was just restarted.
