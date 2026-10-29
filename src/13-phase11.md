## Phase 11: The RacDatabase

**Result of this phase:** a 2-node RAC database `ORCLCDB` with the pluggable database `ORCLPDB` and the service `orclpdbsvc`, created by the operator from one YAML file: pods `racnode1-0` and `racnode2-0`, Grid Infrastructure, the ASM disk groups `VOTEDG`, `DATA` and `FRA`, and the database.

### 11.1 Make room for 16 GiB pods (op-controlplane)

**The sizing, from 10.2:** each worker has 17,845,504 KiB (17.0 GiB) allocatable. The operator refuses pods with less than 16 GiB. op-worker1 already has 500 MiB requested and op-worker2 900 MiB, most of it by the operator's own three controller pods (two of them on op-worker2). A 16 GiB RAC pod would fit on op-worker2 with only about 140 MiB to spare, and the pod would stay `Pending` after any restart that moved a controller pod there.

**The fix:** run the operator with one controller pod instead of three. Only one of the three is ever active (the others wait in leader election), so the lab loses nothing but standby copies. That frees about 400 MiB per controller pod removed.

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
kubectl -n oracle-database-operator-system scale deploy/oracle-database-operator-controller-manager --replicas=1
kubectl -n oracle-database-operator-system rollout status deploy/oracle-database-operator-controller-manager --timeout=300s
kubectl -n oracle-database-operator-system get pods -o wide
for w in op-worker1 op-worker2; do echo "--- $w"; kubectl describe node $w | sed -n '/Allocated resources/,/Events/p' | grep -E '^\s+memory\s'; done
```

**Check:** one controller pod `Running`, and each worker's requested memory below about 900 MiB. With 16 GiB for the RAC pod, that leaves more than 1 GiB per worker.

**This lab's output** (the two extra pods were still `Terminating`, so op-worker2's memory hadn't dropped yet; 11.3's first block shows it a few minutes later):

```text
deployment.apps/oracle-database-operator-controller-manager scaled
deployment "oracle-database-operator-controller-manager" successfully rolled out
NAME                                                           READY   STATUS        RESTARTS   AGE   IP           NODE
oracle-database-operator-controller-manager-54cf89dd45-9rjws   1/1     Terminating   0          11h   10.244.2.4   op-worker2
oracle-database-operator-controller-manager-54cf89dd45-f644n   1/1     Running       0          11h   10.244.1.5   op-worker1
oracle-database-operator-controller-manager-54cf89dd45-xl646   1/1     Terminating   0          11h   10.244.2.5   op-worker2
--- op-worker1
  memory             500Mi (2%)  450Mi (2%)
--- op-worker2
  memory             900Mi (5%)  850Mi (4%)
```

**What the pods get:**

| Setting | Value | Why |
| --- | --- | --- |
| `resources` memory | 16Gi (requests = limits) | the operator's minimum; requests = limits keeps the pod in the Guaranteed class, as in the manual lab |
| `resources` hugepages-2Mi | 4Gi | the 2048 pages each worker reserved in 4g |
| `resources` cpu | 3 | 4 vCPUs per worker, one left for the worker itself |
| `sgaSize` / `pgaSize` | 3G / 1G | the SGA must fit in the hugepages, and SGA + PGA must stay within 80 % of the pod's memory |
| `cpuCount` | 3 | matches the CPU limit |

### 11.2 Write and check the RacDatabase (op-controlplane)

**What each part maps to** (the manual lab step it replaces in brackets):

- **`instanceDetails`:** 2 nodes named `racnode1-0` / `racnode2-0`, Oracle homes under `/scratch/rac/cluster01/racnode<n>` (manual 4f, 10.4), private interfaces `eth1` / `eth2` from the two Multus networks (6.3), on workers labelled `raccluster=raccluster01` (5.4).
- **`envVars`:** the setup log in `/tmp/orod`, and `IGNORE_CRS_PREREQS` / `IGNORE_DB_PREREQS`: in a container on VirtualBox some optional prerequisite checks always fail (no swap, `/dev/shm` as tmpfs), as the manual lab's `INS-13014` warnings showed (manual 11.4).
- **`CRS_ASM_DISCOVERY_STRING`:** the list of disks ASM may look at (its `asm_diskstring`). **Without it the install fails at the DATA/FRA step** (see 11.4): Oracle's setup script builds the discovery string from the first `CRSDG` disk only, by cutting the last 2 characters of its path and adding `*`. That works for names like `/dev/sdd` → `/dev/sd*`, but each by-id name starts with its own UUID, so only the vote disk would match. Listing all three paths lets ASM see every disk from the start.
- **`asmDiskGroupDetails`:** three disk groups, each on one disk from 10.1 and with external redundancy (VirtualBox is the only copy anyway): `VOTEDG` of type `CRSDG` for the cluster's voting file and OCR, `DATA` of type `DBDATAFILESDG` for the database files, and `FRA` of type `DBRECOVERY` for the recovery area. The operator creates the PVs (manual Phase 7) and Grid creates `VOTEDG` during its install; the database groups follow before DBCA.
- **`sshKeySecret`, `dbSecret`:** the Secrets from Phase 9, with the same OpenSSL settings used to encrypt the password.
- **`image`, `imagePullPolicy: IfNotPresent`:** the slim image built on each worker in 8.1; `IfNotPresent` because it exists only locally.
- **`resources`, `securityContext.sysctls`:** sizes from 11.1, and the kernel settings the manual lab put in its StatefulSets (10.4). `kernel.shmmax` must be at least the SGA and `kernel.shmall` at least SGA / 4096; 8 GiB and 2,097,152 pages cover the 3 GB SGA.
- **`configParams`:** the same homes as the manual lab, the 19.32 gold-image zips in `/scratch/software/stage` (8.2), `ORCLCDB` with `ORCLPDB`.

The block fills in the three disk paths from `/root/rac-op/asm-disks`, then asks the API server to **check** the file without creating anything (`--dry-run=server`). That runs the operator's own admission check, so any sizing or field problem shows up now.

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
source /root/rac-op/asm-disks; echo "VOTE=$VOTE"; echo "DATA=$DATA"; echo "FRA=$FRA"
cat > /root/rac-op/racdb.yaml <<EOF
apiVersion: database.oracle.com/v4
kind: RacDatabase
metadata:
  name: racdb
  namespace: rac
spec:
  instanceDetails:
    nodeCount: 2
    racHostSwLocation: /scratch/rac/cluster01
    racNodeName: racnode
    privateIPDetails:
      - { name: macvlan-conf1, interface: eth1 }
      - { name: macvlan-conf2, interface: eth2 }
    workerNodeSelector: { raccluster: raccluster01 }
  envVars:
    - { name: LOG_DIR, value: /tmp/orod }
    - { name: IGNORE_CRS_PREREQS, value: "true" }
    - { name: IGNORE_DB_PREREQS, value: "true" }
    - { name: CRS_ASM_DISCOVERY_STRING, value: "$VOTE,$DATA,$FRA" }
  asmDiskGroupDetails:
    - { name: VOTEDG, redundancy: EXTERNAL, type: CRSDG, disks: [ $VOTE ] }
    - { name: DATA, redundancy: EXTERNAL, type: DBDATAFILESDG, disks: [ $DATA ] }
    - { name: FRA, redundancy: EXTERNAL, type: DBRECOVERY, disks: [ $FRA ] }
  sshKeySecret: { name: ssh-key-secret, privKeySecretName: ssh-privkey, pubKeySecretName: ssh-pubkey }
  dbSecret:
    name: db-user-pass
    keyFileName: key.pem
    pwdFileName: pwdfile.enc
    encryptionType: pkeyutl
    pkeyopt: "rsa_padding_mode:oaep;rsa_oaep_md:sha256;rsa_mgf1_md:sha256"
  image: localhost/oracle/database-rac:19.3.0-slim
  imagePullPolicy: IfNotPresent
  scanSvcName: racnode-scan
  scanSvcTargetPort: 31521
  serviceDetails: { name: orclpdbsvc }
  resources:
    requests: { cpu: "3", memory: 16Gi, hugepages-2Mi: 4Gi }
    limits:   { cpu: "3", memory: 16Gi, hugepages-2Mi: 4Gi }
  securityContext:
    sysctls:
      - { name: kernel.shmall, value: "2097152" }
      - { name: kernel.sem, value: "250 32000 100 128" }
      - { name: kernel.shmmax, value: "8589934592" }
      - { name: kernel.shmmni, value: "4096" }
      - { name: net.ipv4.conf.all.rp_filter, value: "2" }
  configParams:
    gridHome: /u01/app/19c/grid
    gridBase: /u01/app/grid
    dbHome: /u01/app/oracle/product/19c/dbhome_1
    dbBase: /u01/app/oracle
    inventory: /u01/app/oraInventory
    hostSwStageLocation: /scratch/software/stage
    gridSwZipFile: oracle-gridhome-19.32.zip
    dbSwZipFile: oracle-dbhome-19.32.zip
    dbName: ORCLCDB
    pdbName: ORCLPDB
    sgaSize: "3G"
    pgaSize: "1G"
    cpuCount: 3
EOF
kubectl apply --dry-run=server -f /root/rac-op/racdb.yaml
```

