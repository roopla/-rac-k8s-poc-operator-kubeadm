## Phase 13: Restarting the RAC pods safely

**Result of this phase:** the RAC pods survive a restart on their own: Grid's local files are restored, Clusterware and the database start, Clusterware moves the VIPs and SCAN to the pods' new IPs, `ORCLPDB` opens on both instances, the Phase 12 access from Windows keeps working, and a guard (`SKIP_DBCA=true`) makes sure Oracle's setup script can't try to create the database again. The phase also records how the operator behaves when its configuration changes, which caused two unplanned restarts here.

**Why a restart needs care in this lab:**

- **Grid's local files live in the container, not on a volume.** `/etc/oracle` (`ocr.loc`, `olr.loc`), `/etc/oratab`, `/etc/oraInst.loc` and the `oracle-ohasd` unit are on the container's writable layer (`overlay`). A new container, after any pod restart or VM reboot, starts without them. Only `/u01` (the homes, on `/scratch/rac/cluster01/racnodeN`), the stage folder, the Secrets, the env ConfigMap and the ASM disks persist.
- **Every container start runs Oracle's setup script again** (`/usr/sbin/init` → systemd → `runOracle.sh` → `main.py`), with `OP_TYPE=setuprac` on both pods, rebuilt by the operator from the spec on every reconcile.
- **The script restores Grid by itself** (`check_gi_installed` → `restore_gi_files` → `rootcrs.sh -updateosfiles`, then `start_crs`) **but then checks for the database with `check_dbinst`, which only counts an instance that is `OPEN` at that moment.** Otherwise it goes on to `create_db()`, DBCA. After a restart the instances are often still starting, so without a guard the script could try to create the database again.
- **The guard, `SKIP_DBCA=true`,** makes `oraracprov` skip its whole database block (disk-group checks, instance check, DBCA). The scripts read it from the env ConfigMap (`/etc/rac_env_vars/envfile`).
- **The operator rolls both RAC pods at once whenever the env ConfigMap changes.** It stores a hash of that ConfigMap in the pod template; a changed ConfigMap means a changed template, and the operator updates both StatefulSets together. In this lab that happened one to three minutes after each change, with the database `AVAILABLE`; the pods were stopped within Kubernetes' 30 s grace period, with the database open: a hard restart of both nodes.

**What happened, in order** (times US Eastern, 29 October 2026):

| Time | Step | What happened |
| --- | --- | --- |
| 19:42–19:56 | 13.1 | read-only checks: what persists, what the scripts and the operator do on a restart |
| 19:57–20:00 | 13.2 | backups (`RacDatabase`, OCR, pfile), then a clean stop: database, then Clusterware on both pods |
| 20:02–20:10 | 13.3 | `SKIP_DBCA` added to the `RacDatabase` `envVars`; the operator did nothing visible while the pods were not ready; Clusterware started again, database kept closed |
| 20:14 | 13.3 | database started by hand; outage of the planned stop: about 16 minutes |
| 20:15–20:17 | 13.4 | **the first patch of the ConfigMaps was faulty** (`CPU_COUNT=3SKIP_DBCA=true`); the changed ConfigMap made the operator roll both pods at 20:16:28, with the database open |
| 20:18–20:21 | 13.4 | setup script stopped on racnode1-0 before its DBCA check (no guard in effect); Clusterware had moved the VIPs and SCAN to the new pod IPs; both instances open, `ORCLPDB` only mounted on instance 1 |
| 20:22 | 13.5 | `ORCLPDB` opened and its state saved for both instances |
| 20:27–20:36 | 13.6 | ConfigMaps repaired from the backup with `SKIP_DBCA=true` on its own line; the operator rolled both pods again at about 20:28:30; everything came back by itself, guard in effect, no DBCA |

### 13.1 What starts on its own, and what keeps state (read-only)

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
kubectl get nodes; kubectl -n rac get racdatabase racdb; kubectl -n rac get pods -o wide
echo "--- StatefulSets: start order, grace period"
kubectl -n rac get sts racnode1 racnode2 -o custom-columns='NAME:.metadata.name,POLICY:.spec.podManagementPolicy,UPDATE:.spec.updateStrategy.type,GRACE:.spec.template.spec.terminationGracePeriodSeconds'
echo "--- what the container runs"
kubectl -n rac get pod racnode1-0 -o jsonpath='command: {.spec.containers[0].command}{"\n"}args:    {.spec.containers[0].args}{"\n"}'
for p in racnode1-0 racnode2-0; do
  echo "=== $p"
  kubectl -n rac exec $p -c $p -- bash -c 'echo "statefile: $(cat /tmp/orod/.statefile 2>/dev/null)"; findmnt -T /tmp/orod -no TARGET,SOURCE,FSTYPE; findmnt -T /u01 -no TARGET,SOURCE,FSTYPE; systemctl is-enabled oracle-ohasd 2>&1; /u01/app/19c/grid/bin/crsctl config crs'
