## Phase 14: Full shutdown and cold start of the VMs

**Result of this phase:** the whole lab survives a shutdown of all three VMs and comes back with **no manual step**: Kubernetes, the RAC pods, Grid, Clusterware, the database, `ORCLPDB` on both instances, the operator's `AVAILABLE`, and the Phase 12 access from Windows. The phase ends with a start/stop runbook (14.6) to use whenever the PC is shut down.

**What this phase found:**

- **How you stop the database decides whether it starts by itself.** `srvctl stop database` sets the database resource's target to `OFFLINE`; Clusterware keeps that target across restarts, so after a cold start everything came back except the database, which needed `srvctl start database` (first cycle, 14.2–14.4). `crsctl stop crs` alone shuts each instance down with its stop option (`immediate`) but leaves the target `ONLINE`; after the second cold start the database opened by itself (14.5).
- **The guard from Phase 13 works after a cold start too.** On both pods the setup script restored Grid's files (`restore_gi_files`, `rootcrs.sh -updateosfiles`), found Grid configured, and skipped the database block (`SKIP_DBCA`): no DBCA.
- **Each VM boot gives each RAC pod a new container** (restart count +1) and new pod IP; the StatefulSets don't roll (current and update revision unchanged). Clusterware moves the VIPs and SCAN to the new IPs, and the Services' endpoints follow by themselves.
- **Timing:** about 1 minute from VM start to the Kubernetes API; Grid restored about 3–4 minutes after the VMs start; pods `Ready` after 6–9 minutes; with the target `ONLINE`, both instances open about 11 minutes after the VMs were started.
- **The operator lags behind.** After a start it shows `racdb` `PENDING` (and once the connect string `…/ORCLPDB`) until its next check, about every 2 minutes; then `AVAILABLE` with `orclpdbsvc` again.

**What happened, in order** (times US Eastern, 29 October 2026):

| Time | Step | What happened |
| --- | --- | --- |
| 20:54–20:58 | 14.1 | baseline: all as after Phase 13; manual OCR backup; the 10/0 SCAN test explained by load balancing |
| 20:59–21:01 | 14.2 a | clean stop, first way: `srvctl stop database`, then `crsctl stop crs` on both pods |
| 21:02–21:03 | 14.2 b | VMs shut down from inside (workers, then op-controlplane), all off at 21:03:22 |
| 21:04–21:06 | 14.3 a | op-controlplane started, API ready after 53 s, workers started |
| 21:06–21:11 | 14.3 b | new containers, Grid restored, Clusterware up, pods `Ready` at 21:10:30 and 21:11:01; database stays down (target `OFFLINE`) |
| 21:14–21:18 | 14.4 | database started by hand (21:14:16–21:16:51); `racdb` `AVAILABLE` at 21:18:07 |
| 21:20–21:21 | 14.5 a | clean stop, second way: `crsctl stop crs` only (64 s) |
| 21:22–21:24 | 14.5 b | VMs shut down, all off at 21:24:10 |
| 21:24–21:26 | 14.5 c | VMs started, API ready after 59 s |
| 21:27–21:36 | 14.5 d | ORCLCDB2 open by itself at 21:33:40, ORCLCDB1 at 21:35:44; no manual step |

### 14.1 Baseline before the shutdown

**What:** record everything a cold start has to bring back, so the result can be compared; take a manual OCR backup; run the SCAN test from Windows. Only reads, apart from the OCR backup.

**a.**

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
cd /root/rac-op
echo "=== nodes / operator / RAC pods"
kubectl get nodes -o wide
kubectl -n oracle-database-operator-system get pods
kubectl -n rac get pods -o wide; kubectl -n rac get racdatabase racdb
kubectl -n rac get sts racnode1 racnode2 -o custom-columns='NAME:.metadata.name,CURRENT:.status.currentRevision,UPDATE:.status.updateRevision'
echo "=== guard in the env ConfigMaps"
for c in racnode1racdb-cmap racnode2racdb-cmap; do echo "$c: $(kubectl -n rac get cm $c -o jsonpath='{.data.envfile}' | grep -cE '^SKIP_DBCA=true$') SKIP_DBCA line(s), $(kubectl -n rac get cm $c -o jsonpath='{.data.envfile}' | grep -c '=') keys"; done
echo "=== autostart: CRS on each pod, database policy"
for p in racnode1-0 racnode2-0; do echo "$p: $(kubectl -n rac exec $p -c $p -- /u01/app/19c/grid/bin/crsctl config crs 2>&1 | tr '\n' ' ')"; done
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - oracle -c "srvctl config database -d ORCLCDB | grep -E 'Management policy|Start option|Stop option'; srvctl status database -d ORCLCDB; srvctl status service -d ORCLCDB"
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - grid -c "srvctl config nodeapps | grep 'VIP IPv4'; srvctl config scan | grep 'IPv4 VIP'"
echo "=== PDB, saved state, local_listener"
kubectl -n rac exec -i racnode1-0 -c racnode1-0 -- su - oracle -c "export ORACLE_SID=ORCLCDB1; sqlplus -s / as sysdba" <<'EOF'
set lines 200 pages 50
col value for a90
col name for a10
col con_name for a10
col instance_name for a12
col state for a10
select inst_id, name, open_mode from gv$pdbs where name = 'ORCLPDB' order by 1;
select con_name, instance_name, state from dba_pdb_saved_states order by 2;
select inst_id, value from gv$parameter where name = 'local_listener' order by 1;
EOF
echo "=== manual OCR backup"
kubectl -n rac exec racnode1-0 -c racnode1-0 -- /u01/app/19c/grid/bin/ocrconfig -manualbackup
kubectl -n rac exec racnode1-0 -c racnode1-0 -- /u01/app/19c/grid/bin/ocrconfig -showbackup manual | tail -3
```

**Check:** three nodes `Ready`, the operator `Running`; both pods `1/1`, CURRENT = UPDATE; `1 SKIP_DBCA line(s), 41 keys` for each ConfigMap; `CRS-4622 … autostart is enabled` on both pods; `Management policy: AUTOMATIC`; `ORCLPDB` `READ WRITE` on 1 and 2 with two saved-state rows; the two vip `local_listener` values; a new OCR backup line.

**This lab's output:**

```text
=== nodes / operator / RAC pods
NAME              STATUS   ROLES           AGE     VERSION   INTERNAL-IP   EXTERNAL-IP   OS-IMAGE                  KERNEL-VERSION                             CONTAINER-RUNTIME
op-controlplane   Ready    control-plane   2d21h   v1.36.5   10.0.1.20     <none>        Oracle Linux Server 9.8   5.15.0-325.221.6.6.el9uek.x86_64 (amd64)   cri-o://1.36.7
op-worker1        Ready    worker          2d21h   v1.36.5   10.0.1.21     <none>        Oracle Linux Server 9.8   5.15.0-325.221.6.6.el9uek.x86_64 (amd64)   cri-o://1.36.7
op-worker2        Ready    worker          2d21h   v1.36.5   10.0.1.22     <none>        Oracle Linux Server 9.8   5.15.0-325.221.6.6.el9uek.x86_64 (amd64)   cri-o://1.36.7
NAME                                                           READY   STATUS    RESTARTS   AGE
oracle-database-operator-controller-manager-54cf89dd45-f644n   1/1     Running   1          2d12h
NAME         READY   STATUS    RESTARTS   AGE   IP            NODE         NOMINATED NODE   READINESS GATES
racnode1-0   1/1     Running   0          25m   10.244.1.10   op-worker1   <none>           <none>
racnode2-0   1/1     Running   0          25m   10.244.2.8    op-worker2   <none>           <none>
NAME    DBNAME    DBSTATE   ROLE      VERSION       PDB CONNECT STR                STATE
racdb   ORCLCDB   OPEN      PRIMARY   19.32.0.0.0   racnode-scan:1521/orclpdbsvc   AVAILABLE
NAME       CURRENT               UPDATE
racnode1   racnode1-75fbb798ff   racnode1-75fbb798ff
racnode2   racnode2-c48dbfc47    racnode2-c48dbfc47
=== guard in the env ConfigMaps
racnode1racdb-cmap: 1 SKIP_DBCA line(s), 41 keys
racnode2racdb-cmap: 1 SKIP_DBCA line(s), 41 keys
=== autostart: CRS on each pod, database policy
racnode1-0: CRS-4622: Oracle High Availability Services autostart is enabled.
racnode2-0: CRS-4622: Oracle High Availability Services autostart is enabled.
Start options: open
Stop options: immediate
Management policy: AUTOMATIC
Instance ORCLCDB1 is running on node racnode1-0
Instance ORCLCDB2 is running on node racnode2-0
Service orclpdbsvc is running on instance(s) ORCLCDB1,ORCLCDB2
VIP IPv4 Address: 10.244.1.10
VIP IPv4 Address: 10.244.2.8
SCAN 1 IPv4 VIP: 10.244.1.10
SCAN 2 IPv4 VIP: 10.244.2.8
=== PDB, saved state, local_listener

   INST_ID NAME       OPEN_MODE