**Check:** the three `VOTE=`, `DATA=` and `FRA=` paths printed, and `racdatabase.database.oracle.com/racdb created (server dry run)`. Nothing has been created yet. Any `admission webhook ... denied the request` message names the field it objects to; paste it.

**This lab's output (this run's YAML didn't have the CRS_ASM_DISCOVERY_STRING line yet; see 11.4):**

```text
VOTE=/dev/disk/by-id/ata-VBOX_HARDDISK_VB67cb0647-80696c8f
DATA=/dev/disk/by-id/ata-VBOX_HARDDISK_VB74717f76-6ef41222
FRA=/dev/disk/by-id/ata-VBOX_HARDDISK_VB204551ec-809e56f5
racdatabase.database.oracle.com/racdb created (server dry run)
```

### 11.3 Create the database and follow it (op-controlplane)

**What happens after `apply`:** the operator creates the ASM PVs and claims, the headless Services (node names, VIPs, SCAN) and one StatefulSet per node. When both pods are running, the setup scripts in `racnode1-0` unzip the Grid gold image, install and configure Grid on both nodes, create the `VOTEDG` disk group, install the database home, create `DATA` and `FRA` and run DBCA. That's the manual lab's Phases 7 and 10–12 in one go, and took about three hours in this lab: the shared D: drive makes the unzips and DBCA slow.

**First, confirm the file is complete:** a terminal can drop lines from a long paste. The last lines must be the `configParams` values down to `cpuCount: 3`.

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
tail -16 /root/rac-op/racdb.yaml
grep -c . /root/rac-op/racdb.yaml
for w in op-worker1 op-worker2; do echo "--- $w"; kubectl describe node $w | sed -n '/Allocated resources/,/Events/p' | grep -E '^\s+memory\s'; done
```

**Check:** the tail ends with `dbName: ORCLCDB`, `pdbName: ORCLPDB`, `sgaSize: "3G"`, `pgaSize: "1G"`, `cpuCount: 3`; the file has 59 lines; and the requested memory has dropped now that the two extra controller pods are gone (about 500 MiB on op-worker2).

**This lab's output (58 lines: this run's file was one line shorter, without CRS_ASM_DISCOVERY_STRING. The operator pod had moved to op-worker1 when the workers were restarted for vote1):**

```text
      - { name: kernel.shmmni, value: "4096" }
      - { name: net.ipv4.conf.all.rp_filter, value: "2" }
  configParams:
    gridHome: /u01/app/19c/grid
    gridBase: /u01/app/grid
    dbHome: /u01/app/oracle/product/19c/dbhome_1
    dbBase: /u01/app/oracle
    inventory: /u01/app/oraInventory
    hostSwStageLocation: /scratch/software/stage
    gridSwZipFile: oracle-gridhome-19.32.zip
    dbSwZipFile: oracle-dbhome-19.32.zip
    dbName: ORCLCDB
    pdbName: ORCLPDB
    sgaSize: "3G"
    pgaSize: "1G"
    cpuCount: 3
58
--- op-worker1
  memory             500Mi (2%)  450Mi (2%)
--- op-worker2
  memory             100Mi (0%)  50Mi (0%)
```

**Then create it and watch the pods come up:**

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
kubectl apply -f /root/rac-op/racdb.yaml
sleep 30; kubectl -n rac get racdatabase,sts,svc,pvc
kubectl -n rac get pods -o wide -w
```

**Check:** two StatefulSets, the headless Services and three `Bound` PVCs appear, then `racnode1-0` and `racnode2-0` reach `Running` (`0/1` READY is expected for a long time). Note which worker each pod is on. Press Ctrl+C to stop watching.

**This lab's output:**

```text
racdatabase.database.oracle.com/racdb created
NAME                                    DBNAME    DBSTATE   ROLE          VERSION       PDB CONNECT STR   STATE
racdatabase.database.oracle.com/racdb   ORCLCDB   PENDING   NOT_DEFINED   NOT_DEFINED   NOT_DEFINED       PENDING

NAME                        READY   AGE
statefulset.apps/racnode1   0/1     14s
statefulset.apps/racnode2   0/1     14s

NAME                        TYPE        CLUSTER-IP    EXTERNAL-IP   PORT(S)          AGE
service/racnode-scan        ClusterIP   None          <none>        <none>           30s
service/racnode-scan-lsnr   NodePort    10.99.59.33   <none>        1521:31521/TCP   30s
service/racnode1-0          ClusterIP   None          <none>        <none>           30s
service/racnode1-0-vip      ClusterIP   None          <none>        <none>           30s
service/racnode2-0          ClusterIP   None          <none>        <none>           30s
service/racnode2-0-vip      ClusterIP   None          <none>        <none>           30s

NAME                                           STATUS   VOLUME                  CAPACITY   ACCESS MODES
persistentvolumeclaim/asm-pvc-833f4ea4-racdb   Bound    asm-pv-833f4ea4-racdb   10Gi       RWX
persistentvolumeclaim/asm-pvc-c51c7cc4-racdb   Bound    asm-pv-c51c7cc4-racdb   50Gi       RWX
persistentvolumeclaim/asm-pvc-eaac2e15-racdb   Bound    asm-pv-eaac2e15-racdb   50Gi       RWX
NAME                         READY   STATUS        RESTARTS   AGE   IP           NODE
disk-check-daemonset-9p4gz   1/1     Terminating   0          30s   10.244.1.5   op-worker1
disk-check-daemonset-s7fhr   1/1     Terminating   0          30s   10.244.2.3   op-worker2
racnode1-0                   0/1     Running       0          14s   10.244.1.6   op-worker1
racnode2-0                   0/1     Running       0          14s   10.244.2.4   op-worker2
disk-check-daemonset-9p4gz   0/1     Error         0          42s   10.244.1.5   op-worker1
disk-check-daemonset-s7fhr   0/1     Error         0          42s   10.244.2.3   op-worker2
```