done
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - oracle -c "srvctl config database -d ORCLCDB | grep -E 'Management policy|Start options|Stop options|Database instances'; srvctl config service -d ORCLCDB -s orclpdbsvc | grep -E 'Management policy'"
kubectl -n oracle-database-operator-system get deploy,pods
```

```powershell
# PowerShell on the Windows PC
$VB = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
"--- VM states"; foreach ($v in "op-controlplane","op-worker1","op-worker2") { "$v  $((& $VB showvminfo $v --machinereadable | Select-String '^VMState=') -replace 'VMState=','')" }
foreach ($p in 2220, 2221, 2222) { "--- port $p"; ssh -p $p root@127.0.0.1 "hostname; systemctl is-enabled kubelet crio; grep HugePages_Total /proc/meminfo; cat /etc/sysctl.d/92-hugepages.conf 2>/dev/null; ip -br link show | grep -E 'enp0s[89]' | grep -o 'enp0s[89].*PROMISC' || true" }
```

**This lab's output (cluster):**

```text
NAME              STATUS   ROLES           AGE     VERSION
op-controlplane   Ready    control-plane   2d20h   v1.36.5
op-worker1        Ready    worker          2d20h   v1.36.5
op-worker2        Ready    worker          2d20h   v1.36.5
NAME    DBNAME    DBSTATE   ROLE      VERSION       PDB CONNECT STR                STATE
racdb   ORCLCDB   OPEN      PRIMARY   19.32.0.0.0   racnode-scan:1521/orclpdbsvc   AVAILABLE
NAME         READY   STATUS    RESTARTS   AGE   IP           NODE         NOMINATED NODE   READINESS GATES
racnode1-0   1/1     Running   0          47h   10.244.1.6   op-worker1   <none>           <none>
racnode2-0   1/1     Running   0          47h   10.244.2.4   op-worker2   <none>           <none>
--- StatefulSets: start order, grace period
NAME       POLICY         UPDATE          GRACE
racnode1   OrderedReady   RollingUpdate   30
racnode2   OrderedReady   RollingUpdate   30
--- what the container runs
command: ["/usr/sbin/init"]
args:
=== racnode1-0
statefile: completed
/tmp   tmpfs  tmpfs
/u01   /dev/sdb[/rac/cluster01/racnode1] xfs
enabled
CRS-4622: Oracle High Availability Services autostart is enabled.
=== racnode2-0
statefile: provisioning
/tmp   tmpfs  tmpfs
/u01   /dev/sdb[/rac/cluster01/racnode2] xfs
enabled
CRS-4622: Oracle High Availability Services autostart is enabled.
Start options: open
Stop options: immediate
Management policy: AUTOMATIC
Database instances: ORCLCDB1,ORCLCDB2
Management policy: AUTOMATIC
NAME                                                          READY   UP-TO-DATE   AVAILABLE   AGE
deployment.apps/oracle-database-operator-controller-manager   1/1     1            1           2d11h

NAME                                                               READY   STATUS    RESTARTS   AGE
pod/oracle-database-operator-controller-manager-54cf89dd45-f644n   1/1     Running   1          2d11h
```

**This lab's output (Windows):**

```text
--- VM states
op-controlplane  "running"
op-worker1  "running"
op-worker2  "running"
--- port 2220
op-controlplane
enabled
enabled
HugePages_Total:       0
--- port 2221
op-worker1
enabled
enabled
HugePages_Total:    2048
vm.nr_hugepages = 2048
enp0s8           UP             08:00:27:c3:37:02 <BROADCAST,MULTICAST,PROMISC
enp0s9           UP             08:00:27:43:bd:30 <BROADCAST,MULTICAST,PROMISC
--- port 2222
op-worker2
enabled
enabled
HugePages_Total:    2048
vm.nr_hugepages = 2048
enp0s8           UP             08:00:27:9d:88:72 <BROADCAST,MULTICAST,PROMISC
enp0s9           UP             08:00:27:9e:48:85 <BROADCAST,MULTICAST,PROMISC
```

**What it shows:** the VM layer survives reboots (kubelet and CRI-O enabled, hugepages from `/etc/sysctl.d`, promiscuous NICs). Clusterware and the database start by themselves once Grid runs (`ohasd` enabled, CRS autostart, `AUTOMATIC` policy). Kubernetes gives a pod **30 s** to stop, too short for RAC, so the database and Clusterware must be stopped by hand before a planned restart. `/tmp` is a tmpfs, so the setup script's state file is lost on a restart; `OrderedReady` doesn't matter, because each StatefulSet has one pod.

**What persists, and where Grid's local files are** (read-only):

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
kubectl -n rac get pod racnode1-0 -o jsonpath='{range .spec.containers[0].volumeMounts[*]}{.mountPath}{"  <-  "}{.name}{"\n"}{end}'
kubectl -n rac get pod racnode1-0 -o jsonpath='{range .spec.volumes[*]}{.name}{"  "}{.hostPath.path}{.emptyDir}{.persistentVolumeClaim.claimName}{.secret.secretName}{"\n"}{end}'
for p in racnode1-0 racnode2-0; do
  echo "=== $p: where Grid's local files live"
  kubectl -n rac exec $p -c $p -- bash -c 'for f in /etc/oracle /etc/oratab /etc/oraInst.loc /etc/systemd/system/oracle-ohasd.service /etc/init.d/init.ohasd; do printf "%-45s " $f; if [ -e $f ]; then findmnt -T $f -no TARGET,SOURCE | head -1; else echo MISSING; fi; done; ls /etc/oracle'
done
```

**This lab's output (racnode2-0 the same):**