---------- ---------- ----------
         1 ORCLPDB    READ WRITE
         2 ORCLPDB    READ WRITE


CON_NAME   INSTANCE_NAM STATE
---------- ------------ ----------
ORCLPDB    ORCLCDB1     OPEN
ORCLPDB    ORCLCDB2     OPEN


   INST_ID VALUE
---------- ------------------------------------------------------------------------------------------
         1 (ADDRESS=(PROTOCOL=TCP)(HOST=racnode1-0-vip.rac.svc.cluster.local)(PORT=31522))
         2 (ADDRESS=(PROTOCOL=TCP)(HOST=racnode2-0-vip.rac.svc.cluster.local)(PORT=31523))

=== manual OCR backup

racnode2-0     2026/10/30 00:54:50     +VOTEDG:/racnode-c/OCRBACKUP/backup_20261030_005450.ocr.265.1247964891     1753837251

racnode1-0     2026/10/29 23:57:58     +VOTEDG:/racnode-c/OCRBACKUP/backup_20261029_235758.ocr.263.1247961479     1753837251
racnode2-0     2026/10/30 00:54:50     +VOTEDG:/racnode-c/OCRBACKUP/backup_20261030_005450.ocr.265.1247964891     1753837251

racnode1-0     2026/10/29 23:57:58     +VOTEDG:/racnode-c/OCRBACKUP/backup_20261029_235758.ocr.263.1247961479     1753837251
```

The OCR backup times are UTC: `00:54:50` is 20:54:50 Eastern. Clusterware wrote it on racnode2-0, whichever node holds the OCR master.

**b. The VM layer and the SCAN test** (type the password at the prompt):

```powershell
# Windows PowerShell  (connect: local, on your PC)
$VB = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
& $VB list runningvms
foreach ($p in 2220,2221,2222) { "=== port $p"; ssh -p $p root@127.0.0.1 'hostname -s; uptime -p; systemctl is-enabled kubelet crio; grep HugePages_Total /proc/meminfo; free -g | grep Mem' }
python D:\rac-k8s-poc-operator\scan_test.py
```

**Check:** only the three `op-*` VMs; `enabled enabled` on each node; 2048 hugepages on both workers; the test reaches the database.

**This lab's output:**

```text
"op-controlplane" {e4aec2c6-bbe6-439e-a4bd-e0743189316f}
"op-worker1" {8164c82b-4b03-49a4-b193-671b310c6962}
"op-worker2" {05c9cfea-2eba-4f10-8c54-9c1b2919b592}
=== port 2220
op-controlplane
up 2 days, 22 hours, 10 minutes
enabled
enabled
HugePages_Total:       0
Mem:               3           1           0           0           1           2
=== port 2221
op-worker1
up 2 days, 38 minutes
enabled
enabled
HugePages_Total:    2048
Mem:              21           8           3           1          10          12
=== port 2222
op-worker2
up 2 days, 38 minutes
enabled
enabled
HugePages_Total:    2048
Mem:              21           8           2           1          11          12
SYSTEM password:
 1  ORCLCDB2  racnode2-0  ORCLPDB
 2  ORCLCDB2  racnode2-0  ORCLPDB
 3  ORCLCDB2  racnode2-0  ORCLPDB
 4  ORCLCDB2  racnode2-0  ORCLPDB
 5  ORCLCDB2  racnode2-0  ORCLPDB
 6  ORCLCDB2  racnode2-0  ORCLPDB
 7  ORCLCDB2  racnode2-0  ORCLPDB
 8  ORCLCDB2  racnode2-0  ORCLPDB
 9  ORCLCDB2  racnode2-0  ORCLPDB
10  ORCLCDB2  racnode2-0  ORCLPDB
oracledb 26.0.1 thin mode: True
connections per instance: {'ORCLCDB2': 10}
```

**c. Why every connection went to ORCLCDB2** (read-only, then the test again):

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - grid -c "srvctl status scan_listener; srvctl status listener -listener LISTENER"
for p in racnode1-0 racnode2-0; do
  for l in LISTENER_SCAN1 LISTENER_SCAN2 LISTENER; do
    echo "=== $p $l: orclpdbsvc handlers"
    kubectl -n rac exec $p -c $p -- su - grid -c "lsnrctl services $l 2>/dev/null | sed -n '/Service \"orclpdbsvc/,/^Service /p' | grep -E 'Service|Instance|DEDICATED|REMOTE|ADDRESS|established'"
  done
done
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - oracle -c "srvctl config service -d ORCLCDB -s orclpdbsvc | grep -E 'Preferred|Available|Connection Load|Runtime Load|Service role'"
kubectl -n rac exec -i racnode1-0 -c racnode1-0 -- su - oracle -c "export ORACLE_SID=ORCLCDB1; sqlplus -s / as sysdba" <<'EOF'
set lines 200 pages 50
col value for a90
select inst_id, value from gv$parameter where name = 'remote_listener' order by 1;
select inst_id, count(*) sessions from gv$session where type = 'USER' group by inst_id order by 1;
EOF
kubectl -n rac get endpoints racnode-scan-lsnr racnode1-0-lsnr-ext racnode2-0-lsnr-ext
```

```powershell
# Windows PowerShell  (connect: local, on your PC)
Test-NetConnection 127.0.0.1 -Port 31522 | Select-Object TcpTestSucceeded
Test-NetConnection 127.0.0.1 -Port 31523 | Select-Object TcpTestSucceeded
python D:\rac-k8s-poc-operator\scan_test.py
```

**Check:** both SCAN listeners have a handler for each instance; both `remote_listener` values point at SCAN; the endpoints carry the current pod IPs; both ports `True`.

**This lab's output** (a SCAN listener runs on only one pod, so `exit code 1` for the other is expected):