The PVC sizes (10Gi, 50Gi, 50Gi) are the sizes the disk check found; the operator only creates the claims and StatefulSets after that check succeeds. The `Error` on the disk-check pods is how Kubernetes records them being stopped when the operator deletes its DaemonSet.

If a pod stays `Pending` or `ContainerCreating` for more than five minutes, run `kubectl -n rac describe pod racnode1-0 | tail -20` and paste the events. If no pods appear at all, the operator's log says why: `kubectl -n oracle-database-operator-system logs deploy/oracle-database-operator-controller-manager --tail=40`.

**Follow the install:**

```bash
# op-controlplane  (about three hours; connect: ssh -p 2220 root@127.0.0.1)
kubectl -n rac exec racnode1-0 -c racnode1-0 -- tail -f /tmp/orod/oracle_db_setup.log
```

**Check:** the log ends with a banner saying **`ORACLE RAC DATABASE IS READY TO USE`**. Press Ctrl+C to stop following; the install carries on regardless. If the log stops moving for more than 20 minutes or shows `ERROR` / `failed` / `[FATAL]`, paste its last 40 lines (`kubectl -n rac exec racnode1-0 -c racnode1-0 -- tail -40 /tmp/orod/oracle_db_setup.log`). The times in the log are UTC.

**This lab's output (key lines of /tmp/orod/oracle_db_setup.log, UTC; … marks cut text):**

```text
Defaulted container "racnode1-0" out of: racnode1-0, racnode1-init1 (init)
00:25:51  orasetupenv - setupsoftware :Grid software file is set : /mnt/stage/software/oracle-gridhome-19.32.zip
00:25:51  … su - grid -c " unzip -q /mnt/stage/software/oracle-gridhome-19.32.zip -d /u01/app/19c/grid"
00:50:39  … OS command returned code : 0                       (Grid unzip done, 25 min)
00:50:42  … mv /usr/bin/scp /usr/bin/scp.openssh && printf … 'exec /usr/bin/scp.openssh -O -T "$@"' > /usr/bin/scp
00:50:42  orasetupenv - configurelegacyscpfor19c :Installed Oracle 19c OpenSSH scp wrapper at /usr/bin/scp for OL9
00:50:42  oracommon - setasmdiskperm :CRS_ASM_DEVICE_LIST variable is set
00:50:42  … chmod 660 /dev/disk/by-id/ata-VBOX_HARDDISK_VB67cb0647-80696c8f;chown grid:asmadmin …
00:50:42  oracommon - setasmdiskperm :RECO_ASM_DEVICE_LIST variable is set
00:50:42  … chmod 660 /dev/disk/by-id/ata-VBOX_HARDDISK_VB204551ec-809e56f5;chown grid:asmadmin …
00:50:42  oracommon - setasmdiskperm :DB_ASM_DEVICE_LIST variable is set
00:50:42  … chmod 660 /dev/disk/by-id/ata-VBOX_HARDDISK_VB74717f76-6ef41222;chown grid:asmadmin …
00:50:42  … su - oracle -c " unzip -q /mnt/stage/software/oracle-dbhome-19.32.zip -d /u01/app/oracle/product/19c/dbhome_1"
01:17:57  orasshsetup - setupsshusekey :Configuring SSH trust racnode1-0 -> racnode1-0
01:18:03  orasshsetup - setupsshusekey :Configuring SSH trust racnode1-0 -> racnode2-0
01:19:49  WARNING: orasshsetup - setupsshusekey :SSH trust not ready yet for racnode1-0 -> racnode2-0. This is expected during setup …
01:19:49  … cat /mnt/.ssh/ssh-privkey > /home/oracle/.ssh/id_rsa
01:19:51  orasetupenv - setbanner :
          ======================================================================
          Since OP_TYPE is set to setuprac, setup will be initiated on this node
          ======================================================================
01:19:51  orasetupenv - finalizeorasetupenv :Total time for orasetupenv setup() = [ 3245.418 ] seconds
01:20:02  orasetupenv - waitfororasetupenvcompletion :orasetupenv completed successfully on all CRS nodes
01:20:02  orasetupenv - finalizeorasetupenv :Final SSH verification successful on all cluster nodes
01:20:02  WARNING: … Env variable ASM_DISCOVERY_DIR is not set .Ignoring the variable and procedding further..
01:20:02  … openssl pkeyutl -decrypt -pkeyopt "rsa_padding_mode:oaep" … -in "/mnt/.dbsecrets/pwdfile.enc" …
01:20:02  oracommon - setpassword :ORACLE_PWD set to HIDDEN_STRING generated using encrypted password file
01:20:02  oragiprov - performsshsetup :Injected SSH keys detected; skipping legacy SSH setup
01:20:03  … su - grid -c "ssh racnode1-0 'export CV_ASSUME_DISTID=OL8; /u01/app/19c/grid/gridSetup.sh  -ignorePreReq
             -waitforcompletion  -noCopy  -silent oracle.install.option=CRS_SWONLY INVENTORY_LOCATION=/u01/app/oraInventory
             ORACLE_HOME=/u01/app/19c/grid ORACLE_BASE=/u01/app/grid oracle.install.asm.OSDBA=asmdba …'"
01:20:13  … (the same on racnode2-0)
01:23:14  … Successfully Setup Software.
01:23:14  … ssh racnode1-0 sudo /u01/app/oraInventory/orainstRoot.sh   … The execution of the script is complete.
01:23:15  … ssh racnode2-0 sudo /u01/app/oraInventory/orainstRoot.sh   … The execution of the script is complete.
01:23:16  … ssh racnode1-0 sudo /u01/app/19c/grid/root.sh / racnode2-0 … returned code : 0
01:23:20  oragiprov - installcvuqdisk :Successfully installed cvuqdisk file.       (both nodes)
01:23:20  oracommon - extractdomain :Fully Qualified Domain Name (FQDN): racnode1-0.racnode.rac.svc.cluster.local
01:23:20  oracommon - getnwlist :The network card: eth0 for the ip: 10.244.1.6
01:23:20  oracommon - getnwlist :The network card: eth1 for the ip: 10.0.11.140
01:24:45  WARNING: … OS command returned code : 6 … [WARNING] [INS-13014] Target environment does not meet some optional requirements.
          … Successfully Setup Software with warning(s).
01:24:45  WARNING: oracommon - checkoserr :OS command  failed. Flag is set to ignore this error!
01:24:46  … su - grid -c "ssh racnode1-0 sudo /u01/app/19c/grid/root.sh"
01:30:48  … returned code : 0 … Check /u01/app/19c/grid/install/root_racnode1-0_….log
01:30:48  … su - grid -c "ssh racnode2-0 sudo /u01/app/19c/grid/root.sh"
01:35:27  … returned code : 0 … Check /u01/app/19c/grid/install/root_racnode2-0_….log
01:35:27  … su - grid -c "/u01/app/19c/grid/gridSetup.sh -executeConfigTools -responseFile /tmp/grid.rsp -silent"
01:38:39  WARNING: … OPatch failed with error code 106 … cannot locate your -invPtrLoc '…/dbhome_1/oraInst.loc'
01:38:39  oraracprov - logstep :[RAC] db_sw_install :: start
01:38:39  … su - oracle -c "ssh racnode1-0 'export CV_ASSUME_DISTID=OL8; …/dbhome_1/runInstaller -ignorePrereq -waitforcompletion
             -noCopy -silent oracle.install.option=INSTALL_DB_SWONLY … oracle.install.db.CLUSTER_NODES=racnode1-0,racnode2-0 …'"
01:38:39  … (the same on racnode2-0)
01:46:45  … Successfully Setup Software.            (both nodes)
01:46:45  … ssh racnode1-0 sudo /u01/app/oracle/product/19c/dbhome_1/root.sh   … returned code : 0
01:46:46  … ssh racnode2-0 sudo /u01/app/oracle/product/19c/dbhome_1/root.sh   … returned code : 0
01:46:47  WARNING: … ASMCMD-8001: diskgroup 'FRA' does not exist or is not mounted
01:47:06  ERROR: … ORA-15014: path '/dev/disk/by-id/ata-VBOX_HARDDISK_VB204551ec-809e56f5' is not in the discovery set   (see 11.4)
```

