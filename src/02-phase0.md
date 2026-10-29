## Phase 0: Windows host and the operator lab's port forwards

**Result of this phase:** a clean starting point for the operator lab, the PC checked for room, and SSH port forwards 2220–2222 on the shared `k8s-public` network. The manual lab and the golden VM are not touched.

### 0.0 Start clean (only if you built the operator lab before)

**What:** removes an earlier operator lab: the VMs `op-controlplane`, `op-worker1`, `op-worker2`, the folder `D:\VMs\rac-op` with all its disks, the operator lab's port-forward rules, and the SSH host keys remembered for ports 2220–2222. On a first build it just reports that there's nothing to remove.

**What it never touches:** `ol98-golden`, `controlplane`, `worker1`, `worker2`, `D:\VMs\rac-poc` and the `k8s-public` network itself. Every name in the block starts with `op-` or `rac-op`.

```powershell
# PowerShell
$VB = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"; $Base = "D:\VMs\rac-op"
$existing = (& $VB list vms) -join "`n"
foreach ($v in "op-worker1","op-worker2","op-controlplane") {
  if ($existing -match ('"' + $v + '"')) { & $VB controlvm $v poweroff 2>$null; Start-Sleep 3; & $VB unregistervm $v --delete; "removed VM $v" }
}
$left = (& $VB list hdds) | Select-String '^Location:\s+(.*)$' | ForEach-Object { $_.Matches[0].Groups[1].Value } | Where-Object { $_ -like "$Base\*" }
foreach ($d in $left) { & $VB closemedium disk $d --delete; "removed disk $d" }
if (Test-Path $Base) { Remove-Item $Base -Recurse -Force; "removed folder $Base" }
foreach ($r in "ssh-opcp","ssh-opw1","ssh-opw2","k8sapi-op") { & $VB natnetwork modify --netname k8s-public --port-forward-4 delete $r 2>$null }
foreach ($f in "$env:USERPROFILE\.ssh\known_hosts", "$env:USERPROFILE\.ssh\known_hosts_rac_lab") {
  if (Test-Path $f) { foreach ($p in 2220, 2221, 2222) { ssh-keygen -R "[127.0.0.1]:$p" -f $f 2>$null | Out-Null } }
}
"--- VMs (the manual lab and ol98-golden must still be listed; no op-*) ---"
& $VB list vms
```

**Check:** `list vms` still shows `ol98-golden`, `controlplane`, `worker1` and `worker2`, and no `op-*` VM.

**This lab's output:**

```text
PS> & $VB list vms        (first build: nothing to remove, so no "removed …" lines before this)
--- VMs (the manual lab and ol98-golden must still be listed; no op-*) ---
…                                   (other VMs on this PC)
"ol98-golden" {9c69f3bd-2c8a-420a-914b-ad3922917b45}
"controlplane" {779954cf-d37f-45c4-86b3-ee95bc0ee6dc}
"worker1" {4a3c7ad5-0e74-4f94-a556-81aa2795b42e}
"worker2" {5f7040de-3e38-4246-b6b7-f26966b40cd7}
```

### 0.1 Check the host

**Why:** the operator lab needs the same memory and CPU as the manual lab, about 48 GB, so only one lab can run at a time. On disk it needs its own room: three fixed ASM disks (110 GB together) are written in full straight away, and the workers' disks grow as they fill.

```powershell
# PowerShell
$VB = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
& $VB list runningvms
Get-CimInstance Win32_Processor | Select-Object NumberOfCores, NumberOfLogicalProcessors
[Math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
Get-PSDrive D | Select-Object @{n='FreeGB';e={[math]::Round($_.Free/1GB)}}
```

**Check:**

- `list runningvms` prints **nothing**: the manual lab and the golden VM are off;
- 8 or more logical processors and about 64 GB of RAM;
- **300 GB or more free on D:**. Less than about 150 GB stops you at 3.3, when the ASM disks are created.

**This lab's output:**

```text
PS> & $VB list runningvms
                                    (nothing: no VM running)
NumberOfCores NumberOfLogicalProcessors
------------- -------------------------
            8                         8
64

FreeGB
------
  1166
```

### 0.2 SSH key and lab SSH settings (already done)

The manual lab's Phase 0.2 set these up, and they cover every port on `127.0.0.1`, including 2220–2222. This block only checks them; it changes nothing that is already there.

```powershell
# PowerShell
if (-not (Test-Path "$env:USERPROFILE\.ssh\id_ed25519")) { ssh-keygen -t ed25519 }   # press Enter at every prompt
Select-String -Path "$env:USERPROFILE\.ssh\config" -Pattern '^Host 127\.0\.0\.1$' -Context 0,5
```

**Check:** the `Host 127.0.0.1` section with its five settings (`User root`, `StrictHostKeyChecking no`, `UserKnownHostsFile ~/.ssh/known_hosts_rac_lab`, `LogLevel ERROR`, `ServerAliveInterval 30`). If nothing prints, run the manual guide's 0.2 block once.

**This lab's output:**

```text
> C:\Users\alpoo\.ssh\config:2:Host 127.0.0.1
  C:\Users\alpoo\.ssh\config:3:    User root
  C:\Users\alpoo\.ssh\config:4:    StrictHostKeyChecking no
  C:\Users\alpoo\.ssh\config:5:    UserKnownHostsFile ~/.ssh/known_hosts_rac_lab
  C:\Users\alpoo\.ssh\config:6:    LogLevel ERROR
  C:\Users\alpoo\.ssh\config:7:    ServerAliveInterval 30
```

### 0.3 Port forwards for the operator lab

**What:** three SSH forwards on the existing `k8s-public` network: 2220 → op-controlplane, 2221 → op-worker1, 2222 → op-worker2. The golden VM's forward, 2205 → 10.0.1.5, is already there and is reused for personalising the clones in Phase 4.

**Why on the same network:** the two labs never run at the same time, so they can share `k8s-public` and its NAT. Different IPs (.20–.22) and different ports keep them apart; the rule names start with `ssh-op` so 0.0 can remove exactly these.

```powershell
# PowerShell
$VB = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
& $VB natnetwork modify --netname k8s-public --port-forward-4 "ssh-opcp:tcp:[]:2220:[10.0.1.20]:22"
& $VB natnetwork modify --netname k8s-public --port-forward-4 "ssh-opw1:tcp:[]:2221:[10.0.1.21]:22"
& $VB natnetwork modify --netname k8s-public --port-forward-4 "ssh-opw2:tcp:[]:2222:[10.0.1.22]:22"
& $VB natnetwork list
```

**Check:** `natnetwork list` shows `k8s-public` with the manual lab's rules (`ssh-golden`, `ssh-cp`, `ssh-w1`, `ssh-w2`, and any NodePort rules) **plus** `ssh-opcp`, `ssh-opw1` and `ssh-opw2`. If a line says the rule already exists, it was added before; that's fine.

**This lab's output:**

```text
Name:         k8s-public
Enabled:      Yes
Network:      10.0.1.0/24
Gateway:      10.0.1.1
DHCP Server:  No
…
Port-forwarding (ipv4)
        k8sapi:tcp:[]:6443:[10.0.1.10]:6443
        np30200:tcp:[]:30200:[10.0.1.11]:30200
        np30203:tcp:[]:30203:[10.0.1.11]:30203
        np30204:tcp:[]:30204:[10.0.1.11]:30204
        ssh-cp:tcp:[]:2210:[10.0.1.10]:22
        ssh-golden:tcp:[]:2205:[10.0.1.5]:22
        ssh-opcp:tcp:[]:2220:[10.0.1.20]:22
        ssh-opw1:tcp:[]:2221:[10.0.1.21]:22
        ssh-opw2:tcp:[]:2222:[10.0.1.22]:22
        ssh-w1:tcp:[]:2211:[10.0.1.11]:22
        ssh-w2:tcp:[]:2212:[10.0.1.12]:22
```