```text
/mnt/.ssh  <-  racnode1-ssh-secretmap-vol
/mnt/.dbsecrets  <-  racnode1-dbsecret-pwd-vol
/dev/shm  <-  racnode1-oradshm-vol
/etc/rac_env_vars  <-  racnode1-oradata-envfile
/etc/rac_env_vars_writable  <-  racnode1-oradata-envfile-writable
/u01  <-  racnode1-oradata-sw-vol
/mnt/stage/software  <-  racnode1-oradata-swstage-vol
/var/run/secrets/kubernetes.io/serviceaccount  <-  kube-api-access-cbkq5
racnode1-ssh-secretmap-vol  ssh-key-secret
racnode1-oradshm-vol  {"medium":"Memory"}
racnode1-dbsecret-pwd-vol  db-user-pass
racnode1-oradata-envfile
racnode1-oradata-sw-vol  /scratch/rac/cluster01/racnode1
racnode1-oradata-swstage-vol  /scratch/software/stage
asm-pvc-833f4ea4-racdb  asm-pvc-833f4ea4-racdb
asm-pvc-eaac2e15-racdb  asm-pvc-eaac2e15-racdb
asm-pvc-c51c7cc4-racdb  asm-pvc-c51c7cc4-racdb
racnode1-oradata-envfile-writable  {}
kube-api-access-cbkq5
=== racnode1-0: where Grid's local files live
/etc/oracle                                   /      overlay
/etc/oratab                                   /      overlay
/etc/oraInst.loc                              /      overlay
/etc/systemd/system/oracle-ohasd.service      /      overlay
/etc/init.d/init.ohasd                        /      overlay
lastgasp
maps
ocr.loc
ocr.loc.orig
olr.loc
olr.loc.orig
oprocd
scls_scr
setasmgid
```

**What Oracle's setup script does on a restart.** These read-only blocks print the relevant parts of the scripts in the image (`/opt/scripts/startup/scripts`). The excerpts below are cut to the lines that matter (… marks cut text).

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
kubectl -n rac exec racnode1-0 -c racnode1-0 -- bash -c 'cd /opt/scripts/startup/scripts
sed -n "1925,2070p" oracommon.py
grep -n -A30 "def check_dbinst" oracommon.py | head -45
grep -n -A25 "def get_inst_sid" oracommon.py | head -35
sed -n "80,125p" oraracprov.py
grep -n "GI_HOME_CONFIGURED_FLAG" *.py | head'
```

**This lab's output (excerpts):**

```text
    def check_gi_installed(self, retcode1, gihome, giuser, node, oinv):
        if retcode1 == 0:
            if os.path.isdir("/etc/oracle"):
                bstr = "Grid is already installed on this machine and /etc/oracle also exist. Skipping Grid setup.."
                …
                return True
            else:
                …
                    status = self.check_home_inv(None, gihome, giuser)
                    if status:
                        status = self.restore_gi_files(gihome, giuser)
                        …
                            self.run_orainstsh_local(giuser, node, oinv)
                            if self.check_key("CRS_GPC", self.ora_env_dict):
                                return True
                            else:
                                status = self.start_crs(gihome, giuser)
…
    def restore_gi_files(self, gihome, giuser):
        …
        srcdir = "{0}/.etcoraclebackup".format(gibase)
        …
        # 1. Restore /etc/oracle if backup exists
        …
            self.log_info_message("No /etc/oracle backup found; skipping restore", self.file_name)
        # 2. Update OS files (always)
        …
            cmd = "{0}/crs/install/rootcrs.sh -updateosfiles".format(gihome)
…
    def check_dbinst(self):
        …
        inst_sid = self.get_inst_sid(osuser, dbhome, osid, hostname)
        …
        if inst_sid:
            status = self.get_dbinst_status(osuser, dbhome, inst_sid, connect_str)
            if not self.check_substr_match(status, "OPEN"):
                return False, inst_sid, hostname, status
…
    def get_inst_sid(self, dbuser, dbhome, osid, hostname):
        …
        cmd = '''su - {5} -c "… {0}/bin/srvctl status database -d {3} | grep {4}"'''…
…
       if not self.ocommon.check_key("SKIP_DBCA",self.ora_env_dict):
            self.create_asmdg()
            status,osid,host,mode=self.ocommon.check_dbinst()
            …
            if status:
               msg='''Database instance {0} already exists on this machine {1}.'''.format(osid,hostname)
               self.ocommon.update_statefile("completed")
            …
            else:
               …
               self.create_db()
…
orasetupenv.py:945:                 self.ora_env_dict=self.ocommon.add_key("GI_HOME_CONFIGURED_FLAG","true",self.ora_env_dict)
```

(The 19c rule that skips the `/etc/oracle` backup is in `oragiprov.py`: *"Oracle 19c detected and CRS_GPC not set; skipping /etc/oracle backup"*. So on this lab the restore is always `rootcrs.sh -updateosfiles`.)

**Where `OP_TYPE` comes from, and what the operator does with changes** (read-only):

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
for p in racnode1-0 racnode2-0; do echo "=== $p"; kubectl -n rac exec $p -c $p -- grep -E '^(export )?(OP_TYPE|SKIP_DBCA|CRS_GPC|INSTALL_NODE|CRS_NODES|DB_NAME)=' /etc/rac_env_vars/envfile; done
for p in racnode1-0 racnode2-0; do kubectl -n rac get pod $p -o jsonpath='{range .spec.volumes[?(@.configMap)]}{.name}{"  ->  configMap "}{.configMap.name}{"\n"}{end}'; done
cd /root/oraop/controllers/database
sed -n "4095,4135p" racdatabase_controller.go
n=$(grep -n "func (r \*RacDatabaseReconciler) createOrReplaceSfs(" racdatabase_controller.go | cut -d: -f1); sed -n "${n},$((n+25))p" racdatabase_controller.go
```

**This lab's output (excerpts):**

