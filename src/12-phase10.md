## Phase 10: The ASM disks and the room on the workers

**Result of this phase:** the three shared disks' stable names, the same on both workers and saved on op-controlplane for the `RacDatabase`, and the memory, CPU and hugepages each worker can give a RAC pod.

**Why no PVs by hand:** in the manual lab you created the ASM PersistentVolumes and claims yourself (its Phase 7). Here the `RacDatabase` lists the disks' paths on the workers, and the operator creates the PVs from them. It only needs the right names.

### 10.1 Find the disks' by-id names (from the PC)

**Why by-id and not `/dev/sdd`:** `sdX` letters depend on discovery order and can differ between the workers. The by-id name comes from the disk's serial number, which VirtualBox derives from the VDI's UUID, so it's the same on both workers.

The block looks up each disk's UUID, finds its by-id name on both workers, checks they match and that the disk is blank, and saves the three paths on op-controlplane as `VOTE=`, `DATA=` and `FRA=` lines in `/root/rac-op/asm-disks` for the `RacDatabase`.

```powershell
# PowerShell
$VB = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"; $Base = "D:\VMs\rac-op"
$ASM = [ordered]@{}; $Disks = [ordered]@{VOTE="vote1"; DATA="asm1"; FRA="asm2"}
foreach ($d in $Disks.GetEnumerator()) {
  $pre = ((& $VB showmediuminfo disk "$Base\shared\$($d.Value).vdi") | Select-String '^UUID:\s+([0-9a-f]{8})').Matches[0].Groups[1].Value
  $w1 = ssh -p 2221 root@127.0.0.1 "ls /dev/disk/by-id/ | grep -v part | grep ^ata-VBOX_HARDDISK_VB$pre-"
  $w2 = ssh -p 2222 root@127.0.0.1 "ls /dev/disk/by-id/ | grep -v part | grep ^ata-VBOX_HARDDISK_VB$pre-"
  $blank = ssh -p 2221 root@127.0.0.1 "blkid -p /dev/disk/by-id/$w1 >/dev/null 2>&1 && echo used || echo blank"
  if ($w1 -and ($w1 -eq $w2) -and (@($w1).Count -eq 1)) { $ASM[$d.Key] = "/dev/disk/by-id/$w1"; "OK    $($d.Key) ($($d.Value)) = $w1 (same on both workers, $blank)" }
  else { "STOP  $($d.Key) ($($d.Value), VB$pre): op-worker1 sees '$w1', op-worker2 sees '$w2'" }
}
if ($ASM.Count -eq 3) {
  ($ASM.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join "`n" | ssh -p 2220 root@127.0.0.1 "tr -d '\r' > /root/rac-op/asm-disks; cat /root/rac-op/asm-disks"
}
```

**Check:** three `OK` lines (`VOTE`, `DATA`, `FRA`), each ending in `blank`, then the three `VOTE=…`, `DATA=…`, `FRA=…` lines as saved on op-controlplane. `used` instead of `blank` means the disk carries a signature from earlier use; ASM refuses such disks, so stop and paste the output.

**This lab's output:**

```text
OK    VOTE (vote1) = ata-VBOX_HARDDISK_VB67cb0647-80696c8f (same on both workers, blank)
OK    DATA (asm1) = ata-VBOX_HARDDISK_VB74717f76-6ef41222 (same on both workers, blank)
OK    FRA (asm2) = ata-VBOX_HARDDISK_VB204551ec-809e56f5 (same on both workers, blank)
VOTE=/dev/disk/by-id/ata-VBOX_HARDDISK_VB67cb0647-80696c8f
DATA=/dev/disk/by-id/ata-VBOX_HARDDISK_VB74717f76-6ef41222
FRA=/dev/disk/by-id/ata-VBOX_HARDDISK_VB204551ec-809e56f5
```

**This lab's output (the first version of this block, on Windows PowerShell 5.1: [ordered]@{…} can't be followed directly by .GetEnumerator(); the block now builds the list in $Disks first. Nothing was saved, because the save step only runs when all three disks were found):**

```text
foreach ($d in [ordered]@{VOTE="vote1"; DATA="asm1"; FRA="asm2"}.GetEnumerator()) {
The ordered attribute can be specified only on a hash literal node.
    + CategoryInfo          : ParserError: (:) [], ParentContainsErrorRecordException
    + FullyQualifiedErrorId : OrderedAttributeOnlyOnHashLiteralNode
```

### 10.2 What each worker can give a RAC pod (op-controlplane)

**Why it matters here:** the operator's admission check refuses a `RacDatabase` whose pods get less than **16 GiB** of memory, and it wants the SGA to fit into the hugepages. The manual lab ran its pods with 12 GiB. This shows what Kubernetes has left on each worker after the system and the pods already running there, including the operator's own controllers.

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
for w in op-worker1 op-worker2; do
  echo "--- $w allocatable: $(kubectl get node $w -o jsonpath='cpu={.status.allocatable.cpu} memory={.status.allocatable.memory} hugepages-2Mi={.status.allocatable.hugepages-2Mi}')"
  kubectl describe node $w | sed -n '/Allocated resources/,/Events/p' | grep -E '^\s+(cpu|memory|hugepages-2Mi)\s'
done
```

**Check:** note for each worker the allocatable `memory` (about 18 GiB is expected: 22 GB minus the 4 GiB of hugepages) and `hugepages-2Mi` (`4Gi`), and how much memory is already requested. Paste the output: the sizes in Phase 11 are chosen from it.

**This lab's output:**

```text
--- op-worker1 allocatable: cpu=4 memory=17845504Ki hugepages-2Mi=4Gi
  cpu                600m (15%)  500m (12%)
  memory             500Mi (2%)  450Mi (2%)
  hugepages-2Mi      0 (0%)      0 (0%)
--- op-worker2 allocatable: cpu=4 memory=17845504Ki hugepages-2Mi=4Gi
  cpu                1 (25%)     900m (22%)
  memory             900Mi (5%)  850Mi (4%)
  hugepages-2Mi      0 (0%)      0 (0%)
```