**What the log goes through** (times from this lab's run, US Eastern):

| Stage | What happens | Took |
| --- | --- | --- |
| Disk check | a short-lived `disk-check-daemonset` pod per worker reads the disk sizes, then is deleted; its pods show `Error` while terminating, which is normal | seconds |
| Unzips | each pod unzips the Grid home (about 11 GB) and the DB home into its own `/u01`, both pods at once; the log is silent during `unzip -q` | 8:25–9:17 PM |
| SSH | trust for `grid` and `oracle` between the pods, using the keys from `ssh-key-secret` | 2 min |
| Grid software | `gridSetup.sh … -noCopy … CRS_SWONLY` on each node, then `orainstRoot.sh` and `root.sh`; `-noCopy` because every node already has its home, so nothing is copied over the network | 3 min |
| Grid config | `gridSetup.sh -responseFile … -noCopy`, then `root.sh` on racnode1-0 (creates **VOTEDG**, OCR and voting file) and racnode2-0; then `-executeConfigTools` | 15 min |
| DB software | `runInstaller … -noCopy INSTALL_DB_SWONLY` on each node (relinks `bin/oracle`), then the DB `root.sh` | 8 min |
| Disk groups | `asmca -createDiskGroup` for **FRA** and **DATA** | 1 min |
| DBCA | creates `ORCLCDB` (instances on both pods) and `ORCLPDB`, sets up listeners and the service | 80 min (10:03–11:22 PM) |
| **Total** | from `apply` to `ORACLE RAC DATABASE IS READY TO USE`, including the 11.4 stop | about 3 hours |

**Warnings that are expected** (the script logs them and carries on):

- `SSH trust not ready yet for racnode1-0 -> racnode2-0`: racnode2-0 was still finishing its own setup; the later "Final SSH verification successful" is what counts.
- `OPatch failed with error code 106 … cannot locate … oraInst.loc`: the script tries OPatch on a home that isn't registered yet; there are no patches to apply to the 19.32 gold image.
- `returned code : 6 … [INS-13014] Target environment does not meet some optional requirements`: the same container prerequisite warnings as the manual lab.
- `home directory is not empty. skipping software unzipping…` (logged as ERROR): only on a rerun (11.4).
- `ASMCMD-8001: diskgroup 'FRA' does not exist`: the script checks for the disk group before creating it.
- `Could not locate file: …/install/files.lst` in the installer log: there's no file list because nothing was copied.

**Quick checks while it runs** (each takes seconds):

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
for p in racnode1-0 racnode2-0; do echo -n "$p  "; kubectl -n rac exec $p -c $p -- du -sh /u01/app/19c/grid /u01/app/oracle/product/19c/dbhome_1 2>/dev/null | tr '\n' ' '; echo; done
for p in racnode1-0 racnode2-0; do echo "--- $p"; kubectl -n rac exec $p -c $p -- ls -l /u01/app/19c/grid/bin/oracle; done
kubectl -n rac exec racnode1-0 -c racnode1-0 -- bash -c 'f=$(ls -t /u01/app/19c/grid/install/root_racnode1-0_*.log 2>/dev/null | head -1); [ -n "$f" ] && tail -20 "$f"'
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - grid -c "crsctl check cluster -all; olsnodes -n -s; crsctl query css votedisk; asmcmd lsdg; srvctl status nodeapps; srvctl status scan_listener" 2>/dev/null
```

The first line shows the unzips growing (about 11G each when done). The second shows `bin/oracle` once the Grid software-only `root.sh` has run: `-rwsr-s--x grid oinstall`, about 440 MB, on both pods. The third is racnode1-0's `root.sh` log (use `racnode2-0` in both places for the second node). The last works once Grid is configured: CRS, CSS and EVM online on both nodes, both nodes `Active`, one voting disk in `VOTEDG`, the disk groups mounted so far, the VIPs and SCAN listeners running.

**This lab's output (the checks run during the install):**

```text
--- the unzips (watch -n 10 …du -sh …)
racnode1-0  5.8G        /u01/app/19c/grid
racnode2-0  5.5G        /u01/app/19c/grid
…
racnode1-0  128M        /u01/app/oracle/product/19c/dbhome_1
racnode2-0  121M        /u01/app/oracle/product/19c/dbhome_1

--- bin/oracle after the Grid software-only root.sh
--- racnode1-0
-rwsr-s--x. 1 grid oinstall 440858040 Oct 28 01:22 /u01/app/19c/grid/bin/oracle
--- racnode2-0
-rwsr-s--x. 1 grid oinstall 440858040 Oct 28 01:23 /u01/app/19c/grid/bin/oracle

--- root.sh on racnode1-0 (/u01/app/19c/grid/install/root_racnode1-0_*.log)
2026/10/28 01:25:21 CLSRSC-594: Executing installation step 8 of 19: 'ConfigOLR'.
…
2026/10/28 01:26:10 CLSRSC-594: Executing installation step 16 of 19: 'InitConfig'.
2026/10/28 01:27:33 CLSRSC-4002: Successfully installed Oracle Trace File Analyzer (TFA) Collector.
ASM has been created and started successfully.
[DBT-30001] Disk groups created successfully. Check /u01/app/grid/cfgtoollogs/asmca/asmca-261028AM012650.log for details.
2026/10/28 01:27:56 CLSRSC-482: Running command: '/u01/app/19c/grid/bin/ocrconfig -upgrade grid oinstall'
CRS-4256: Updating the profile
Successful addition of voting disk f2a52506ee824fecbf0b6936be04ac26.
Successfully replaced voting disk group with +VOTEDG.
CRS-4256: Updating the profile
CRS-4266: Voting file(s) successfully replaced
##  STATE    File Universal Id                File Name Disk group
--  -----    -----------------                --------- ---------
 1. ONLINE   f2a52506ee824fecbf0b6936be04ac26 (/dev/disk/by-id/ata-VBOX_HARDDISK_VB67cb0647-80696c8f) [VOTEDG]
Located 1 voting disk(s).
2026/10/28 01:28:46 CLSRSC-594: Executing installation step 17 of 19: 'StartCluster'.
2026/10/28 01:29:33 CLSRSC-343: Successfully started Oracle Clusterware stack
2026/10/28 01:29:34 CLSRSC-594: Executing installation step 18 of 19: 'ConfigNode'.
2026/10/28 01:30:29 CLSRSC-594: Executing installation step 19 of 19: 'PostConfig'.
2026/10/28 01:30:48 CLSRSC-325: Configure Oracle Grid Infrastructure for a Cluster ... succeeded

--- root.sh on racnode2-0
2026/10/28 01:31:58 CLSRSC-594: Executing installation step 16 of 19: 'InitConfig'.
2026/10/28 01:32:25 CLSRSC-594: Executing installation step 17 of 19: 'StartCluster'.
2026/10/28 01:34:30 CLSRSC-4002: Successfully installed Oracle Trace File Analyzer (TFA) Collector.
2026/10/28 01:35:04 CLSRSC-343: Successfully started Oracle Clusterware stack
2026/10/28 01:35:27 CLSRSC-325: Configure Oracle Grid Infrastructure for a Cluster ... succeeded

--- the cluster after both root.sh runs
racnode1-0:
CRS-4537: Cluster Ready Services is online
CRS-4529: Cluster Synchronization Services is online
CRS-4533: Event Manager is online
racnode2-0:
CRS-4537: Cluster Ready Services is online
CRS-4529: Cluster Synchronization Services is online
CRS-4533: Event Manager is online
racnode1-0      1       Active
racnode2-0      2       Active
State    Type    Rebal  Sector  Logical_Sector  Block       AU  Total_MB  Free_MB  …  Voting_files  Name
MOUNTED  EXTERN  N         512             512   4096  4194304     10240     9900  …             Y  VOTEDG/
VIP 10.244.1.6 is enabled
VIP 10.244.1.6 is running on node: racnode1-0
VIP 10.244.2.4 is enabled
VIP 10.244.2.4 is running on node: racnode2-0
SCAN listener LISTENER_SCAN1 is running on node racnode1-0
SCAN listener LISTENER_SCAN2 is running on node racnode2-0

--- -executeConfigTools (gridSetupActions*.log)
INFO:  [Oct 28, 2026 1:37:13 AM]   Voting Disk ...PASSED
INFO:  [Oct 28, 2026 1:37:21 AM]   ASM Integrity ...PASSED
INFO:  [Oct 28, 2026 1:37:26 AM]   Network configuration consistency checks ...PASSED
INFO:  [Oct 28, 2026 1:37:29 AM] Exit Status is 0
```

**Following DBCA** (the main log is silent while it runs):

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
kubectl -n rac exec racnode1-0 -c racnode1-0 -- bash -c 'tail -5 $(ls -t /u01/app/oracle/cfgtoollogs/dbca/ORCLCDB/*.log 2>/dev/null | grep -v trace | head -1)'
```

**Check:** percentage lines such as `Copying database files`, `Creating cluster database views`, `Creating Pluggable Databases`, ending at `100% complete`.

**This lab's output (the end of the log, after the 11.4 fix and DBCA; UTC, so 11:22 PM Eastern):**

```text
2026-10-28T03:21:31  Post plug operations are now complete.
                     Pluggable database ORCLPDB with pdb id - 3 is now marked as NEW.
2026-10-28T03:22:12  Pluggable database ORCLPDB opened read write
2026-10-28T03:22:38  Completed: alter pluggable database "ORCLPDB" open  instances=all
2026-10-28T03:22:56  ORCLPDB(3):Started service orclpdbsvc/orclpdbsvc/orclpdbsvc
ORACLE RAC DATABASE IS READY TO USE
```

### 11.4 If DATA or FRA creation fails with ORA-15014 (what happened in this lab)

The first run of this lab, without `CRS_ASM_DISCOVERY_STRING` in the YAML, stopped right after the DB home install:

```text
asmca -silent -createDiskGroup -diskGroupName FRA -redundancy EXTERNAL -disk '/dev/disk/by-id/ata-VBOX_HARDDISK_VB204551ec-…'
[FATAL] [DBT-30006] Exception while Processing Request.
   CAUSE: ORA-15018: diskgroup cannot be created
ORA-15031: disk specification '/dev/disk/by-id/ata-VBOX_HARDDISK_VB204551ec-…' matches no disks
ORA-15014: path '/dev/disk/by-id/ata-VBOX_HARDDISK_VB204551ec-…' is not in the discovery set
```

**Cause:** when Grid was configured, the setup script set ASM's discovery string from the first `CRSDG` disk only: `/dev/disk/by-id/ata-VBOX_HARDDISK_VB67cb0647-80696c*`. That pattern matches the vote disk and nothing else, so ASM couldn't see the DATA and FRA disks. The script marked itself `failed` and stopped. Grid, VOTEDG and both homes were fine.

**Fix without starting over:** widen the discovery string, then run the setup script again. It skips everything already done (unzips, Grid, DB home) and continues with the disk groups and DBCA.

**a. Check the state** (changes nothing):

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
kubectl -n rac exec racnode1-0 -c racnode1-0 -- bash -c 'echo "state: $(cat /tmp/orod/.statefile 2>/dev/null)"'
kubectl -n rac exec racnode1-0 -c racnode1-0 -- ps -eo pid,etime,args --sort=etime | grep -E '[m]ain\.py|[r]unOracle'
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - grid -c "asmcmd dsget"
```

**Check:** `state: failed`; no `main.py` / `runOracle` line, or only short-lived `main.py --checkracinst` / `--checkdbrole` lines (the pod's health probes); `dsget` shows the single `…VB<vote>…*` pattern.

**This lab's output** (only the state was captured here; `dsget` wasn't run before b in this lab):

```text
state before: failed
```

**b. Widen the discovery string** to all three disks. `dsset` writes it to both places ASM keeps it, the cluster profile (GPnP) and the ASM spfile in VOTEDG, so it's cluster-wide and survives restarts; nothing restarts.

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
source /root/rac-op/asm-disks
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - grid -c "asmcmd dsset '$VOTE,$DATA,$FRA'"
for p in racnode1-0 racnode2-0; do echo "--- $p"; kubectl -n rac exec $p -c $p -- su - grid -c "asmcmd dsget; asmcmd lsdsk -p --candidate"; done
```

**Check:** on both pods, `parameter:` and `profile:` list all three paths, and the DATA and FRA disks are listed as `CANDIDATE`. (`command terminated with exit code 1` after `lsdsk --candidate` is normal.)

**This lab's output:**

```text
--- racnode1-0
parameter:/dev/disk/by-id/ata-VBOX_HARDDISK_VB67cb0647-80696c8f, /dev/disk/by-id/ata-VBOX_HARDDISK_VB74717f76-6ef41222, /dev/disk/by-id/ata-VBOX_HARDDISK_VB204551ec-809e56f5
profile:/dev/disk/by-id/ata-VBOX_HARDDISK_VB67cb0647-80696c8f,/dev/disk/by-id/ata-VBOX_HARDDISK_VB74717f76-6ef41222,/dev/disk/by-id/ata-VBOX_HARDDISK_VB204551ec-809e56f5
Group_Num  Disk_Num      Incarn  Mount_Stat  Header_Stat  Mode_Stat  State   Path
        0         1           0  CLOSED      CANDIDATE    ONLINE     NORMAL  /dev/disk/by-id/ata-VBOX_HARDDISK_VB204551ec-809e56f5
        0         0           0  CLOSED      CANDIDATE    ONLINE     NORMAL  /dev/disk/by-id/ata-VBOX_HARDDISK_VB74717f76-6ef41222
command terminated with exit code 1
--- racnode2-0
(the same)
```

**c. Run the setup script again**, detached so it keeps running after you disconnect. The check looks only for a python `main.py` that isn't a health probe; a plain `pgrep -f main.py` would match its own `bash -c` command line and always say "running".

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
kubectl -n rac exec racnode1-0 -c racnode1-0 -- bash -c '
running=$(ps -eo pid,args | awk "\$2 ~ /python/ && /main\\.py/ && !/check/")
if [ -n "$running" ]; then echo "STOP: setup already running:"; echo "$running"; exit 1; fi
setsid nohup /opt/scripts/startup/runOracle.sh > /tmp/orod/rerun.out 2>&1 < /dev/null &
sleep 8; ps -eo pid,etime,args | awk "\$3 ~ /python/ && /main\\.py/ && !/check/" && echo "setup restarted"'
kubectl -n rac exec racnode1-0 -c racnode1-0 -- tail -f /tmp/orod/oracle_db_setup.log
```

**Check:** `python3 main.py` with a few seconds of runtime and `setup restarted`; then new log lines with the current UTC time: "Grid is already installed on this machine … Skipping Grid setup", CVU checks passing on both nodes, `asmca … FRA` and `asmca … DATA` returning code 0, and DBCA starting. From there the install continues as in 11.3.

**This lab's output (the start block's ps lines, then key lines of the log, UTC. The --checkdbrole line is a health probe, correctly ignored):**

```text
 268876       00:07 python3 main.py
 270334       00:01 /bin/python3 /opt/scripts/startup/scripts/main.py --checkdbrole=true
setup restarted
02:00:08  oracommon - checkgiinstalled :
          ===========================================================================================
          Grid is already installed on this machine and /etc/oracle also exist. Skipping Grid setup..
          ===========================================================================================
02:00:16  oragiprov - setup :
          ==========================================
          Grid is already configured on this machine
          ==========================================
02:00:35  … Verification of ASM Integrity was successful.
02:00:40  oraracprov - cluchecks :All required CVU checks passed successfully on node racnode1-0
02:02:13  … asmca -silent -createDiskGroup -diskGroupName FRA -redundancy EXTERNAL -disk '/dev/disk/by-id/ata-VBOX_HARDDISK_VB204551ec-809e56f5'
02:02:52  … returned code : 0 … [INFO] [DBT-30001] Disk groups created successfully.
02:02:54  … asmca -silent -createDiskGroup -diskGroupName DATA -redundancy EXTERNAL -disk '/dev/disk/by-id/ata-VBOX_HARDDISK_VB74717f76-6ef41222'
02:03:31  … returned code : 0 … [INFO] [DBT-30001] Disk groups created successfully.
02:03:32  oraracprov - logstep :[RAC] create_db :: start
02:03:32  … dbca -silent -ignorePreReqs -createDatabase -templateName General_Purpose.dbc -gdbname ORCLCDB
             -createAsContainerDatabase true -sysPassword ******** -systemPassword ******** -datafileDestination +DATA
             -storageType ASM -characterSet AL32UTF8 -redoLogFileSize 1024 -databaseType OLTP -databaseConfigType RAC
             -nodelist racnode1-0,racnode2-0 -useOMF true -numberOfPDBs 1 -pdbAdminPassword ******** -pdbName ORCLPDB
             -initparams 'db_recovery_file_dest=+FRA,db_create_file_dest=+DATA,REMOTE_LOGIN_PASSWORDFILE=EXCLUSIVE,
             LOG_ARCHIVE_FORMAT=%t_%s_%r.arc,db_unique_name=ORCLCDB,db_files=1024,LOG_BUFFER=256M,…,
             DG_BROKER_CONFIG_FILE1=+DATA,DG_BROKER_CONFIG_FILE2=+FRA,DB_CREATE_ONLINE_LOG_DEST_1=+FRA,
             sga_target=3G,sga_max_size=3G,pga_aggregate_target=1G,cpu_count=3' -enableArchive true
```

### 11.5 Verify the database (op-controlplane)

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
kubectl -n rac get racdatabase racdb; kubectl -n rac get pods -o wide
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - oracle -c "srvctl status database -d ORCLCDB -v; srvctl status service -d ORCLCDB"
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - grid -c "asmcmd lsdg"
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - oracle -c 'export ORACLE_SID=ORCLCDB1; sqlplus -s / as sysdba <<EOF
set lines 200 pages 100
col name for a60
select inst_id, instance_name, host_name, status from gv\$instance;
select name, open_mode from v\$pdbs;
select log_mode from v\$database;
select name from v\$controlfile;
select group#, thread#, bytes/1024/1024 mb, member from v\$log join v\$logfile using (group#) order by 1;
show parameter db_recovery_file_dest
EOF'
```

**Check** (this lab's values):

| What | Expected |
| --- | --- |
| `racdb` | `ORCLCDB  OPEN  PRIMARY  19.32.0.0.0  racnode-scan:1521/orclpdbsvc  AVAILABLE` |
| Pods | `racnode1-0` and `racnode2-0` both `1/1 Running` |
| Instances | `ORCLCDB1` on racnode1-0, `ORCLCDB2` on racnode2-0, both `OPEN`; `orclpdbsvc` on both |
| PDBs | `PDB$SEED READ ONLY`, `ORCLPDB READ WRITE` |
| Log mode | `ARCHIVELOG` |
| Disk groups | `DATA` and `FRA` 51200 MB, `VOTEDG` 10240 MB (`Voting_files Y`), all `MOUNTED EXTERN` |
| Control file | **one**, `+FRA/ORCLCDB/CONTROLFILE/current.…` |
| Redo | 4 groups of 1024 MB (2 per thread), **one member each, all in `+FRA`** |
| Recovery area | `db_recovery_file_dest +FRA`, `db_recovery_file_dest_size 23895M` (DBCA's default) |

**This lab's output:**

```text
NAME    DBNAME    DBSTATE   ROLE      VERSION       PDB CONNECT STR                STATE
racdb   ORCLCDB   OPEN      PRIMARY   19.32.0.0.0   racnode-scan:1521/orclpdbsvc   AVAILABLE
NAME         READY   STATUS    RESTARTS   AGE   IP           NODE
racnode1-0   1/1     Running   0          11h   10.244.1.6   op-worker1
racnode2-0   1/1     Running   0          11h   10.244.2.4   op-worker2
Instance ORCLCDB1 is running on node racnode1-0 with online services orclpdbsvc. Instance status: Open.
Instance ORCLCDB2 is running on node racnode2-0 with online services orclpdbsvc. Instance status: Open.
Service orclpdbsvc is running on instance(s) ORCLCDB1,ORCLCDB2
State    Type    Rebal  Sector  Logical_Sector  Block       AU  Total_MB  Free_MB  Req_mir_free_MB  Usable_file_MB  Offline_disks  Voting_files  Name
MOUNTED  EXTERN  N         512             512   4096  1048576     51200    44128                0           44128              0             N  DATA/
MOUNTED  EXTERN  N         512             512   4096  1048576     51200    46197                0           46197              0             N  FRA/
MOUNTED  EXTERN  N         512             512   4096  4194304     10240     9884                0            9884              0             Y  VOTEDG/

   INST_ID INSTANCE_NAME    HOST_NAME            STATUS
---------- ---------------- -------------------- ------------
         2 ORCLCDB2         racnode2-0           OPEN
         1 ORCLCDB1         racnode1-0           OPEN

NAME                                                         OPEN_MODE
------------------------------------------------------------ ----------
PDB$SEED                                                     READ ONLY
ORCLPDB                                                      READ WRITE

LOG_MODE
------------
ARCHIVELOG

NAME
------------------------------------------------------------
+FRA/ORCLCDB/CONTROLFILE/current.256.1247796495

    GROUP#    THREAD#         MB MEMBER
---------- ---------- ---------- ----------------------------------------------
         1          1       1024 +FRA/ORCLCDB/ONLINELOG/group_1.258.1247796499
         2          1       1024 +FRA/ORCLCDB/ONLINELOG/group_2.257.1247796499
         3          2       1024 +FRA/ORCLCDB/ONLINELOG/group_3.259.1247800443
         4          2       1024 +FRA/ORCLCDB/ONLINELOG/group_4.260.1247800527

NAME                                 TYPE        VALUE
------------------------------------ ----------- ------------------------------
db_recovery_file_dest                string      +FRA
db_recovery_file_dest_size           big integer 23895M
```

**What the alert log shows afterwards** (`/u01/app/oracle/diag/rdbms/orclcdb/ORCLCDB1/trace/alert_ORCLCDB1.log`): regular `Warning: long redo log write elapsed times detected`. All VM disks share one D: drive and redo shares the FRA disk with archiving, so log writes are slow; harmless in the lab. The repeated `ALTER SYSTEM SET _ipddb_enable=TRUE` lines come from the operator's health checks.

**This lab's output (alert_ORCLCDB1.log the next morning, UTC):**

```text
2026-10-28T03:28:35  Resize operation completed for file# 3, fname +DATA/ORCLCDB/DATAFILE/sysaux.258.1247796421, old size 880640K, new size 911360K
2026-10-28T03:30:29  ALTER SYSTEM SET _ipddb_enable=TRUE SCOPE=MEMORY SID='ORCLCDB1';
…
2026-10-28T04:05:53  Warning: long redo log write elapsed times detected, the LG* process tracefiles have more details
…
2026-10-28T10:00:46  Thread 1 advanced to log sequence 6 (LGWR switch),  current SCN: 2601276
                       Current log# 2 seq# 6 mem# 0: +FRA/ORCLCDB/ONLINELOG/group_2.257.1247796499
2026-10-28T10:01:25  ARC2 (PID:827359): Archived Log entry 2 added for B-1247796498.T-1.S-5 …
2026-10-28T11:06:05  Warning: long redo log write elapsed times detected, the LG* process tracefiles have more details
```

### 11.6 Put a second control file and redo member in DATA (op-controlplane)

**Why:** the setup script sets `DB_CREATE_ONLINE_LOG_DEST_1=+FRA` when there's no `DBREDO` disk group, and with that set, Oracle's managed file naming puts the control file only there. The result in 11.5 is a single control file and single-member redo groups, all in FRA: losing that one disk group loses the database's only control file and its online redo. The usual layout has one copy of each in DATA and one in FRA.

**a. A redo member in DATA for each group** (the database stays open):

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - oracle -c 'export ORACLE_SID=ORCLCDB1; sqlplus -s / as sysdba <<EOF
alter database add logfile member '"'"'+DATA'"'"' to group 1;
alter database add logfile member '"'"'+DATA'"'"' to group 2;
alter database add logfile member '"'"'+DATA'"'"' to group 3;
alter database add logfile member '"'"'+DATA'"'"' to group 4;
alter system archive log current;
set lines 200
col member for a70
select group#, status, member from v\$logfile order by 1, member;
EOF'
```

**Check:** four `Database altered.`, then two members per group, one `+DATA/ORCLCDB/ONLINELOG/group_N.…` and one `+FRA/ORCLCDB/ONLINELOG/group_N.…`. In this lab the new members of groups 2 and 4 showed `INVALID`: a new member stays `INVALID` until its group is next written, which clears by itself after log switches (checked in c).

**This lab's output:**

```text
Database altered.
Database altered.
Database altered.
Database altered.
System altered.

    GROUP# STATUS  MEMBER
---------- ------- ----------------------------------------------------------------------
         1         +DATA/ORCLCDB/ONLINELOG/group_1.274.1247831211
         1         +FRA/ORCLCDB/ONLINELOG/group_1.258.1247796499
         2 INVALID +DATA/ORCLCDB/ONLINELOG/group_2.275.1247831285
         2         +FRA/ORCLCDB/ONLINELOG/group_2.257.1247796499
         3         +DATA/ORCLCDB/ONLINELOG/group_3.276.1247831353
         3         +FRA/ORCLCDB/ONLINELOG/group_3.259.1247800443
         4 INVALID +DATA/ORCLCDB/ONLINELOG/group_4.277.1247831421
         4         +FRA/ORCLCDB/ONLINELOG/group_4.260.1247800527

8 rows selected.
```

**b. A second control file in DATA** (about 5 minutes of downtime). The block changes the setting to "one copy in DATA, one in FRA", stops the database, starts only instance 1 without mounting, lets RMAN write two new copies from the current file (RMAN also writes their names into the spfile), and starts the database again. The original file isn't touched, so if anything fails you can go back to it.

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
CF=$(kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - oracle -c "export ORACLE_SID=ORCLCDB1; echo 'set head off feed off
select name from v\$controlfile;' | sqlplus -s / as sysdba" | grep -m1 '^+')
echo "current control file: $CF"
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - oracle -c "export ORACLE_SID=ORCLCDB1; echo \"alter system set control_files='+DATA','+FRA' scope=spfile sid='*';\" | sqlplus -s / as sysdba
srvctl stop database -d ORCLCDB
srvctl start instance -d ORCLCDB -i ORCLCDB1 -startoption nomount
rman target / <<EOF
restore controlfile from '$CF';
EOF
srvctl stop instance -d ORCLCDB -i ORCLCDB1
srvctl start database -d ORCLCDB
echo 'select name from v\$controlfile;' | sqlplus -s / as sysdba
srvctl status database -d ORCLCDB"
kubectl -n rac get racdatabase racdb
```

**Check** (this lab's output): `System altered.`; RMAN `connected to target database: ORCLCDB (not mounted)`, `channel ORA_DISK_1: copied control file copy`, `output file name=+DATA/ORCLCDB/CONTROLFILE/current.278.…` and `output file name=+FRA/ORCLCDB/CONTROLFILE/current.267.…`; then both names from `v$controlfile`, and `Instance ORCLCDB1 is running on node racnode1-0`, `Instance ORCLCDB2 is running on node racnode2-0`. If anything fails after `srvctl stop database`, stop and paste the output.

**This lab's output (this run set CF by hand to the same value instead of the CF=$(…) line):**

```text
current control file: +FRA/ORCLCDB/CONTROLFILE/current.256.1247796495
System altered.

Recovery Manager: Release 19.0.0.0.0 - Production on Wed Oct 28 11:52:51 2026
Version 19.32.0.0.0
connected to target database: ORCLCDB (not mounted)

RMAN> restore controlfile from '+FRA/ORCLCDB/CONTROLFILE/current.256.1247796495';
Starting restore at 28-OCT-26
using target database control file instead of recovery catalog
allocated channel: ORA_DISK_1
channel ORA_DISK_1: SID=357 instance=ORCLCDB1 device type=DISK

channel ORA_DISK_1: copied control file copy
output file name=+DATA/ORCLCDB/CONTROLFILE/current.278.1247831575
output file name=+FRA/ORCLCDB/CONTROLFILE/current.267.1247831577
Finished restore at 28-OCT-26

Recovery Manager complete.

NAME
--------------------------------------------------------------------------------
+DATA/ORCLCDB/CONTROLFILE/current.278.1247831575
+FRA/ORCLCDB/CONTROLFILE/current.267.1247831577

Instance ORCLCDB1 is running on node racnode1-0
Instance ORCLCDB2 is running on node racnode2-0
```

**c. Check the database is fully back, then remove the old control file.** The old `current.256…` in FRA is no longer in `control_files`; the block only removes it if the database doesn't list it any more.

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
OLD=+FRA/ORCLCDB/CONTROLFILE/current.256.1247796495
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - oracle -c "srvctl status database -d ORCLCDB -v; srvctl status service -d ORCLCDB"
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - oracle -c 'export ORACLE_SID=ORCLCDB1; sqlplus -s / as sysdba <<EOF
set lines 200 pages 100
col member for a70
col name for a60
alter system archive log current;
alter system archive log current;
select name, open_mode from v\$pdbs;
select name from v\$controlfile;
select group#, status, member from v\$logfile order by 1, member;
EOF'
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - oracle -c "export ORACLE_SID=ORCLCDB1; echo 'select name from v\$controlfile;' | sqlplus -s / as sysdba" | grep -q "$OLD" && echo "STOP: $OLD is still in use" || kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - grid -c "asmcmd rm $OLD; asmcmd ls +FRA/ORCLCDB/CONTROLFILE/"
kubectl -n rac get racdatabase racdb
```

**Check** (this lab's output): both instances `Open` with `orclpdbsvc`; `ORCLPDB READ WRITE`; the two control files `+DATA/…/current.278…` and `+FRA/…/current.267…`; all eight redo members without a status (the `INVALID` from a is gone); `asmcmd ls` shows only `current.267.…`; `racdb … OPEN PRIMARY 19.32.0.0.0 racnode-scan:1521/orclpdbsvc AVAILABLE`. If `ORCLPDB` shows `MOUNTED` instead, run `alter pluggable database ORCLPDB open instances=all;` and `alter pluggable database ORCLPDB save state instances=all;` as sysdba.

**This lab's output:**

```text
Instance ORCLCDB1 is running on node racnode1-0 with online services orclpdbsvc. Instance status: Open.
Instance ORCLCDB2 is running on node racnode2-0 with online services orclpdbsvc. Instance status: Open.
Service orclpdbsvc is running on instance(s) ORCLCDB1,ORCLCDB2
System altered.
System altered.

NAME                                                         OPEN_MODE
------------------------------------------------------------ ----------
PDB$SEED                                                     READ ONLY
ORCLPDB                                                      READ WRITE

NAME
------------------------------------------------------------
+DATA/ORCLCDB/CONTROLFILE/current.278.1247831575
+FRA/ORCLCDB/CONTROLFILE/current.267.1247831577

    GROUP# STATUS  MEMBER
---------- ------- ----------------------------------------------------------------------
         1         +DATA/ORCLCDB/ONLINELOG/group_1.274.1247831211
         1         +FRA/ORCLCDB/ONLINELOG/group_1.258.1247796499
         2         +DATA/ORCLCDB/ONLINELOG/group_2.275.1247831285
         2         +FRA/ORCLCDB/ONLINELOG/group_2.257.1247796499
         3         +DATA/ORCLCDB/ONLINELOG/group_3.276.1247831353
         3         +FRA/ORCLCDB/ONLINELOG/group_3.259.1247800443
         4         +DATA/ORCLCDB/ONLINELOG/group_4.277.1247831421
         4         +FRA/ORCLCDB/ONLINELOG/group_4.260.1247800527

8 rows selected.

current.267.1247831577
NAME    DBNAME    DBSTATE   ROLE      VERSION       PDB CONNECT STR                STATE
racdb   ORCLCDB   OPEN      PRIMARY   19.32.0.0.0   racnode-scan:1521/orclpdbsvc   AVAILABLE
```

**For the next build:** a fourth disk group of type `DBREDO` in the YAML sets the online log destination separately from FRA; this lab didn't test that.