```text
=== racnode1-0
CRS_NODES=pubhost:racnode1-0,viphost:racnode1-0-vip;pubhost:racnode2-0,viphost:racnode2-0-vip
OP_TYPE=setuprac
INSTALL_NODE=racnode1-0
DB_NAME=ORCLCDB
=== racnode2-0
(the same)
racnode1-oradata-envfile  ->  configMap racnode1racdb-cmap
racnode2-oradata-envfile  ->  configMap racnode2racdb-cmap
…
        if cfg.OpType == "" {
                env.AddKV("OP_TYPE", "setuprac")
        }
…
func appendRACSpecEnvVars(instance *racdb.RacDatabase, env *racEnvAccumulator) {
        for _, e := range instance.Spec.EnvVars {
                env.AddKV(e.Name, e.Value)
        }
}
…
func (r *RacDatabaseReconciler) createOrReplaceSfs(
        …
        configMapHash, err := r.computeRACConfigMapHash(ctx, racDatabase.Namespace, &dep.Spec.Template)
        …
        dep.Spec.Template.Annotations[racConfigMapHashAnnotation] = configMapHash
        result, err := sharedk8sobjects.ReconcileStatefulSet(ctx, r.Client, racDatabase.Namespace, dep, …
```

**What that means:** `OP_TYPE` is `setuprac` on both pods and comes back on every reconcile unless `configParams.opType` is set. `SKIP_DBCA` appears nowhere in the operator; only Oracle's scripts read it. The operator puts a hash of each env ConfigMap into its pod template, so **a changed ConfigMap rolls the pods**.

### 13.2 Save the current state, then stop the database and Clusterware

**a. Backups** (no outage): the `RacDatabase` as the cluster has it, a copy of the YAML, a manual OCR backup, and a pfile on `/u01`.

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
kubectl -n rac get racdatabase racdb -o yaml > /root/rac-op/racdb-before-13.yaml
cp -p /root/rac-op/racdb.yaml /root/rac-op/racdb.yaml.before-13
ls -l /root/rac-op/racdb-before-13.yaml /root/rac-op/racdb.yaml.before-13
kubectl -n rac exec racnode1-0 -c racnode1-0 -- bash -c '/u01/app/19c/grid/bin/ocrconfig -manualbackup; /u01/app/19c/grid/bin/ocrconfig -showbackup manual'
kubectl -n rac exec -i racnode1-0 -c racnode1-0 -- su - oracle -c "export ORACLE_SID=ORCLCDB1; sqlplus -s / as sysdba" <<'EOF'
create pfile='/u01/app/oracle/pfile-ORCLCDB-before-13.ora' from spfile;
EOF
kubectl -n rac exec racnode1-0 -c racnode1-0 -- bash -c 'ls -l /u01/app/oracle/pfile-ORCLCDB-before-13.ora; grep -E "local_listener|control_files|db_recovery" /u01/app/oracle/pfile-ORCLCDB-before-13.ora'
```

**This lab's output:**

```text
-rw-r--r--. 1 root root 10285 Oct 29 19:57 /root/rac-op/racdb-before-13.yaml
-rw-r--r--. 1 root root  2257 Oct 27 20:22 /root/rac-op/racdb.yaml.before-13

racnode1-0     2026/10/29 23:57:58     +VOTEDG:/racnode-c/OCRBACKUP/backup_20261029_235758.ocr.263.1247961479     1753837251

racnode1-0     2026/10/29 23:57:58     +VOTEDG:/racnode-c/OCRBACKUP/backup_20261029_235758.ocr.263.1247961479     1753837251

File created.

-rw-r--r--. 1 oracle asmadmin 2497 Oct 29 23:58 /u01/app/oracle/pfile-ORCLCDB-before-13.ora
*.control_files='+DATA/ORCLCDB/CONTROLFILE/current.278.1247831575','+FRA/ORCLCDB/CONTROLFILE/current.267.1247831577'#Restore Controlfile
*.db_recovery_file_dest='+FRA'
*.db_recovery_file_dest_size=23895m
*.local_listener='-oraagent-dummy-'
ORCLCDB1.local_listener='(ADDRESS=(PROTOCOL=TCP)(HOST=racnode1-0-vip.rac.svc.cluster.local)(PORT=31522))'
ORCLCDB2.local_listener='(ADDRESS=(PROTOCOL=TCP)(HOST=racnode2-0-vip.rac.svc.cluster.local)(PORT=31523))'
```

**b. Clean stop:** the database first (stop option `immediate`), then Clusterware on racnode2-0, then racnode1-0.

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - oracle -c "srvctl stop database -d ORCLCDB; srvctl status database -d ORCLCDB"
for p in racnode2-0 racnode1-0; do
  echo "=== crsctl stop crs on $p"
  kubectl -n rac exec $p -c $p -- /u01/app/19c/grid/bin/crsctl stop crs
  kubectl -n rac exec $p -c $p -- /u01/app/19c/grid/bin/crsctl check crs
done
sleep 20
kubectl -n rac get pods -o wide; kubectl -n rac get racdatabase racdb
```

**This lab's output (the `crsctl stop crs` lines cut):**

```text
Instance ORCLCDB1 is not running on node racnode1-0
Instance ORCLCDB2 is not running on node racnode2-0
=== crsctl stop crs on racnode2-0
CRS-2791: Starting shutdown of Oracle High Availability Services-managed resources on 'racnode2-0'
CRS-2673: Attempting to stop 'ora.crsd' on 'racnode2-0'
…
CRS-2793: Shutdown of Oracle High Availability Services-managed resources on 'racnode2-0' has completed
CRS-4133: Oracle High Availability Services has been stopped.
CRS-4639: Could not contact Oracle High Availability Services
=== crsctl stop crs on racnode1-0
…
CRS-4133: Oracle High Availability Services has been stopped.
CRS-4639: Could not contact Oracle High Availability Services
NAME                         READY   STATUS        RESTARTS   AGE   IP           NODE         NOMINATED NODE   READINESS GATES
disk-check-daemonset-fstch   1/1     Terminating   0          15s   10.244.1.8   op-worker1   <none>           <none>
disk-check-daemonset-mcvbh   1/1     Terminating   0          15s   10.244.2.6   op-worker2   <none>           <none>
racnode1-0                   0/1     Running       0          47h   10.244.1.6   op-worker1   <none>           <none>
racnode2-0                   0/1     Running       0          47h   10.244.2.4   op-worker2   <none>           <none>
NAME    DBNAME    DBSTATE        ROLE           VERSION        PDB CONNECT STR   STATE
racdb   ORCLCDB   NOTAVAILABLE   NOTAVAILABLE   NOTAVAILABLE   NOTAVAILABLE      PENDING
```