```text
SCAN Listener LISTENER_SCAN1 is enabled
SCAN listener LISTENER_SCAN1 is running on node racnode1-0
SCAN Listener LISTENER_SCAN2 is enabled
SCAN listener LISTENER_SCAN2 is running on node racnode2-0
Listener LISTENER is enabled
Listener LISTENER is running on node(s): racnode1-0,racnode2-0
=== racnode1-0 LISTENER_SCAN1: orclpdbsvc handlers
Service "orclpdbsvc" has 2 instance(s).
  Instance "ORCLCDB1", status READY, has 1 handler(s) for this service...
      "DEDICATED" established:6 refused:0 state:ready
         REMOTE SERVER
         (ADDRESS=(PROTOCOL=TCP)(HOST=racnode1-0-vip.rac.svc.cluster.local)(PORT=31522))
  Instance "ORCLCDB2", status READY, has 1 handler(s) for this service...
      "DEDICATED" established:15 refused:0 state:ready
         REMOTE SERVER
         (ADDRESS=(PROTOCOL=TCP)(HOST=racnode2-0-vip.rac.svc.cluster.local)(PORT=31523))
=== racnode1-0 LISTENER_SCAN2: orclpdbsvc handlers
command terminated with exit code 1
=== racnode1-0 LISTENER: orclpdbsvc handlers
Service "orclpdbsvc" has 1 instance(s).
  Instance "ORCLCDB1", status READY, has 1 handler(s) for this service...
      "DEDICATED" established:6 refused:0 state:ready
=== racnode2-0 LISTENER_SCAN1: orclpdbsvc handlers
command terminated with exit code 1
=== racnode2-0 LISTENER_SCAN2: orclpdbsvc handlers
Service "orclpdbsvc" has 2 instance(s).
  Instance "ORCLCDB1", status READY, has 1 handler(s) for this service...
      "DEDICATED" established:0 refused:0 state:ready
         REMOTE SERVER
         (ADDRESS=(PROTOCOL=TCP)(HOST=racnode1-0-vip.rac.svc.cluster.local)(PORT=31522))
  Instance "ORCLCDB2", status READY, has 1 handler(s) for this service...
      "DEDICATED" established:0 refused:0 state:ready
         REMOTE SERVER
         (ADDRESS=(PROTOCOL=TCP)(HOST=racnode2-0-vip.rac.svc.cluster.local)(PORT=31523))
=== racnode2-0 LISTENER: orclpdbsvc handlers
Service "orclpdbsvc" has 1 instance(s).
  Instance "ORCLCDB2", status READY, has 1 handler(s) for this service...
      "DEDICATED" established:15 refused:0 state:ready
Service role: PRIMARY
Connection Load Balancing Goal: LONG
Runtime Load Balancing Goal: NONE
Preferred instances: ORCLCDB1,ORCLCDB2
Available instances:

   INST_ID VALUE
---------- ------------------------------------------------------------------------------------------
         1  racnode-scan:1521
         2  racnode-scan:1521


   INST_ID   SESSIONS
---------- ----------
         1          8
         2          6

Warning: v1 Endpoints is deprecated in v1.33+; use discovery.k8s.io/v1 EndpointSlice
NAME                  ENDPOINTS           AGE
racnode-scan-lsnr     10.244.1.10:1521    2d
racnode1-0-lsnr-ext   10.244.1.10:31522   22h
racnode2-0-lsnr-ext   10.244.2.8:31523    22h

TcpTestSucceeded
----------------
            True

TcpTestSucceeded
----------------
            True

SYSTEM password:
 1  ORCLCDB2  racnode2-0  ORCLPDB
 2  ORCLCDB2  racnode2-0  ORCLPDB
 3  ORCLCDB2  racnode2-0  ORCLPDB
 4  ORCLCDB2  racnode2-0  ORCLPDB
 5  ORCLCDB2  racnode2-0  ORCLPDB
 6  ORCLCDB1  racnode1-0  ORCLPDB
 7  ORCLCDB2  racnode2-0  ORCLPDB
 8  ORCLCDB1  racnode1-0  ORCLPDB
 9  ORCLCDB1  racnode1-0  ORCLPDB
10  ORCLCDB1  racnode1-0  ORCLPDB
oracledb 26.0.1 thin mode: True
connections per instance: {'ORCLCDB2': 6, 'ORCLCDB1': 4}
```

**What it shows:** nothing was wrong. The service's **connection load balancing goal is `LONG`**: SCAN sends each new connection to the instance with fewer sessions. ORCLCDB1 had more user sessions (8 against 6, background agents included), so SCAN kept choosing ORCLCDB2 until the counts evened out; the second run shows exactly that (five to ORCLCDB2, then mixed). A 10/0 result from this test therefore doesn't mean an instance is missing; the handlers in the SCAN listeners do.

**One gap the output also shows** (from Phase 12, not caused here): the operator's `racnode-scan-lsnr` Service has **one** endpoint, racnode1-0's. Windows reaches SCAN only through LISTENER_SCAN1 on racnode1-0, so with racnode1-0 down `127.0.0.1:31521` fails although ORCLCDB2 is up. Listed under open points.

### 14.2 Clean stop, first way: `srvctl stop database`, then Clusterware and the VMs

**Interruption:** the whole lab, until 14.4.

**a. The database, then Clusterware** (racnode2-0 first):

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
date
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - oracle -c "srvctl stop database -d ORCLCDB; srvctl status database -d ORCLCDB"
for p in racnode2-0 racnode1-0; do
  echo "=== crsctl stop crs on $p"
  kubectl -n rac exec $p -c $p -- /u01/app/19c/grid/bin/crsctl stop crs 2>&1 | grep -E 'CRS-279[13]|CRS-4133|CRS-4687|CRS-4000|error|fail'
  kubectl -n rac exec $p -c $p -- /u01/app/19c/grid/bin/crsctl check crs