**What it shows:** every resource stopped cleanly; the pods dropped to `0/1` (the readiness probe checks the listener on 1522) but kept running; the operator noticed (a new disk-check run, `PENDING`) without changing anything.

### 13.3 `SKIP_DBCA` in the `RacDatabase` (no effect on this cluster)

**a. Preview.** `kubectl diff` showed that the file on op-controlplane lacked `accessMode: ReadWriteMany` on the three disk groups, which the live object has. Applying that would have been a disk-group change, which sends the operator down its storage path; the file was fixed first so `SKIP_DBCA` was the only change.

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
cd /root/rac-op
grep -n 'SKIP_DBCA' racdb.yaml || sed -i '/name: IGNORE_DB_PREREQS/a\    - { name: SKIP_DBCA, value: "true" }' racdb.yaml
grep -q 'accessMode: ReadWriteMany' racdb.yaml || sed -i -E '/type: (CRSDG|DBDATAFILESDG|DBRECOVERY)/s/redundancy: EXTERNAL,/redundancy: EXTERNAL, accessMode: ReadWriteMany,/' racdb.yaml
kubectl diff -f racdb.yaml; echo "(kubectl diff exit $?)"
kubectl apply --dry-run=server -f racdb.yaml
```

**This lab's output (first diff, before the `accessMode` fix; excerpt):**

```text
-  generation: 1
+  generation: 2
…
   asmDiskGroupDetails:
-  - accessMode: ReadWriteMany
-    disks:
+  - disks:
     - /dev/disk/by-id/ata-VBOX_HARDDISK_VB67cb0647-80696c8f
…
+  - name: SKIP_DBCA
+    value: "true"
```

**This lab's output (after the fix):**

```text
-  generation: 1
+  generation: 2
…
   - name: IGNORE_DB_PREREQS
     value: "true"
+  - name: SKIP_DBCA
+    value: "true"
…
(kubectl diff exit 1)
racdatabase.database.oracle.com/racdb configured (server dry run)
```

(The live object has no `CRS_ASM_DISCOVERY_STRING` either: this build's first apply didn't have it, and 11.4 set the discovery string with `asmcmd dsset`, which is stored in the cluster profile and the ASM spfile.)

**b. Apply.** The operator accepted it (`generation 2 observed 2`) but didn't write the ConfigMaps or roll the pods. While the pods weren't ready, each reconcile stopped at *"unable to validate RAC pod. The pod not ready is: racnode1-0"* and retried every 30 s.

```text
racdatabase.database.oracle.com/racdb configured
--- racnode1racdb-cmap
OP_TYPE=setuprac
--- racnode2racdb-cmap
OP_TYPE=setuprac
…
generation 2  observed 2
state PENDING
ReconcileComplete=True  LastReconcileCycleCompleted: no reconcile errors
ReconcileWaiting=True  LastReconcileCycleWaiting: RAC pods pending: [racnode1-0]
…  RAC topology update encountered a non-fatal issue       {"racDatabase": "racdb", "error": "unable to validate RAC pod. The  pod not ready  is: racnode1-0"}
```

**c. Clusterware started again, database kept closed.** Both pods turned ready about a minute later (20:08:12); for 2½ minutes after that the ConfigMaps still had no `SKIP_DBCA`. Later checks showed why: for this `instanceDetails`-style spec, `envVars` reach neither the ConfigMaps nor the container environment after the first creation. **Changing `envVars` on an existing database has no effect here.** The database was then started by hand:

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
for p in racnode1-0 racnode2-0; do kubectl -n rac exec $p -c $p -- /u01/app/19c/grid/bin/crsctl start crs; done
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - oracle -c "srvctl start database -d ORCLCDB; srvctl status database -d ORCLCDB -v; srvctl status service -d ORCLCDB"
```

```text
CRS-4123: Oracle High Availability Services has been started.
CRS-4123: Oracle High Availability Services has been started.
…
Instance ORCLCDB1 is running on node racnode1-0 with online services orclpdbsvc. Instance status: Open.
Instance ORCLCDB2 is running on node racnode2-0 with online services orclpdbsvc. Instance status: Open.
Service orclpdbsvc is running on instance(s) ORCLCDB1,ORCLCDB2
```

### 13.4 A faulty ConfigMap patch, and the unplanned restart it caused

**What went wrong:** the first patch of the two ConfigMaps (20:15) was meant to add `SKIP_DBCA=true` as its own line. The `envfile` has no newline at its end, and the line that should have added one, `printf '%sSKIP_DBCA=true\n' "$( … && echo)"`, added nothing: command substitution drops the newline it produces. The text was glued onto the last line, **`CPU_COUNT=3SKIP_DBCA=true`**, in both ConfigMaps. Don't use that block; 13.6 has the correct one.

**What it caused:** the changed ConfigMaps changed the operator's hash; at 20:16:28 it updated both StatefulSets and Kubernetes deleted both RAC pods together, with the database open:

```text
2026-10-30T00:16:28Z   SuccessfulDelete        racnode1                     statefulset-controller   Delete Pod racnode1-0 in StatefulSet racnode1 successful
2026-10-30T00:16:29Z   Killing                 racnode1-0                   kubelet                  Stopping container racnode1-0
2026-10-30T00:16:29Z   SuccessfulDelete        racnode2                     statefulset-controller   Delete Pod racnode2-0 in StatefulSet racnode2 successful
2026-10-30T00:16:29Z   Killing                 racnode2-0                   kubelet                  Stopping container racnode2-0
2026-10-30T00:17:01Z   SuccessfulCreate        racnode2                     statefulset-controller   Create Pod racnode2-0 in StatefulSet racnode2 successful
2026-10-30T00:17:01Z   SuccessfulCreate        racnode1                     statefulset-controller   Create Pod racnode1-0 in StatefulSet racnode1 successful
…  INFO    controllers.controllers.RacDatabase     Updating StatefulSet to desired spec    {… "StatefulSet.Name": "racnode1"}
…  INFO    controllers.controllers.RacDatabase     Updating StatefulSet to desired spec    {… "StatefulSet.Name": "racnode2"}
```

**The new pods had no guard** (`SKIP_DBCA` was part of `CPU_COUNT`'s value), so the setup script on racnode1-0 was stopped once its Grid part was done and before it reached the database check:

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
kubectl -n rac exec racnode1-0 -c racnode1-0 -- bash -c '
L=/tmp/orod/oracle_db_setup.log
grep -n -E "restore_gi_files|updateosfiles|Starting Oracle Clusterware|already configured|create_db|dbca -silent" $L | tail -12
if grep -qE "create_db :: start|dbca -silent" $L; then echo "STOP: DBCA has already started; not killing anything"; exit 0; fi
P=$(ps -eo pid,args | awk "\$2 ~ /python/ && /main\\.py/ && !/check/ {print \$1}")
echo "setup process(es): $P"; [ -n "$P" ] && kill $P; sleep 5
echo "--- still running after the kill (should be empty):"; ps -eo pid,etime,args | awk "\$3 ~ /python/ && /main\\.py/ && !/check/"
echo "--- last log lines"; tail -3 $L'
```

```text
3356:10/30/2026 12:17:40 AM     INFO:   oracommon   -   restoregifiles   :restore_gi_files invoked (Oracle major version: 19)
3359:10/30/2026 12:17:40 AM     INFO:   oracommon   -   executeprocess   :Received Command : /u01/app/19c/grid/crs/install/rootcrs.sh -updateosfiles
3421:          Grid is already configured on this machine
setup process(es): 56
--- still running after the kill (should be empty):
--- last log lines
…
10/30/2026 12:19:16 AM     INFO:  oraracprov   -     cluchecks      :CVU checks not ready yet on node racnode1-0. This is expected after pod restart. Retrying in 30 seconds...
```

**What came back by itself anyway:** Clusterware, ASM, the listeners, the VIPs and SCAN, now on the new pod IPs, and the database (`AUTOMATIC`):

```text
=== racnode1-0 eth0: 10.244.1.9/24
=== racnode2-0 eth0: 10.244.2.7/24
…
ora.orclcdb.db
      1        ONLINE  OFFLINE      racnode1-0               STARTING
      2        ONLINE  ONLINE       racnode2-0               Open,HOME=/u01/app/oracle/product/19c/dbhome_1,STABLE
…
VIP IPv4 Address: 10.244.1.9
VIP IPv4 Address: 10.244.2.7
SCAN 1 IPv4 VIP: 10.244.1.9
SCAN 2 IPv4 VIP: 10.244.2.7
  racnode1-0-vip -> 10.244.1.9
  racnode2-0-vip -> 10.244.2.7
  racnode-scan -> 10.244.2.7 10.244.1.9
…
20:21:16  Instance ORCLCDB1 is running on node racnode1-0 Instance ORCLCDB2 is running on node racnode2-0
…
         1 ORCLPDB    MOUNTED
         2 ORCLPDB    READ WRITE
```

### 13.5 Open the PDB on both instances and save that state

`ORCLPDB` opened automatically only where its open state was saved. Saving it for both instances makes it open by itself after every restart:

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
kubectl -n rac exec -i racnode1-0 -c racnode1-0 -- su - oracle -c "export ORACLE_SID=ORCLCDB1; sqlplus -s / as sysdba" <<'EOF'
alter pluggable database ORCLPDB open instances=all;
alter pluggable database ORCLPDB save state instances=all;
set lines 200
col con_name for a10
col instance_name for a12
select inst_id, name, open_mode from gv$pdbs where name = 'ORCLPDB' order by 1;
select con_name, instance_name, state from dba_pdb_saved_states order by 2;
EOF
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - oracle -c "srvctl start service -d ORCLCDB -s orclpdbsvc -i ORCLCDB1 2>&1; srvctl status service -d ORCLCDB"
```

**This lab's output:**

```text
Pluggable database altered.

Pluggable database altered.

   INST_ID NAME       OPEN_MODE
---------- ---------- ----------
         1 ORCLPDB    READ WRITE
         2 ORCLPDB    READ WRITE

CON_NAME   INSTANCE_NAM STATE
---------- ------------ --------------
ORCLPDB    ORCLCDB1     OPEN
ORCLPDB    ORCLCDB2     OPEN

PRCR-1120 : Resources are already running.
CRS-5702: Resource 'ora.orclcdb.orclpdbsvc.svc' is already running on 'racnode1-0'
Service orclpdbsvc is running on instance(s) ORCLCDB1,ORCLCDB2
```

### 13.6 The guard, done right, and a restart that needs no help

**What:** each `envfile` becomes exactly the 20:15 backup plus the line `SKIP_DBCA=true`, with a newline added first if the backup lacks one. The block checks the result (41 keys, the last two lines `CPU_COUNT=3` and `SKIP_DBCA=true`) before patching. **It restarts both RAC pods:** about 2½ minutes later the operator rolls them, as in 13.4. That is the one restart the guard costs; after it the ConfigMaps don't change again.

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
cd /root/rac-op
for c in racnode1racdb-cmap racnode2racdb-cmap; do
  b=$(mktemp); f=$(mktemp)
  kubectl create --dry-run=client -f cm-$c-before-13.4.yaml -o jsonpath='{.data.envfile}' > $b
  { cat $b; [ -n "$(tail -c1 $b)" ] && echo; echo "SKIP_DBCA=true"; } > $f
  echo "--- $c: backup $(grep -c '=' $b) keys -> new $(grep -c '=' $f) keys; last lines:"; tail -2 $f | cat -A
  if [ "$(grep -c '=' $f)" = "41" ] && [ "$(tail -2 $f | head -1)" = "CPU_COUNT=3" ] && [ "$(tail -1 $f)" = "SKIP_DBCA=true" ]; then
    kubectl -n rac patch cm $c --type merge -p "$(python3 -c 'import json,sys; print(json.dumps({"data":{"envfile":open(sys.argv[1]).read()}}))' $f)"
  else echo "STOP: $c not as expected, not patched"; fi
  rm -f $b $f
done
for i in $(seq 1 40); do
  echo "=== $(date +%T)  racdb: $(kubectl -n rac get racdatabase racdb -o jsonpath='{.status.state}')"
  kubectl -n rac get pods --no-headers -o custom-columns='POD:.metadata.name,READY:.status.containerStatuses[0].ready,STARTED:.metadata.creationTimestamp,IP:.status.podIP' | grep racnode
  sleep 20
done
```

(The backups `cm-racnode1racdb-cmap-before-13.4.yaml` and `cm-racnode2racdb-cmap-before-13.4.yaml` were taken at the start of 13.4 with `kubectl -n rac get cm <name> -o yaml`.)

**This lab's output (watch lines cut):**

```text
--- racnode1racdb-cmap: backup 40 keys -> new 41 keys; last lines:
CPU_COUNT=3$
SKIP_DBCA=true$
configmap/racnode1racdb-cmap patched
--- racnode2racdb-cmap: backup 40 keys -> new 41 keys; last lines:
CPU_COUNT=3$
SKIP_DBCA=true$
configmap/racnode2racdb-cmap patched
=== 20:27:10  racdb: AVAILABLE
racnode1-0   true   2026-10-30T00:17:01Z   10.244.1.9
racnode2-0   true   2026-10-30T00:17:01Z   10.244.2.7
…
=== 20:29:11  racdb: AVAILABLE
racnode1-0   false   2026-10-30T00:28:58Z   10.244.1.10
racnode2-0   false   2026-10-30T00:28:58Z   10.244.2.8
…
=== 20:32:13  racdb: AVAILABLE
racnode1-0   false   2026-10-30T00:28:58Z   10.244.1.10
racnode2-0   true    2026-10-30T00:28:58Z   10.244.2.8
…
=== 20:32:53  racdb: AVAILABLE
racnode1-0   true   2026-10-30T00:28:58Z   10.244.1.10
racnode2-0   true   2026-10-30T00:28:58Z   10.244.2.8
```

**Check after the restart** (read-only):

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
for p in racnode1-0 racnode2-0; do echo "=== $p sees: $(kubectl -n rac exec $p -c $p -- grep -E '^(SKIP_DBCA|CPU_COUNT|OP_TYPE)=' /etc/rac_env_vars/envfile | tr '\n' ' ')"; done
kubectl -n rac exec racnode1-0 -c racnode1-0 -- bash -c 'L=/tmp/orod/oracle_db_setup.log; echo "statefile: $(cat /tmp/orod/.statefile)"; grep -n -E "restore_gi_files|updateosfiles|already configured|All required CVU checks|SKIP_DBCA|create_db|dbca -silent|Total time for setup|ERROR|FATAL" $L | tail -15'
for i in $(seq 1 20); do r=$(kubectl -n rac exec racnode1-0 -c racnode1-0 -- bash -c 'ps -eo pid,etime,args | awk "\$3 ~ /python/ && /main\\.py/ && !/check/"'); [ -z "$r" ] && { echo "$(date +%T) setup finished"; break; }; echo "$(date +%T) still running: $r"; sleep 30; done
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - oracle -c "srvctl status database -d ORCLCDB; srvctl status service -d ORCLCDB"
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
```

```powershell
# PowerShell on the Windows PC
python D:\rac-k8s-poc-operator\scan_test.py
```

**Check:** both pods see `SKIP_DBCA=true`; the setup log shows the restore and Clusterware, *"Grid is already configured"*, the CVU checks passing, **no** `create_db` / `dbca -silent`, and a final `Total time for setup()`; both instances running, `ORCLPDB` `READ WRITE` on both, `local_listener` unchanged, the service on both; VIPs and SCAN on the new IPs; `CURRENT` = `UPDATE`; both instances from Windows.

**This lab's output:**

```text
=== racnode1-0 sees: OP_TYPE=setuprac CPU_COUNT=3 SKIP_DBCA=true
=== racnode2-0 sees: OP_TYPE=setuprac CPU_COUNT=3 SKIP_DBCA=true
statefile: provisioning
87:10/30/2026 12:29:01 AM     INFO:   oracommon   - populateracenvvars :SKIP_DBCA key is populated: true
…
199:10/30/2026 12:29:05 AM     INFO:   oracommon   - populateracenvvars :SKIP_DBCA key exists with value true
295:10/30/2026 12:29:05 AM    ERROR:  orasetupenv  -   setupsoftware    :oracle gi home directory is not empty. skipping software unzipping...
334:10/30/2026 12:29:06 AM    ERROR:  orasetupenv  -   setupsoftware    :oracle db home directory is not empty. skipping software unzipping...
3360:10/30/2026 12:29:35 AM     INFO:   oracommon   -   restoregifiles   :restore_gi_files invoked (Oracle major version: 19)
3363:10/30/2026 12:29:35 AM     INFO:   oracommon   -   executeprocess   :Received Command : /u01/app/19c/grid/crs/install/rootcrs.sh -updateosfiles
3413:10/30/2026 12:29:58 AM     INFO:  oramachine   -       setup        :Total time for setup() = [ 56.742 ] seconds
3425:          Grid is already configured on this machine
3434:10/30/2026 12:30:13 AM     INFO:   oragiprov   -       setup        :Total time for setup() = [ 15.098 ] seconds
20:34:20 still running:      52       05:19 python3 main.py
…
20:35:51 setup finished
3780:10/30/2026 12:33:51 AM     INFO:  oraracprov   -     cluchecks      :All required CVU checks passed successfully on node racnode1-0
3840:10/30/2026 12:35:18 AM     INFO:  oraracprov   -     cluchecks      :All required CVU checks passed successfully on node racnode2-0
3873:10/30/2026 12:35:26 AM     INFO:  oraracprov   -       setup        :Total time for setup() = [ 328.67 ] seconds
Instance ORCLCDB1 is running on node racnode1-0
Instance ORCLCDB2 is running on node racnode2-0
Service orclpdbsvc is running on instance(s) ORCLCDB1,ORCLCDB2

   INST_ID NAME       OPEN_MODE
---------- ---------- ----------
         1 ORCLPDB    READ WRITE
         2 ORCLPDB    READ WRITE

   INST_ID VALUE
---------- ------------------------------------------------------------------------------------------
         1 (ADDRESS=(PROTOCOL=TCP)(HOST=racnode1-0-vip.rac.svc.cluster.local)(PORT=31522))
         2 (ADDRESS=(PROTOCOL=TCP)(HOST=racnode2-0-vip.rac.svc.cluster.local)(PORT=31523))

VIP IPv4 Address: 10.244.1.10
VIP IPv4 Address: 10.244.2.8
SCAN 1 IPv4 VIP: 10.244.1.10
SCAN 2 IPv4 VIP: 10.244.2.8
NAME       CURRENT               UPDATE
racnode1   racnode1-75fbb798ff   racnode1-75fbb798ff
racnode2   racnode2-c48dbfc47    racnode2-c48dbfc47
NAME         READY   STATUS    RESTARTS   AGE     IP            NODE         NOMINATED NODE   READINESS GATES
racnode1-0   1/1     Running   0          4m46s   10.244.1.10   op-worker1   <none>           <none>
racnode2-0   1/1     Running   0          4m46s   10.244.2.8    op-worker2   <none>           <none>
NAME    DBNAME    DBSTATE   ROLE      VERSION       PDB CONNECT STR                STATE
racdb   ORCLCDB   OPEN      PRIMARY   19.32.0.0.0   racnode-scan:1521/orclpdbsvc   AVAILABLE
SYSTEM password:
 1  ORCLCDB2  racnode2-0  ORCLPDB
 2  ORCLCDB1  racnode1-0  ORCLPDB
 …
10  ORCLCDB2  racnode2-0  ORCLPDB
oracledb 26.0.1 thin mode: True
connections per instance: {'ORCLCDB2': 4, 'ORCLCDB1': 6}
```

**What 13.6 shows:** a full restart of both RAC pods comes back without any manual step: the scripts restore Grid's files with `rootcrs.sh -updateosfiles`, Clusterware starts and moves the VIPs and SCAN to the new pod IPs, the database opens (`AUTOMATIC`), `ORCLPDB` opens on both instances (saved state), `local_listener` holds (spfile), and Windows reaches both instances through the Phase 12 forwards (the NodePorts follow the pods). The state file stays `provisioning`, because writing `completed` is part of the block the guard skips; the operator reports `AVAILABLE` regardless.

### 13.7 Rules for this lab from now on

| Rule | Why |
| --- | --- |
| **Don't change the env ConfigMaps (`racnodeNracdb-cmap`) while the database is needed.** | Any change makes the operator roll **both** RAC pods together, within minutes, with a 30 s stop: a hard restart of the whole cluster. |
| **Changing `envVars` in the `RacDatabase` has no effect on this cluster.** | For an `instanceDetails`-style spec they only go into the ConfigMaps when the database is first created. `SKIP_DBCA` can't be in the YAML from the start, since the first start must run DBCA; for a new build, add it to both ConfigMaps once the database exists, before any restart, as in 13.6. |
| **Before a planned restart: stop the database, then Clusterware on each pod.** | Kubernetes gives a pod 30 s, too short for RAC to stop cleanly. With the guard in place the pods come back by themselves (13.6). |
| **After a restart, check the pod IPs.** | Each new pod gets a new IP; Clusterware followed (VIPs and SCAN), and so did the names and NodePorts, but anything that uses a pod IP directly won't. |
| **Undo the guard:** remove the `SKIP_DBCA=true` line from both ConfigMaps (or restore `cm-…-before-13.4.yaml`), and `SKIP_DBCA` from `racdb.yaml`. | Needed only for operations that should run the database part of the setup again; it rolls both pods. |

**A full VM shutdown and start** was tested in Phase 14: it works without a manual step if the database is stopped with `crsctl stop crs`; see its runbook (14.6).