done
sleep 20
kubectl -n rac get pods -o wide; kubectl -n rac get racdatabase racdb
date
```

**Check:** both instances `not running`; `CRS-4133` then `CRS-4639` on each pod; the pods `0/1` but `Running` (no liveness probe, so Kubernetes doesn't restart them). Go on to b only if both CRS stops completed.

**This lab's output:**

```text
Thu Oct 29 08:59:35 PM EDT 2026
Instance ORCLCDB1 is not running on node racnode1-0
Instance ORCLCDB2 is not running on node racnode2-0
=== crsctl stop crs on racnode2-0
CRS-2791: Starting shutdown of Oracle High Availability Services-managed resources on 'racnode2-0'
CRS-2793: Shutdown of Oracle High Availability Services-managed resources on 'racnode2-0' has completed
CRS-4133: Oracle High Availability Services has been stopped.
CRS-4639: Could not contact Oracle High Availability Services
=== crsctl stop crs on racnode1-0
CRS-2791: Starting shutdown of Oracle High Availability Services-managed resources on 'racnode1-0'
CRS-2793: Shutdown of Oracle High Availability Services-managed resources on 'racnode1-0' has completed
CRS-4133: Oracle High Availability Services has been stopped.
CRS-4639: Could not contact Oracle High Availability Services
NAME                         READY   STATUS        RESTARTS   AGE   IP            NODE         NOMINATED NODE   READINESS GATES
disk-check-daemonset-62zp8   1/1     Terminating   0          33s   10.244.2.9    op-worker2   <none>           <none>
disk-check-daemonset-k2sp9   1/1     Terminating   0          33s   10.244.1.11   op-worker1   <none>           <none>
racnode1-0                   0/1     Running       0          32m   10.244.1.10   op-worker1   <none>           <none>
racnode2-0                   0/1     Running       0          32m   10.244.2.8    op-worker2   <none>           <none>
NAME    DBNAME    DBSTATE        ROLE           VERSION        PDB CONNECT STR   STATE
racdb   ORCLCDB   NOTAVAILABLE   NOTAVAILABLE   NOTAVAILABLE   NOTAVAILABLE      PENDING
Thu Oct 29 09:01:41 PM EDT 2026
```

`disk-check-daemonset`: the operator starts this short-lived disk check on each worker when it reconciles a database that isn't available; it removes it again by itself. `PENDING` is the operator's state for a database it can't reach.

**b. Shut the VMs down from inside the guests,** workers first, then op-controlplane. The block waits up to 5 minutes per VM and never forces a power-off:

```powershell
# Windows PowerShell  (connect: local, on your PC)
$VB = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
function Wait-Off($name) { $t0 = Get-Date; for ($i = 0; $i -lt 60; $i++) { Start-Sleep 5; if (-not ((& $VB list runningvms) -match "`"$name")) { return "$name off after $([int]((Get-Date) - $t0).TotalSeconds) s" } }; return "$name STILL RUNNING after 300 s - stop here, don't force" }
Get-Date
foreach ($p in 2222, 2221) { ssh -o ConnectTimeout=5 -p $p root@127.0.0.1 'hostname -s; systemctl poweroff' }
Wait-Off "op-worker2"; Wait-Off "op-worker1"
ssh -o ConnectTimeout=5 -p 2220 root@127.0.0.1 'hostname -s; systemctl poweroff'
Wait-Off "op-controlplane"
"--- running VMs now:"; & $VB list runningvms
Get-Date
```

**Check:** three `… off after N s` lines and nothing under "running VMs now".

**This lab's output:**

```text
Thursday, October 29, 2026 9:01:59 PM

op-worker2
op-worker1
op-worker2 off after 41 s
op-worker1 off after 5 s
op-controlplane
op-controlplane off after 36 s
--- running VMs now:

Thursday, October 29, 2026 9:03:22 PM
```

Both workers shut down at the same time; `op-worker1 … 5 s` counts only from the moment worker2 was off.

### 14.3 Cold start

**a. op-controlplane first, the workers once the API answers:**

```powershell
# Windows PowerShell  (connect: local, on your PC)
$VB = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
Get-Date
& $VB startvm op-controlplane --type headless
$t0 = Get-Date; $ok = $false
for ($i = 0; $i -lt 60; $i++) { Start-Sleep 5; $r = ssh -o ConnectTimeout=3 -o BatchMode=yes -p 2220 root@127.0.0.1 'kubectl get --raw=/readyz 2>/dev/null' 2>$null; if ($r -eq 'ok') { $ok = $true; break } }
if ($ok) { "API ready after $([int]((Get-Date) - $t0).TotalSeconds) s" } else { "API NOT ready after 300 s - stop here" }
if ($ok) {
  foreach ($n in "op-worker1","op-worker2") { & $VB startvm $n --type headless }
  $t0 = Get-Date
  for ($i = 0; $i -lt 60; $i++) { Start-Sleep 10; $r = ssh -o ConnectTimeout=3 -p 2220 root@127.0.0.1 'kubectl get nodes --no-headers | grep -cw Ready'; if ($r -eq '3') { break } }
  "3 nodes Ready after $([int]((Get-Date) - $t0).TotalSeconds) s"
}
Get-Date
```

**Check:** `API ready after N s`, then both workers started.

**This lab's output** (the first version of the node count used `awk` inside a double-quoted PowerShell string; the escaping left a stray `\` for awk, so the count never worked; the block above has the fixed line, which returned at once when run on its own afterwards):

```text
Thursday, October 29, 2026 9:04:21 PM

Waiting for VM "op-controlplane" to power on...
VM "op-controlplane" has been successfully started.
API ready after 53 s
Waiting for VM "op-worker1" to power on...
VM "op-worker1" has been successfully started.
Waiting for VM "op-worker2" to power on...
VM "op-worker2" has been successfully started.
awk: cmd. line:1: \$2=="Ready"
awk: cmd. line:1: ^ backslash not last character on line
…
```

**The node count is not a real check right after a start:** in 14.5 c the fixed line reported `3 nodes Ready after 11 s`, before the workers could have booted. After the control plane restarts, Kubernetes keeps showing each node's last status until the node controller's grace period runs out. The runbook (14.6) waits for kubelet on the workers instead; the RAC watch below is the real check.

**b. Watch RAC come back** (every 30 s, up to 25 minutes, ends when both instances run):

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
cd /root/rac-op; date
for i in $(seq 1 50); do
  pods=$(kubectl -n rac get pods racnode1-0 racnode2-0 --no-headers -o custom-columns='N:.metadata.name,R:.status.containerStatuses[0].ready,C:.status.containerStatuses[0].restartCount,S:.status.phase' 2>&1 | tr -s ' ' | tr '\n' ' ')
  st=$(kubectl -n rac get racdatabase racdb -o jsonpath='{.status.state}' 2>/dev/null)
  db=$(kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - oracle -c "srvctl status database -d ORCLCDB" 2>&1 | tr '\n' ' ' | cut -c1-140)
  echo "$(date +%T)  [$pods] racdb=$st  $db"
  echo "$db" | grep -q 'ORCLCDB1 is running' && echo "$db" | grep -q 'ORCLCDB2 is running' && break
  sleep 30
done
kubectl -n rac get pods -o wide; kubectl -n rac get racdatabase racdb
kubectl -n rac get events --sort-by=.lastTimestamp | tail -20
```

**This lab's output** (stopped with Ctrl+C at 21:12, see below):

```text
Thu Oct 29 09:06:04 PM EDT 2026
21:06:05  [racnode1-0 false 0 Running racnode2-0 false 0 Running ] racdb=PENDING  error: unable to upgrade connection: error dialing backend: dial tcp 10.0.1.21:10250: connect: connection refused
21:06:35  [racnode1-0 false 1 Running racnode2-0 false 0 Running ] racdb=PENDING  error: unable to upgrade connection: container not found ("racnode1-0")
21:07:06  [racnode1-0 false 1 Running racnode2-0 false 1 Running ] racdb=PENDING  error: unable to upgrade connection: container not found ("racnode1-0")
21:07:38  [racnode1-0 false 1 Running racnode2-0 false 1 Running ] racdb=PENDING  ****Unable to retrieve Oracle Clusterware home. Start Oracle Clusterware stack and try again. command terminated with exit code 1
21:08:09  [racnode1-0 false 1 Running racnode2-0 false 1 Running ] racdb=PENDING  ****Unable to retrieve Oracle Clusterware home. Start Oracle Clusterware stack and try again. command terminated with exit code 1
21:08:56  [racnode1-0 false 1 Running racnode2-0 false 1 Running ] racdb=PENDING  PRKH-1010 : Unable to communicate with CRS services. PRKH-3003 : An attempt to communicate with the CSS daemon failed command terminated wit
21:09:27  [racnode1-0 false 1 Running racnode2-0 false 1 Running ] racdb=PENDING  PRCD-1027 : Failed to retrieve database ORCLCDB PRCR-1070 : Failed to check if resource ora.orclcdb.db is registered CRS-0184 : Cannot commu
21:09:59  [racnode1-0 false 1 Running racnode2-0 false 1 Running ] racdb=PENDING  Instance ORCLCDB1 is not running on node racnode1-0 Instance ORCLCDB2 is not running on node racnode2-0
21:10:30  [racnode1-0 true 1 Running racnode2-0 false 1 Running ] racdb=PENDING  Instance ORCLCDB1 is not running on node racnode1-0 Instance ORCLCDB2 is not running on node racnode2-0
21:11:01  [racnode1-0 true 1 Running racnode2-0 true 1 Running ] racdb=PENDING  Instance ORCLCDB1 is not running on node racnode1-0 Instance ORCLCDB2 is not running on node racnode2-0
21:11:33  [racnode1-0 true 1 Running racnode2-0 true 1 Running ] racdb=PENDING  Instance ORCLCDB1 is not running on node racnode1-0 Instance ORCLCDB2 is not running on node racnode2-0
21:12:04  [racnode1-0 true 1 Running racnode2-0 true 1 Running ] racdb=PENDING  Instance ORCLCDB1 is not running on node racnode1-0 Instance ORCLCDB2 is not running on node racnode2-0
21:12:35  [racnode1-0 true 1 Running racnode2-0 true 1 Running ] racdb=PENDING  Instance ORCLCDB1 is not running on node racnode1-0 Instance ORCLCDB2 is not running on node racnode2-0
```

**How to read the stages:** `connection refused` on port 10250 = kubelet on the worker not up yet; `container not found` = kubelet is creating the new container (restart count 1); `srvctl: command not found` (seen in 14.5) = the setup script hasn't written the user environment yet; `Unable to retrieve Oracle Clusterware home` = Grid's files not restored yet; `PRKH-1010`, `CRS-0184` = Clusterware starting; `not running` with the pods `Ready` = Clusterware up, database not started. Here it stayed at the last stage, because `srvctl stop database` had set the database's target to `OFFLINE` (14.4 confirms). That was also the case in 13.3, where the database was started by hand for the same reason.

### 14.4 Confirm the cause, start the database, check everything

**a.**

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
echo "=== database resource target/state (expect TARGET=OFFLINE)"
kubectl -n rac exec racnode1-0 -c racnode1-0 -- /u01/app/19c/grid/bin/crsctl stat res ora.orclcdb.db -t
kubectl -n rac exec racnode1-0 -c racnode1-0 -- /u01/app/19c/grid/bin/crsctl stat res -t | grep -A3 -E '^ora\.(asm|LISTENER|scan|DATA|FRA|VOTEDG)' | head -40
echo "=== setup log on both pods"
for p in racnode1-0 racnode2-0; do kubectl -n rac exec $p -c $p -- bash -c 'L=/tmp/orod/oracle_db_setup.log; echo "--- $(hostname) statefile: $(cat /tmp/orod/.statefile)"; grep -E "SKIP_DBCA key exists|restore_gi_files invoked|updateosfiles|already configured|Total time for setup|create_db|dbca -silent" $L | tail -8'; done
echo "=== start the database"; date
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - oracle -c "srvctl start database -d ORCLCDB; srvctl status database -d ORCLCDB; srvctl status service -d ORCLCDB"; date
kubectl -n rac exec -i racnode1-0 -c racnode1-0 -- su - oracle -c "export ORACLE_SID=ORCLCDB1; sqlplus -s / as sysdba" <<'EOF'
set lines 200 pages 50
col value for a90
col name for a10
select inst_id, name, open_mode from gv$pdbs where name = 'ORCLPDB' order by 1;
select inst_id, value from gv$parameter where name = 'local_listener' order by 1;
EOF
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - grid -c "srvctl config nodeapps | grep 'VIP IPv4'; srvctl config scan | grep 'IPv4 VIP'"
kubectl -n rac get sts racnode1 racnode2 -o custom-columns='NAME:.metadata.name,CURRENT:.status.currentRevision,UPDATE:.status.updateRevision'
kubectl -n rac get pods -o wide; kubectl -n rac get racdatabase racdb
kubectl get endpointslices -n rac -o wide | grep -E 'scan|lsnr-ext'
kubectl -n rac get events --sort-by=.lastTimestamp | tail -15
```

**Check:** `ora.orclcdb.db` `OFFLINE OFFLINE` before the start, everything else `ONLINE`; the guard and `restore_gi_files` in the setup log, no `create_db` or `dbca`; after the start both instances and the service on both; `ORCLPDB` `READ WRITE` on 1 and 2; the two vip `local_listener` values; CURRENT = UPDATE.

**This lab's output:**

```text
=== database resource target/state (expect TARGET=OFFLINE)
--------------------------------------------------------------------------------
Name           Target  State        Server                   State details
--------------------------------------------------------------------------------
Cluster Resources
--------------------------------------------------------------------------------
ora.orclcdb.db
      1        OFFLINE OFFLINE                               Instance Shutdown,ST
                                                             ABLE
      2        OFFLINE OFFLINE                               Instance Shutdown,ST
                                                             ABLE
--------------------------------------------------------------------------------
ora.LISTENER.lsnr
               ONLINE  ONLINE       racnode1-0               STABLE
               ONLINE  ONLINE       racnode2-0               STABLE
ora.chad
--
ora.DATA.dg(ora.asmgroup)
      1        ONLINE  ONLINE       racnode1-0               STABLE
      2        ONLINE  ONLINE       racnode2-0               STABLE
ora.FRA.dg(ora.asmgroup)
      1        ONLINE  ONLINE       racnode1-0               STABLE
      2        ONLINE  ONLINE       racnode2-0               STABLE
ora.LISTENER_SCAN1.lsnr
      1        ONLINE  ONLINE       racnode1-0               STABLE
ora.LISTENER_SCAN2.lsnr
      1        ONLINE  ONLINE       racnode2-0               STABLE
ora.VOTEDG.dg(ora.asmgroup)
      1        ONLINE  ONLINE       racnode1-0               STABLE
      2        ONLINE  ONLINE       racnode2-0               STABLE
ora.asm(ora.asmgroup)
      1        ONLINE  ONLINE       racnode1-0               Started,STABLE
      2        ONLINE  ONLINE       racnode2-0               Started,STABLE
ora.asmnet1.asmnetwork(ora.asmgroup)
      1        ONLINE  ONLINE       racnode1-0               STABLE
      2        ONLINE  ONLINE       racnode2-0               STABLE
ora.asmnet2.asmnetwork(ora.asmgroup)
      1        ONLINE  ONLINE       racnode1-0               STABLE
      2        ONLINE  ONLINE       racnode2-0               STABLE
ora.cvu
--
ora.scan1.vip
      1        ONLINE  ONLINE       racnode1-0               STABLE
ora.scan2.vip
      1        ONLINE  ONLINE       racnode2-0               STABLE
--------------------------------------------------------------------------------
=== setup log on both pods
--- racnode1-0 statefile: provisioning
10/30/2026 01:07:23 AM     INFO:   oracommon   - populateracenvvars :SKIP_DBCA key exists with value true
10/30/2026 01:08:07 AM     INFO:   oracommon   -   restoregifiles   :restore_gi_files invoked (Oracle major version: 19)
10/30/2026 01:08:07 AM     INFO:   oracommon   -   executeprocess   :Received Command : /u01/app/19c/grid/crs/install/rootcrs.sh -updateosfiles
10/30/2026 01:09:03 AM     INFO:  oramachine   -       setup        :Total time for setup() = [ 103.557 ] seconds
          Grid is already configured on this machine
10/30/2026 01:09:19 AM     INFO:   oragiprov   -       setup        :Total time for setup() = [ 16.214 ] seconds
10/30/2026 01:13:17 AM     INFO:  oraracprov   -       setup        :Total time for setup() = [ 254.485 ] seconds
--- racnode2-0 statefile: provisioning
10/30/2026 01:07:40 AM     INFO:   oracommon   - populateracenvvars :SKIP_DBCA key exists with value true
10/30/2026 01:08:27 AM     INFO:   oracommon   -   restoregifiles   :restore_gi_files invoked (Oracle major version: 19)
10/30/2026 01:08:27 AM     INFO:   oracommon   -   executeprocess   :Received Command : /u01/app/19c/grid/crs/install/rootcrs.sh -updateosfiles
10/30/2026 01:09:02 AM     INFO:  oramachine   -       setup        :Total time for setup() = [ 82.257 ] seconds
=== start the database
Thu Oct 29 09:14:16 PM EDT 2026
Instance ORCLCDB1 is running on node racnode1-0
Instance ORCLCDB2 is running on node racnode2-0
Service orclpdbsvc is running on instance(s) ORCLCDB1,ORCLCDB2
Thu Oct 29 09:16:51 PM EDT 2026

   INST_ID NAME       OPEN_MODE
---------- ---------- ----------
         1 ORCLPDB    READ WRITE
         2 ORCLPDB    READ WRITE


   INST_ID VALUE
---------- ------------------------------------------------------------------------------------------
         1 (ADDRESS=(PROTOCOL=TCP)(HOST=racnode1-0-vip.rac.svc.cluster.local)(PORT=31522))
         2 (ADDRESS=(PROTOCOL=TCP)(HOST=racnode2-0-vip.rac.svc.cluster.local)(PORT=31523))

VIP IPv4 Address: 10.244.1.2
VIP IPv4 Address: 10.244.2.2
SCAN 1 IPv4 VIP: 10.244.1.2
SCAN 2 IPv4 VIP: 10.244.2.2
NAME       CURRENT               UPDATE
racnode1   racnode1-75fbb798ff   racnode1-75fbb798ff
racnode2   racnode2-c48dbfc47    racnode2-c48dbfc47
NAME         READY   STATUS    RESTARTS   AGE   IP           NODE         NOMINATED NODE   READINESS GATES
racnode1-0   1/1     Running   1          47m   10.244.1.2   op-worker1   <none>           <none>
racnode2-0   1/1     Running   1          47m   10.244.2.2   op-worker2   <none>           <none>
NAME    DBNAME    DBSTATE   ROLE      VERSION       PDB CONNECT STR             STATE
racdb   ORCLCDB   OPEN      PRIMARY   19.32.0.0.0   racnode-scan:1521/ORCLPDB   PENDING
racnode-scan-69fqn          IPv4          <unset>   10.244.1.2,10.244.2.2   2d
racnode-scan-lsnr-qbpd2     IPv4          1521      10.244.1.2              2d
racnode1-0-lsnr-ext-tgml2   IPv4          31522     10.244.1.2              23h
racnode2-0-lsnr-ext-spfhc   IPv4          31523     10.244.2.2              23h
9m45s       Normal    Started                  pod/racnode1-0                   Container started
9m44s       Normal    Pulled                   pod/racnode1-0                   Container image "localhost/oracle/database-rac:19.3.0-slim" already present on machine and can be accessed by the pod
9m44s       Normal    Started                  pod/racnode1-0                   Container started
9m44s       Normal    Created                  pod/racnode1-0                   Container created
9m38s       Warning   FailedCreatePodSandBox   pod/racnode2-0                   Failed to create pod sandbox: rpc error: code = Unknown desc = failed to create pod network sandbox k8s_racnode2-0_rac_e8ed6d9c-…(c175002c…): error adding pod rac_racnode2-0 to CNI network "multus-cni-network": plugin type="multus-shim" name="multus-cni-network" failed (add): … error adding container to network "cbr0": plugin type="flannel" failed (add): failed to load flannel 'subnet.env' file: open /run/flannel/subnet.env: no such file or directory. Check the flannel pod log for this node....
9m24s       Normal    AddedInterface           pod/racnode2-0                   Add eth0 [10.244.2.2/24] from cbr0
9m23s       Normal    AddedInterface           pod/racnode2-0                   Add eth1 [10.0.11.141/24] from rac/macvlan-conf1
9m23s       Normal    Pulled                   pod/racnode2-0                   Container image "localhost/oracle/database-rac:19.3.0-slim" already present on machine and can be accessed by the pod
9m23s       Normal    AddedInterface           pod/racnode2-0                   Add eth2 [10.0.12.141/24] from rac/macvlan-conf2
9m22s       Normal    Created                  pod/racnode2-0                   Container created
9m22s       Normal    Started                  pod/racnode2-0                   Container started
9m21s       Normal    Pulled                   pod/racnode2-0                   Container image "localhost/oracle/database-rac:19.3.0-slim" already present on machine and can be accessed by the pod
9m21s       Normal    Created                  pod/racnode2-0                   Container created
9m21s       Normal    Started                  pod/racnode2-0                   Container started
6m20s       Warning   Unhealthy                pod/racnode2-0                   Readiness probe failed: dial tcp 10.244.2.2:1522: connect: connection refused
```

**What it shows:** Clusterware brought back everything whose target was `ONLINE` (ASM, the disk groups, the listeners, SCAN); only the database, target `OFFLINE`, stayed down. The guard worked on both pods (no `create_db`, no `dbca`); racnode2-0's grep ends at `oramachine` because its later steps logged nothing matching. The setup log's times are UTC (01:07 = 21:07 Eastern). The new pod IPs are 10.244.1.2 and 10.244.2.2; VIPs, SCAN VIPs and the Services' endpoints all follow. `FailedCreatePodSandBox` is start-up order on worker2: the pod tried to start before flannel had written `/run/flannel/subnet.env`; kubelet retried 14 s later. The readiness failure is the node listener port (1522) before Clusterware started it.

**b. The operator's status, and Windows:**

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
for i in $(seq 1 10); do echo "$(date +%T)  $(kubectl -n rac get racdatabase racdb --no-headers)"; kubectl -n rac get racdatabase racdb -o jsonpath='{.status.state}' | grep -q AVAILABLE && break; sleep 30; done
kubectl -n oracle-database-operator-system logs deploy/oracle-database-operator-controller-manager --since=15m 2>/dev/null | grep -iE 'racdb|rac/' | grep -iE 'state|pending|available|error|pdb|connect' | tail -15
```

```powershell
# Windows PowerShell  (connect: local, on your PC)
python D:\rac-k8s-poc-operator\scan_test.py
```

**This lab's output** (operator log times UTC; the Service lines repeat for all six Services, two shown):

```text
21:17:36  racdb   ORCLCDB   OPEN   PRIMARY   19.32.0.0.0   racnode-scan:1521/ORCLPDB   PENDING
21:18:07  racdb   ORCLCDB   OPEN   PRIMARY   19.32.0.0.0   racnode-scan:1521/orclpdbsvc   AVAILABLE
2026-10-30T01:16:11Z    INFO    controllers.controllers.RacDatabase     Entering reconcile phase        {"controller": "racdatabase", "namespace": "rac", "name": "racdb", "phase": "PendingAndRecovery"}
2026-10-30T01:16:11Z    INFO    controllers.controllers.RacDatabase     Service reconciled to desired state     {"Instance.Namespace": "rac", "Instance.Name": "racdb", "dep.Name": "racnode1-0-vip", "Service.Namespace": "rac", "Service.Name": "racnode1-0-vip"}
…
2026-10-30T01:18:04Z    INFO    controllers.controllers.RacDatabase     Entering reconcile phase        {"controller": "racdatabase", "namespace": "rac", "name": "racdb", "phase": "StateGuard"}
2026-10-30T01:18:04Z    INFO    controllers.controllers.RacDatabase     Entering reconcile phase        {"controller": "racdatabase", "namespace": "rac", "name": "racdb", "phase": "PendingAndRecovery"}
2026-10-30T01:18:04Z    INFO    controllers.controllers.RacDatabase     Service reconciled to desired state     {"Instance.Namespace": "rac", "Instance.Name": "racdb", "dep.Name": "racnode-scan", "Service.Namespace": "rac", "Service.Name": "racnode-scan"}
SYSTEM password:
 1  ORCLCDB2  racnode2-0  ORCLPDB
 2  ORCLCDB1  racnode1-0  ORCLPDB
 3  ORCLCDB2  racnode2-0  ORCLPDB
 4  ORCLCDB1  racnode1-0  ORCLPDB
 5  ORCLCDB2  racnode2-0  ORCLPDB
 6  ORCLCDB2  racnode2-0  ORCLPDB
 7  ORCLCDB2  racnode2-0  ORCLPDB
 8  ORCLCDB1  racnode1-0  ORCLPDB
 9  ORCLCDB1  racnode1-0  ORCLPDB
10  ORCLCDB2  racnode2-0  ORCLPDB
oracledb 26.0.1 thin mode: True
connections per instance: {'ORCLCDB2': 6, 'ORCLCDB1': 4}
```

**What it shows:** the operator's check at 21:16:11 ran while the database was still opening, so it kept `PENDING`; its next check, two minutes later, set `AVAILABLE` and the connect string back to `orclpdbsvc`. Windows reaches both instances. **First cycle result:** everything came back by itself except the database, because of how it was stopped.

### 14.5 Second cycle: stop with `crsctl stop crs` only

**Why:** with the database's target left `ONLINE`, Clusterware should open it after a cold start without a manual step. `crsctl stop crs` still shuts each instance down cleanly, with the database's stop option (`immediate`).

**a. Stop** (check the target first):

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
date
kubectl -n rac exec racnode1-0 -c racnode1-0 -- /u01/app/19c/grid/bin/crsctl stat res ora.orclcdb.db -t | grep -A2 '^ora.orclcdb.db'
for p in racnode2-0 racnode1-0; do
  echo "=== crsctl stop crs on $p"
  kubectl -n rac exec $p -c $p -- /u01/app/19c/grid/bin/crsctl stop crs 2>&1 | grep -E 'ora.orclcdb.db|CRS-279[13]|CRS-4133|CRS-4687|CRS-4000|error|fail'
  kubectl -n rac exec $p -c $p -- /u01/app/19c/grid/bin/crsctl check crs
done
date
```

**Check:** `ONLINE ONLINE` before the stop; on each pod `CRS-2673 … stop 'ora.orclcdb.db'` and `CRS-2677 … succeeded`, then `CRS-4133`.

**This lab's output** (`grep -A2` shows only instance 1's row, because its details wrap onto a second line):

```text
Thu Oct 29 09:20:00 PM EDT 2026
ora.orclcdb.db
      1        ONLINE  ONLINE       racnode1-0               Open,HOME=/u01/app/o
                                                             racle/product/19c/db
=== crsctl stop crs on racnode2-0
CRS-2791: Starting shutdown of Oracle High Availability Services-managed resources on 'racnode2-0'
CRS-2673: Attempting to stop 'ora.orclcdb.db' on 'racnode2-0'
CRS-2677: Stop of 'ora.orclcdb.db' on 'racnode2-0' succeeded
CRS-2793: Shutdown of Oracle High Availability Services-managed resources on 'racnode2-0' has completed
CRS-4133: Oracle High Availability Services has been stopped.
CRS-4639: Could not contact Oracle High Availability Services
=== crsctl stop crs on racnode1-0
CRS-2791: Starting shutdown of Oracle High Availability Services-managed resources on 'racnode1-0'
CRS-2673: Attempting to stop 'ora.orclcdb.db' on 'racnode1-0'
CRS-2677: Stop of 'ora.orclcdb.db' on 'racnode1-0' succeeded
CRS-2793: Shutdown of Oracle High Availability Services-managed resources on 'racnode1-0' has completed
CRS-4133: Oracle High Availability Services has been stopped.
CRS-4639: Could not contact Oracle High Availability Services
Thu Oct 29 09:21:04 PM EDT 2026
```

**b. Shut the VMs down:** the same block as 14.2 b.

**This lab's output:**

```text
Thursday, October 29, 2026 9:22:51 PM

op-worker2
op-worker1
op-worker2 off after 36 s
op-worker1 off after 5 s
op-controlplane
op-controlplane off after 36 s
--- running VMs now:

Thursday, October 29, 2026 9:24:10 PM
```

**c. Start the VMs:** the same block as 14.3 a.

**This lab's output** (`3 nodes Ready after 11 s` is the stale status described in 14.3, not the workers' real state):

```text
Thursday, October 29, 2026 9:24:30 PM

Waiting for VM "op-controlplane" to power on...
VM "op-controlplane" has been successfully started.
API ready after 59 s
Waiting for VM "op-worker1" to power on...
VM "op-worker1" has been successfully started.
Waiting for VM "op-worker2" to power on...
VM "op-worker2" has been successfully started.
3 nodes Ready after 11 s

Thursday, October 29, 2026 9:26:10 PM
```

**d. Watch, without starting anything:**

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
date
for i in $(seq 1 50); do
  pods=$(kubectl -n rac get pods racnode1-0 racnode2-0 --no-headers -o custom-columns='N:.metadata.name,R:.status.containerStatuses[0].ready,C:.status.containerStatuses[0].restartCount' 2>&1 | tr -s ' ' | tr '\n' ' ')
  db=$(kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - oracle -c "srvctl status database -d ORCLCDB" 2>&1 | tr '\n' ' ' | cut -c1-140)
  echo "$(date +%T)  [$pods] racdb=$(kubectl -n rac get racdatabase racdb -o jsonpath='{.status.state}' 2>/dev/null)  $db"
  echo "$db" | grep -q 'ORCLCDB1 is running' && echo "$db" | grep -q 'ORCLCDB2 is running' && break
  sleep 30
done
kubectl -n rac exec -i racnode1-0 -c racnode1-0 -- su - oracle -c "export ORACLE_SID=ORCLCDB1; sqlplus -s / as sysdba" <<'EOF'
set lines 200 pages 50
col name for a10
select inst_id, name, open_mode from gv$pdbs where name = 'ORCLPDB' order by 1;
EOF
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - oracle -c "srvctl status service -d ORCLCDB"
sleep 150; kubectl -n rac get pods -o wide; kubectl -n rac get racdatabase racdb
```

**Check:** the loop ends with both instances `is running`; `ORCLPDB` `READ WRITE` on 1 and 2; the service on both; `racdb` `AVAILABLE`.

**This lab's output:**

```text
Thu Oct 29 09:27:16 PM EDT 2026
21:27:18  [racnode1-0 false 1 racnode2-0 false 1 ] racdb=PENDING  error: unable to upgrade connection: container not found ("racnode1-0")
21:27:50  [racnode1-0 false 2 racnode2-0 false 2 ] racdb=PENDING  -bash: line 1: srvctl: command not found command terminated with exit code 127
21:28:23  [racnode1-0 false 2 racnode2-0 false 2 ] racdb=PENDING  ****Unable to retrieve Oracle Clusterware home. Start Oracle Clusterware stack and try again. command terminated with exit code 1
21:28:57  [racnode1-0 false 2 racnode2-0 false 2 ] racdb=PENDING  PRKH-1010 : Unable to communicate with CRS services. PRKH-3003 : An attempt to communicate with the CSS daemon failed command terminated wit
21:29:28  [racnode1-0 false 2 racnode2-0 false 2 ] racdb=PENDING  PRKH-1010 : Unable to communicate with CRS services. PRKH-3003 : An attempt to communicate with the CSS daemon failed command terminated wit
21:30:00  [racnode1-0 false 2 racnode2-0 false 2 ] racdb=PENDING  PRCD-1027 : Failed to retrieve database ORCLCDB PRCR-1070 : Failed to check if resource ora.orclcdb.db is registered CRS-0184 : Cannot commu
21:30:31  [racnode1-0 false 2 racnode2-0 false 2 ] racdb=PENDING  PRCD-1027 : Failed to retrieve database ORCLCDB PRCR-1070 : Failed to check if resource ora.orclcdb.db is registered CRS-0184 : Cannot commu
21:31:02  [racnode1-0 false 2 racnode2-0 true 2 ] racdb=PENDING  Instance ORCLCDB1 is not running on node racnode1-0 Instance ORCLCDB2 is not running on node racnode2-0
21:31:34  [racnode1-0 false 2 racnode2-0 true 2 ] racdb=PENDING  Instance ORCLCDB1 is not running on node racnode1-0 Instance ORCLCDB2 is not running on node racnode2-0
21:32:05  [racnode1-0 false 2 racnode2-0 true 2 ] racdb=PENDING  Instance ORCLCDB1 is not running on node racnode1-0 Instance ORCLCDB2 is not running on node racnode2-0
21:32:36  [racnode1-0 false 2 racnode2-0 true 2 ] racdb=PENDING  Instance ORCLCDB1 is not running on node racnode1-0 Instance ORCLCDB2 is not running on node racnode2-0
21:33:07  [racnode1-0 false 2 racnode2-0 true 2 ] racdb=PENDING  Instance ORCLCDB1 is not running on node racnode1-0 Instance ORCLCDB2 is not running on node racnode2-0
21:33:40  [racnode1-0 true 2 racnode2-0 true 2 ] racdb=PENDING  Instance ORCLCDB1 is not running on node racnode1-0 Instance ORCLCDB2 is running on node racnode2-0
21:34:11  [racnode1-0 true 2 racnode2-0 true 2 ] racdb=PENDING  Instance ORCLCDB1 is not running on node racnode1-0 Instance ORCLCDB2 is running on node racnode2-0
21:34:42  [racnode1-0 true 2 racnode2-0 true 2 ] racdb=PENDING  Instance ORCLCDB1 is not running on node racnode1-0 Instance ORCLCDB2 is running on node racnode2-0
21:35:13  [racnode1-0 true 2 racnode2-0 true 2 ] racdb=PENDING  Instance ORCLCDB1 is not running on node racnode1-0 Instance ORCLCDB2 is running on node racnode2-0
21:35:44  [racnode1-0 true 2 racnode2-0 true 2 ] racdb=PENDING  Instance ORCLCDB1 is running on node racnode1-0 Instance ORCLCDB2 is running on node racnode2-0

   INST_ID NAME       OPEN_MODE
---------- ---------- ----------
         1 ORCLPDB    READ WRITE
         2 ORCLPDB    READ WRITE

Service orclpdbsvc is running on instance(s) ORCLCDB1,ORCLCDB2
```

The final lines (after `sleep 150`) were read again separately:

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
kubectl -n rac get pods -o wide; kubectl -n rac get racdatabase racdb
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - grid -c "srvctl config nodeapps | grep 'VIP IPv4'; srvctl config scan | grep 'IPv4 VIP'"
kubectl -n rac get sts racnode1 racnode2 -o custom-columns='NAME:.metadata.name,CURRENT:.status.currentRevision,UPDATE:.status.updateRevision'
```

```text
NAME         READY   STATUS    RESTARTS   AGE   IP           NODE         NOMINATED NODE   READINESS GATES
racnode1-0   1/1     Running   2          69m   10.244.1.5   op-worker1   <none>           <none>
racnode2-0   1/1     Running   2          69m   10.244.2.2   op-worker2   <none>           <none>
NAME    DBNAME    DBSTATE   ROLE      VERSION       PDB CONNECT STR                STATE
racdb   ORCLCDB   OPEN      PRIMARY   19.32.0.0.0   racnode-scan:1521/orclpdbsvc   AVAILABLE
VIP IPv4 Address: 10.244.1.5
VIP IPv4 Address: 10.244.2.2
SCAN 1 IPv4 VIP: 10.244.1.5
SCAN 2 IPv4 VIP: 10.244.2.2
NAME       CURRENT               UPDATE
racnode1   racnode1-75fbb798ff   racnode1-75fbb798ff
racnode2   racnode2-c48dbfc47    racnode2-c48dbfc47
```

**e. Windows, three runs** (the first while only ORCLCDB2 was open, the second and third after both were):

```powershell
# Windows PowerShell  (connect: local, on your PC)
python D:\rac-k8s-poc-operator\scan_test.py
```

```text
connections per instance: {'ORCLCDB2': 10}
connections per instance: {'ORCLCDB1': 10}
 1  ORCLCDB1  racnode1-0  ORCLPDB
 2  ORCLCDB1  racnode1-0  ORCLPDB
 3  ORCLCDB1  racnode1-0  ORCLPDB
 4  ORCLCDB1  racnode1-0  ORCLPDB
 5  ORCLCDB1  racnode1-0  ORCLPDB
 6  ORCLCDB1  racnode1-0  ORCLPDB
 7  ORCLCDB2  racnode2-0  ORCLPDB
 8  ORCLCDB1  racnode1-0  ORCLPDB
 9  ORCLCDB2  racnode2-0  ORCLPDB
10  ORCLCDB1  racnode1-0  ORCLPDB
oracledb 26.0.1 thin mode: True
connections per instance: {'ORCLCDB1': 8, 'ORCLCDB2': 2}
```

**What 14.5 shows:** the database came back **without any manual step**: ORCLCDB2 at 21:33:40 and ORCLCDB1 at 21:35:44, about 11 minutes after the VMs were started and 16 minutes after the stop began. Each instance starts once its own node's Clusterware, ASM and disk groups are up; racnode1-0 was about 2½ minutes behind racnode2-0. The first Windows run reached the only open instance through SCAN; the next ones followed the `LONG` balancing (the instance with fewer sessions first). racnode1-0's pod IP changed again (10.244.1.5); the VIP and SCAN VIP followed.

### 14.6 Runbook: stopping and starting the lab

Use this whenever the PC is shut down or restarted. Each block was run as shown in 14.5, except the worker wait in step 3, which replaces the node count that gave a stale result (14.3).

**Stop (about 3 minutes):**

1. Stop Clusterware on both pods; the database stops with it and its target stays `ONLINE` (14.5 a):

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
for p in racnode2-0 racnode1-0; do
  echo "=== crsctl stop crs on $p"
  kubectl -n rac exec $p -c $p -- /u01/app/19c/grid/bin/crsctl stop crs 2>&1 | grep -E 'ora.orclcdb.db|CRS-279[13]|CRS-4133|CRS-4687|CRS-4000|error|fail'
  kubectl -n rac exec $p -c $p -- /u01/app/19c/grid/bin/crsctl check crs
done
```

**Check:** `CRS-4133` on both pods. If not, don't shut down; find out why first.

2. Shut the VMs down from inside, workers first (14.2 b):

```powershell
# Windows PowerShell  (connect: local, on your PC)
$VB = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
function Wait-Off($name) { $t0 = Get-Date; for ($i = 0; $i -lt 60; $i++) { Start-Sleep 5; if (-not ((& $VB list runningvms) -match "`"$name")) { return "$name off after $([int]((Get-Date) - $t0).TotalSeconds) s" } }; return "$name STILL RUNNING after 300 s - stop here, don't force" }
foreach ($p in 2222, 2221) { ssh -o ConnectTimeout=5 -p $p root@127.0.0.1 'hostname -s; systemctl poweroff' }
Wait-Off "op-worker2"; Wait-Off "op-worker1"
ssh -o ConnectTimeout=5 -p 2220 root@127.0.0.1 'hostname -s; systemctl poweroff'
Wait-Off "op-controlplane"
"--- running VMs now:"; & $VB list runningvms
```

**Check:** three `off` lines and no running VMs. Only then shut down or restart Windows.

**Start (about 12 minutes until both instances are open):**

3. op-controlplane, then the workers once the API answers; then wait until kubelet runs on both workers:

```powershell
# Windows PowerShell  (connect: local, on your PC)
$VB = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
& $VB list runningvms
& $VB startvm op-controlplane --type headless
$t0 = Get-Date; $ok = $false
for ($i = 0; $i -lt 60; $i++) { Start-Sleep 5; $r = ssh -o ConnectTimeout=3 -o BatchMode=yes -p 2220 root@127.0.0.1 'kubectl get --raw=/readyz 2>/dev/null' 2>$null; if ($r -eq 'ok') { $ok = $true; break } }
if ($ok) { "API ready after $([int]((Get-Date) - $t0).TotalSeconds) s" } else { "API NOT ready after 300 s - stop here" }
if ($ok) {
  foreach ($n in "op-worker1","op-worker2") { & $VB startvm $n --type headless }
  foreach ($p in 2221, 2222) { $t0 = Get-Date; for ($i = 0; $i -lt 60; $i++) { Start-Sleep 5; $r = ssh -o ConnectTimeout=3 -o BatchMode=yes -p $p root@127.0.0.1 'systemctl is-active kubelet' 2>$null; if ($r -eq 'active') { break } }; "port ${p}: kubelet $r after $([int]((Get-Date) - $t0).TotalSeconds) s" }
}
```

**Check:** the first line lists no running VM from the manual lab (one lab at a time); `API ready`; `kubelet active` on both workers.

4. Watch the database open by itself: the 14.5 d block. **Check:** both instances `is running` (about 9–11 minutes after the workers start), `ORCLPDB` `READ WRITE` on 1 and 2, the service on both, `racdb` `AVAILABLE` (allow 2 minutes for the operator).
5. Windows: `python D:\rac-k8s-poc-operator\scan_test.py`. A 10/0 split is normal right after a start (`LONG` balancing); the test failing is not.

**If the database stays down** with the pods `Ready` and `srvctl status database` showing both instances `not running` for more than 5 minutes: check the target with `crsctl stat res ora.orclcdb.db -t` (14.4 a). `OFFLINE` means it was stopped with `srvctl`; start it with `srvctl start database -d ORCLCDB` as `oracle` on racnode1-0. Don't delete pods or change the ConfigMaps (Phase 13).

**Not covered:** a hard power-off (VirtualBox "Power Off", a Windows crash or power loss) with the database open. Clusterware should recover the instances, but that hasn't been tested here.

**What was changed in Phase 14:** nothing in the cluster's configuration. A manual OCR backup (`backup_20261030_005450.ocr`) was added; the database's target is `ONLINE` again (as before the phase).
