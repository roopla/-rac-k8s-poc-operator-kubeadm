## Phase 12: Access from Windows

**Result of this phase:** a client on the Windows PC connects through SCAN (`127.0.0.1:31521/orclpdbsvc`), is sent on to either instance, and reconnects to the other instance when one goes away.

**How a RAC connection works, and why it fails from Windows today:**

1. The client connects to a SCAN listener (`LISTENER_SCAN1` or `2`, port 1521).
2. The SCAN listener picks an instance offering the service and **redirects** the client to that instance's node listener, using the address the instance registered: its `local_listener`.
3. The client opens a second connection to that address.

Inside the cluster all three steps work. From Windows, step 1 reaches SCAN once there's a port forward to the NodePort `racnode-scan-lsnr` (31521), but step 2 hands out a pod IP and port 1522 (12.1), which Windows can't reach. So each instance needs a redirect address that Windows **and** the pods can reach.

**The plan** (12.1 shows the starting point):

| | racnode1-0 / ORCLCDB1 | racnode2-0 / ORCLCDB2 |
| --- | --- | --- |
| extra node listener port (both nodes listen on both) | 31522 | 31523 |
| `local_listener` | `racnode1-0-vip.rac.svc.cluster.local:31522` | `racnode2-0-vip.rac.svc.cluster.local:31523` |
| that name, inside the cluster | the pod IP (headless Service), so the instance registers on 31522 | the pod IP, on 31523 |
| new NodePort Service | 31522 → racnode1-0:31522 | 31523 → racnode2-0:31523 |
| Windows NAT forward | 127.0.0.1:31522 → 10.0.1.21:31522 | 127.0.0.1:31523 → 10.0.1.21:31523 |
| Windows `hosts` (already there) | `racnode1-0-vip.rac.svc.cluster.local` → 127.0.0.1 | `racnode2-0-vip.rac.svc.cluster.local` → 127.0.0.1 |

Plus 127.0.0.1:31521 → 10.0.1.21:31521 for SCAN. All forwards may go to op-worker1: a NodePort answers on every node and Kubernetes routes on to the right pod.

**Why a different port per node:** the port SCAN hands out must be the same number on Windows, on the NodePort and on the listener, and Windows reaches both nodes through the one address 127.0.0.1. Two nodes on 1522 can't share it.

**Why not the operator's NodePort option:** the `RacDatabase` fields for node-listener NodePorts (`baseLsnrTargetPort`) only take effect when the database is first created; this cluster already exists, so the same result is set up by hand here. For a new build they belong in the YAML (not tested in this lab).

### 12.1 Where things stand (read-only)

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
kubectl get nodes; kubectl -n rac get racdatabase racdb
kubectl -n rac get pods -o wide
kubectl -n rac get svc -o wide
kubectl -n rac get endpoints
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - grid -c "srvctl config scan; srvctl config scan_listener; srvctl config listener; srvctl status listener; lsnrctl status LISTENER | grep -E 'Alias|Listening|Service \"'"
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - oracle -c "srvctl config service -d ORCLCDB -s orclpdbsvc | grep -E 'Service name|Preferred|Available|Connection Load|Failover'"
for i in 1 2; do echo "=== ORCLCDB$i"; kubectl -n rac exec -i racnode$i-0 -c racnode$i-0 -- su - oracle -c "export ORACLE_SID=ORCLCDB$i; sqlplus -s / as sysdba" <<'EOF'
set lines 200 pages 50
col name for a16
col value for a110
select name, value from v$parameter where name in ('local_listener','remote_listener');
EOF
done
for i in 1 2; do echo "=== racnode$i-0"; kubectl -n rac exec racnode$i-0 -c racnode$i-0 -- su - grid -c "lsnrctl status LISTENER | grep DESCRIPTION; lsnrctl status LISTENER_SCAN$i | grep -E 'DESCRIPTION|orclpdbsvc'"; done
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - grid -c "srvctl status scan_listener"
```

```powershell
# PowerShell on the Windows PC
$VB = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
"--- NAT forwards on k8s-public"; & $VB natnetwork list | Select-String 'Name:|ssh-op|:31|:15|:64'
"--- hosts entries"; Select-String -Path C:\Windows\System32\drivers\etc\hosts -Pattern 'racnode|scan' -ErrorAction SilentlyContinue
"--- python"; python --version; python -m pip show oracledb 2>$null | Select-String '^(Name|Version):'
"--- port 31521 from Windows"; Test-NetConnection 127.0.0.1 -Port 31521 -InformationLevel Quiet
```

**What it showed in this lab:**

| What | Found |
| --- | --- |
| cluster | three nodes `Ready`; `racdb` `OPEN`, `19.32.0.0.0`, `AVAILABLE`; both pods `1/1 Running` |
| SCAN | `racnode-scan`, two SCAN VIPs = the two pod IPs; `LISTENER_SCAN1` on racnode1-0, `LISTENER_SCAN2` on racnode2-0, both **TCP 1521** |
| node listener | `LISTENER` on **TCP 1522** (not 1521), on each pod's own IP |
| `racnode-scan-lsnr` | NodePort `1521:31521`, selecting **only racnode1-0** (endpoint `10.244.1.6:1521`): from outside, 31521 always reaches `LISTENER_SCAN1`, which knows both instances |
| `local_listener` | `(ADDRESS=(PROTOCOL=TCP)(HOST=10.244.1.6)(PORT=1522))` and `…10.244.2.4…1522`: pod IPs, the address SCAN hands to clients |
| `remote_listener` | `racnode-scan:1521` on both instances; `orclpdbsvc` registered with both SCAN listeners (2 instances each) |
| `orclpdbsvc` | preferred on `ORCLCDB1,ORCLCDB2`, load balancing goal `LONG`, **no failover type** set |
| Windows | only the SSH and API forwards; `hosts` already maps both `-vip` names to 127.0.0.1; Python 3.14.5 with `oracledb` 26.0.1 (thin mode, no Oracle client needed); 31521 not reachable yet |

**This lab's output (cluster):**

```text
NAME              STATUS   ROLES           AGE   VERSION
op-controlplane   Ready    control-plane   45h   v1.36.5
op-worker1        Ready    worker          45h   v1.36.5
op-worker2        Ready    worker          45h   v1.36.5
NAME    DBNAME    DBSTATE   ROLE      VERSION       PDB CONNECT STR                STATE
racdb   ORCLCDB   OPEN      PRIMARY   19.32.0.0.0   racnode-scan:1521/orclpdbsvc   AVAILABLE
NAME         READY   STATUS    RESTARTS   AGE   IP           NODE         NOMINATED NODE   READINESS GATES
racnode1-0   1/1     Running   0          23h   10.244.1.6   op-worker1   <none>           <none>
racnode2-0   1/1     Running   0          23h   10.244.2.4   op-worker2   <none>           <none>
NAME                TYPE        CLUSTER-IP    EXTERNAL-IP   PORT(S)          AGE   SELECTOR
racnode-scan        ClusterIP   None          <none>        <none>           23h   app=oracle-database-operator,database.oracle.com/component=RAC,database.oracle.com/managed-by=racdatabase-controller,database.oracle.com/name=racdb
racnode-scan-lsnr   NodePort    10.99.59.33   <none>        1521:31521/TCP   23h   statefulset.kubernetes.io/pod-name=racnode1-0
racnode1-0          ClusterIP   None          <none>        <none>           23h   statefulset.kubernetes.io/pod-name=racnode1-0
racnode1-0-vip      ClusterIP   None          <none>        <none>           23h   statefulset.kubernetes.io/pod-name=racnode1-0
racnode2-0          ClusterIP   None          <none>        <none>           23h   statefulset.kubernetes.io/pod-name=racnode2-0
racnode2-0-vip      ClusterIP   None          <none>        <none>           23h   statefulset.kubernetes.io/pod-name=racnode2-0
Warning: v1 Endpoints is deprecated in v1.33+; use discovery.k8s.io/v1 EndpointSlice
NAME                ENDPOINTS               AGE
racnode-scan        10.244.1.6,10.244.2.4   23h
racnode-scan-lsnr   10.244.1.6:1521         23h
racnode1-0          10.244.1.6              23h
racnode1-0-vip      10.244.1.6              23h
racnode2-0          10.244.2.4              23h
racnode2-0-vip      10.244.2.4              23h
SCAN name: racnode-scan, Network: 1
Subnet IPv4: 10.244.0.0/255.255.0.0/eth0, static
Subnet IPv6:
SCAN 1 IPv4 VIP: 10.244.1.6
SCAN VIP is enabled.
SCAN 2 IPv4 VIP: 10.244.2.4
SCAN VIP is enabled.
SCAN Listeners for network 1:
Registration invited nodes:
Registration invited subnets:
Endpoints: TCP:1521
SCAN Listener LISTENER_SCAN1 exists
SCAN Listener is enabled.
SCAN Listener LISTENER_SCAN2 exists
SCAN Listener is enabled.
Name: LISTENER
Type: Database Listener
Network: 1, Owner: grid
Home: <CRS home>
End points: TCP:1522
Listener is enabled.
Listener is individually enabled on nodes:
Listener is individually disabled on nodes:
Listener LISTENER is enabled
Listener LISTENER is running on node(s): racnode1-0,racnode2-0
Alias                     LISTENER
Listening Endpoints Summary...
Service "+ASM" has 1 instance(s).
Service "+ASM_DATA" has 1 instance(s).
Service "+ASM_FRA" has 1 instance(s).
Service "+ASM_VOTEDG" has 1 instance(s).
Service "5edf079783cfb131e0630601f40a4240" has 1 instance(s).
Service "ORCLCDB" has 1 instance(s).
Service "ORCLCDBXDB" has 1 instance(s).
Service "orclpdb" has 1 instance(s).
Service "orclpdbsvc" has 1 instance(s).
Service name: orclpdbsvc
Failover type:
Failover method:
Failover retries:
Failover delay:
Failover restore: NONE
Connection Load Balancing Goal: LONG
Preferred instances: ORCLCDB1,ORCLCDB2
Available instances:
=== ORCLCDB1

NAME             VALUE
---------------- --------------------------------------------------------------------------------------------------------------
local_listener    (ADDRESS=(PROTOCOL=TCP)(HOST=10.244.1.6)(PORT=1522))
remote_listener   racnode-scan:1521

=== ORCLCDB2

NAME             VALUE
---------------- --------------------------------------------------------------------------------------------------------------
local_listener    (ADDRESS=(PROTOCOL=TCP)(HOST=10.244.2.4)(PORT=1522))
remote_listener   racnode-scan:1521

=== racnode1-0
Connecting to (DESCRIPTION=(ADDRESS=(PROTOCOL=IPC)(KEY=LISTENER)))
  (DESCRIPTION=(ADDRESS=(PROTOCOL=ipc)(KEY=LISTENER)))
  (DESCRIPTION=(ADDRESS=(PROTOCOL=tcp)(HOST=10.244.1.6)(PORT=1522)))
Connecting to (DESCRIPTION=(ADDRESS=(PROTOCOL=IPC)(KEY=LISTENER_SCAN1)))
  (DESCRIPTION=(ADDRESS=(PROTOCOL=ipc)(KEY=LISTENER_SCAN1)))
  (DESCRIPTION=(ADDRESS=(PROTOCOL=tcp)(HOST=10.244.1.6)(PORT=1521)))
Service "orclpdbsvc" has 2 instance(s).
=== racnode2-0
Connecting to (DESCRIPTION=(ADDRESS=(PROTOCOL=IPC)(KEY=LISTENER)))
  (DESCRIPTION=(ADDRESS=(PROTOCOL=ipc)(KEY=LISTENER)))
  (DESCRIPTION=(ADDRESS=(PROTOCOL=tcp)(HOST=10.244.2.4)(PORT=1522)))
Connecting to (DESCRIPTION=(ADDRESS=(PROTOCOL=IPC)(KEY=LISTENER_SCAN2)))
  (DESCRIPTION=(ADDRESS=(PROTOCOL=ipc)(KEY=LISTENER_SCAN2)))
  (DESCRIPTION=(ADDRESS=(PROTOCOL=tcp)(HOST=10.244.2.4)(PORT=1521)))
Service "orclpdbsvc" has 2 instance(s).
SCAN Listener LISTENER_SCAN1 is enabled
SCAN listener LISTENER_SCAN1 is running on node racnode1-0
SCAN Listener LISTENER_SCAN2 is enabled
SCAN listener LISTENER_SCAN2 is running on node racnode2-0
```

**This lab's output (Windows):**

```text
--- NAT forwards on k8s-public

Name:         k8s-public
        k8sapi:tcp:[]:6443:[10.0.1.10]:6443
        k8sapi-op:tcp:[]:6444:[10.0.1.20]:6443
        ssh-opcp:tcp:[]:2220:[10.0.1.20]:22
        ssh-opw1:tcp:[]:2221:[10.0.1.21]:22
        ssh-opw2:tcp:[]:2222:[10.0.1.22]:22

--- hosts entries

C:\Windows\System32\drivers\etc\hosts:41:127.0.0.1 racnode1-0-vip.rac.svc.cluster.local
C:\Windows\System32\drivers\etc\hosts:42:127.0.0.1 racnode2-0-vip.rac.svc.cluster.local

--- python
Python 3.14.5

Name: oracledb
Version: 26.0.1

--- port 31521 from Windows
WARNING: TCP connect to (127.0.0.1 : 31521) failed
False
```

**The first version of the `local_listener` query failed (fixed above):** it put the parameter names in double quotes inside the `su -c "…"` line. In SQL, double quotes mark identifiers, so Oracle read `"remote_listener"` as a column name. The block above feeds the SQL through a heredoc, so it can use the single quotes SQL needs.

```text
select name, value from v$parameter where name in ("local_listener","remote_listener")
                                                                    *
ERROR at line 1:
ORA-00904: "remote_listener": invalid identifier
```

### 12.2 Add ports 31522 and 31523 to the node listener

**What:** `LISTENER` on both nodes listens on 31522 and 31523 as well as 1522.

**Why both ports on both nodes:** a listener's endpoints are one cluster-wide setting, the same on every node. Each instance will use only its own port (12.3); the other one is unused but harmless.

**Interruption:** the new ports take effect when the listener restarts; the block restarts it one node at a time, for a few seconds each. Connected sessions keep running, SCAN keeps working, new connections to the node being restarted fail for those seconds, and the instance re-registers on its own (the `sleep 60` gives it time).

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - grid -c "srvctl modify listener -listener LISTENER -endpoints 'TCP:1522/TCP:31522/TCP:31523'; srvctl config listener -listener LISTENER | grep 'End points'"
for n in racnode1-0 racnode2-0; do
  echo "=== restart LISTENER on $n"
  kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - grid -c "srvctl stop listener -listener LISTENER -node $n; srvctl start listener -listener LISTENER -node $n; srvctl status listener -listener LISTENER -node $n"
  sleep 10
done
sleep 60
for i in 1 2; do echo "=== racnode$i-0"; kubectl -n rac exec racnode$i-0 -c racnode$i-0 -- su - grid -c "lsnrctl status LISTENER | grep -E 'PROTOCOL=tcp|orclpdbsvc'"; done
for i in 1 2; do echo "=== ORCLCDB$i"; kubectl -n rac exec -i racnode$i-0 -c racnode$i-0 -- su - oracle -c "export ORACLE_SID=ORCLCDB$i; sqlplus -s / as sysdba" <<'EOF'
set lines 200 pages 50
col value for a110
select value from v$parameter where name = 'local_listener';
EOF
done
kubectl -n rac get racdatabase racdb
```

**Check:** `End points: TCP:1522,31522,31523`; the listener running on each node after its restart; three tcp lines per pod (its own pod IP, ports 1522, 31522, 31523) and `orclpdbsvc` registered again; `racdb` still `AVAILABLE`.

**This lab's output:**

```text
End points: TCP:1522,31522,31523
=== restart LISTENER on racnode1-0
Listener LISTENER is enabled on node(s): racnode1-0
Listener LISTENER is running on node(s): racnode1-0
=== restart LISTENER on racnode2-0
Listener LISTENER is enabled on node(s): racnode2-0
Listener LISTENER is running on node(s): racnode2-0

=== racnode1-0
  (DESCRIPTION=(ADDRESS=(PROTOCOL=tcp)(HOST=10.244.1.6)(PORT=31523)))
  (DESCRIPTION=(ADDRESS=(PROTOCOL=tcp)(HOST=10.244.1.6)(PORT=31522)))
  (DESCRIPTION=(ADDRESS=(PROTOCOL=tcp)(HOST=10.244.1.6)(PORT=1522)))
Service "orclpdbsvc" has 1 instance(s).
=== racnode2-0
  (DESCRIPTION=(ADDRESS=(PROTOCOL=tcp)(HOST=10.244.2.4)(PORT=31523)))
  (DESCRIPTION=(ADDRESS=(PROTOCOL=tcp)(HOST=10.244.2.4)(PORT=31522)))
  (DESCRIPTION=(ADDRESS=(PROTOCOL=tcp)(HOST=10.244.2.4)(PORT=1522)))
Service "orclpdbsvc" has 1 instance(s).
=== ORCLCDB1

VALUE
--------------------------------------------------------------------------------------------------------------
 (ADDRESS=(PROTOCOL=TCP)(HOST=10.244.1.6)(PORT=1522)), (ADDRESS=(PROTOCOL=TCP)(HOST=10.244.1.6)(PORT=31522)),
(ADDRESS=(PROTOCOL=TCP)(HOST=10.244.1.6)(PORT=31523))


=== ORCLCDB2

VALUE
--------------------------------------------------------------------------------------------------------------
 (ADDRESS=(PROTOCOL=TCP)(HOST=10.244.2.4)(PORT=1522)), (ADDRESS=(PROTOCOL=TCP)(HOST=10.244.2.4)(PORT=31522)),
(ADDRESS=(PROTOCOL=TCP)(HOST=10.244.2.4)(PORT=31523))


NAME    DBNAME    DBSTATE   ROLE      VERSION       PDB CONNECT STR                STATE
racdb   ORCLCDB   OPEN      PRIMARY   19.32.0.0.0   racnode-scan:1521/orclpdbsvc   AVAILABLE
```

**What the `local_listener` lines show:** Grid's agent rewrote each instance's `local_listener` by itself, from the pod IP and port 1522 to the pod IP with **all three** ports. The agent manages `local_listener` for a RAC database as long as it isn't set explicitly; it follows the listener's endpoints. The addresses are still pod IPs, which Windows can't reach, so 12.3 sets the parameter explicitly per instance.

### 12.3 Set `local_listener` explicitly, one value per instance

**What:** `ORCLCDB1` gets `racnode1-0-vip.rac.svc.cluster.local` port 31522 and `ORCLCDB2` gets `racnode2-0-vip.rac.svc.cluster.local` port 31523, with `scope=both` (now and in the spfile); `alter system register` makes each instance tell the SCAN listeners its new address at once.

**Why it works on both sides:** inside the pod each name resolves to the pod's own IP (the block checks this first and skips an instance if it doesn't), so the instance reaches its listener on that port. On Windows the same names point to 127.0.0.1 (`hosts`), and 12.4 forwards the ports. No session is interrupted and nothing restarts.

**The test logins:** `nobody/x` is a deliberately wrong login, so no password is involved. `ORA-01017: invalid username/password` can only come from an instance, so it proves the client got through SCAN **and** through the redirect; `ORA-12541` or `ORA-12545` would mean the redirect address doesn't work.

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
for i in 1 2; do
  h=racnode$i-0-vip.rac.svc.cluster.local; p=$((31521+i))
  echo "=== ORCLCDB$i -> $h:$p"
  kubectl -n rac exec racnode$i-0 -c racnode$i-0 -- getent hosts $h || { echo "STOP: $h does not resolve in racnode$i-0"; continue; }
  kubectl -n rac exec -i racnode$i-0 -c racnode$i-0 -- su - oracle -c "export ORACLE_SID=ORCLCDB$i; sqlplus -s / as sysdba" <<EOF
alter system set local_listener='(ADDRESS=(PROTOCOL=TCP)(HOST=$h)(PORT=$p))' scope=both sid='ORCLCDB$i';
alter system register;
EOF
done
sleep 30
kubectl -n rac exec -i racnode1-0 -c racnode1-0 -- su - oracle -c "export ORACLE_SID=ORCLCDB1; sqlplus -s / as sysdba" <<'EOF'
set lines 200 pages 50
col sid for a10
col value for a90
select inst_id, value from gv$parameter where name = 'local_listener' order by 1;
select sid, value from v$spparameter where name = 'local_listener';
EOF
for i in 1 2; do echo "=== LISTENER_SCAN$i"; kubectl -n rac exec racnode$i-0 -c racnode$i-0 -- su - grid -c "lsnrctl services LISTENER_SCAN$i" | awk '/Service "orclpdbsvc"/{f=1;print;next} /^Service "/{f=0} f && /Instance|ADDRESS/'; done
for t in 1 2 3 4; do kubectl -n rac exec racnode2-0 -c racnode2-0 -- su - oracle -c "echo exit | sqlplus -L -s nobody/x@//racnode-scan:1521/orclpdbsvc" | grep -E 'ORA-|SP2-'; done
kubectl -n rac get racdatabase racdb
```

**Check:** each name resolves to its pod's own IP; `System altered.` twice per instance; the new value for both instances in `gv$parameter` and stored per instance in `v$spparameter`; both SCAN listeners listing `ORCLCDB1` at `racnode1-0-vip…:31522` and `ORCLCDB2` at `racnode2-0-vip…:31523`; four `ORA-01017`; `racdb` still `AVAILABLE`.

**This lab's output:**

```text
=== ORCLCDB1 -> racnode1-0-vip.rac.svc.cluster.local:31522
10.244.1.6      racnode1-0-vip.rac.svc.cluster.local

System altered.


System altered.

=== ORCLCDB2 -> racnode2-0-vip.rac.svc.cluster.local:31523
10.244.2.4      racnode2-0-vip.rac.svc.cluster.local

System altered.


System altered.


   INST_ID VALUE
---------- ------------------------------------------------------------------------------------------
         1 (ADDRESS=(PROTOCOL=TCP)(HOST=racnode1-0-vip.rac.svc.cluster.local)(PORT=31522))
         2 (ADDRESS=(PROTOCOL=TCP)(HOST=racnode2-0-vip.rac.svc.cluster.local)(PORT=31523))


SID        VALUE
---------- ------------------------------------------------------------------------------------------
*          -oraagent-dummy-
ORCLCDB1   (ADDRESS=(PROTOCOL=TCP)(HOST=racnode1-0-vip.rac.svc.cluster.local)(PORT=31522))
ORCLCDB2   (ADDRESS=(PROTOCOL=TCP)(HOST=racnode2-0-vip.rac.svc.cluster.local)(PORT=31523))

=== LISTENER_SCAN1
Service "orclpdbsvc" has 2 instance(s).
  Instance "ORCLCDB1", status READY, has 1 handler(s) for this service...
         (ADDRESS=(PROTOCOL=TCP)(HOST=racnode1-0-vip.rac.svc.cluster.local)(PORT=31522))
  Instance "ORCLCDB2", status READY, has 1 handler(s) for this service...
         (ADDRESS=(PROTOCOL=TCP)(HOST=racnode2-0-vip.rac.svc.cluster.local)(PORT=31523))
=== LISTENER_SCAN2
Service "orclpdbsvc" has 2 instance(s).
  Instance "ORCLCDB1", status READY, has 1 handler(s) for this service...
         (ADDRESS=(PROTOCOL=TCP)(HOST=racnode1-0-vip.rac.svc.cluster.local)(PORT=31522))
  Instance "ORCLCDB2", status READY, has 1 handler(s) for this service...
         (ADDRESS=(PROTOCOL=TCP)(HOST=racnode2-0-vip.rac.svc.cluster.local)(PORT=31523))
ORA-01017: invalid username/password; logon denied
SP2-0751: Unable to connect to Oracle.  Exiting SQL*Plus
command terminated with exit code 1
ORA-01017: invalid username/password; logon denied
SP2-0751: Unable to connect to Oracle.  Exiting SQL*Plus
command terminated with exit code 1
ORA-01017: invalid username/password; logon denied
SP2-0751: Unable to connect to Oracle.  Exiting SQL*Plus
command terminated with exit code 1
ORA-01017: invalid username/password; logon denied
SP2-0751: Unable to connect to Oracle.  Exiting SQL*Plus
command terminated with exit code 1
NAME    DBNAME    DBSTATE   ROLE      VERSION       PDB CONNECT STR                STATE
racdb   ORCLCDB   OPEN      PRIMARY   19.32.0.0.0   racnode-scan:1521/orclpdbsvc   AVAILABLE
```

**The `-oraagent-dummy-` line:** that's the spfile entry for all instances (`*`), and the marker Grid's agent leaves when it manages `local_listener` itself. The new per-instance entries for `ORCLCDB1` and `ORCLCDB2` take precedence over it. 12.5 checks they survive a listener restart.

### 12.4 Open the ports: NodePort Services, then Windows forwards

**What:** two NodePort Services in namespace `rac`, `racnode1-0-lsnr-ext` (31522 → `racnode1-0`:31522) and `racnode2-0-lsnr-ext` (31523 → `racnode2-0`:31523), and three NAT forwards on `k8s-public`: 127.0.0.1:31521, 31522, 31523 → op-worker1 (10.0.1.21), same port.

**Why each part:**

- **Own Services for the node listeners:** the operator's `racnode-scan-lsnr` (31521) only covers SCAN. Each new Service selects one pod by its StatefulSet pod name, as the operator's own Services do.
- **Same number everywhere:** port, `targetPort` and `nodePort` are the number SCAN hands out (12.3), so the redirect works unchanged from Windows.
- **Own label:** `app: rac-ext-access` and none of the operator's labels, so the operator doesn't treat them as its own.
- **Forwards to op-worker1 only:** a NodePort answers on every node and passes the traffic on to the right pod. The rule names start with `op-ora-`, so they're easy to find and remove.

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
for i in 1 2; do p=$((31521+i)); cat <<EOF
---
apiVersion: v1
kind: Service
metadata:
  name: racnode$i-0-lsnr-ext
  namespace: rac
  labels: { app: rac-ext-access }
spec:
  type: NodePort
  selector: { statefulset.kubernetes.io/pod-name: racnode$i-0 }
  ports:
    - { name: lsnr, protocol: TCP, port: $p, targetPort: $p, nodePort: $p }
EOF
done | kubectl apply -f -
kubectl -n rac get svc racnode-scan-lsnr racnode1-0-lsnr-ext racnode2-0-lsnr-ext
kubectl -n rac get endpoints racnode-scan-lsnr racnode1-0-lsnr-ext racnode2-0-lsnr-ext
sleep 10
for h in 10.0.1.21 10.0.1.22; do for p in 31521 31522 31523; do timeout 3 bash -c "</dev/tcp/$h/$p" 2>/dev/null && echo "$h:$p open" || echo "$h:$p CLOSED"; done; done
echo "--- straight to the pods"
for a in 10.244.1.6:1521 10.244.1.6:31522 10.244.2.4:31523; do timeout 3 bash -c "</dev/tcp/${a%:*}/${a#*:}" 2>/dev/null && echo "$a open" || echo "$a CLOSED"; done
```

**Check:** two Services `created`; three NodePorts `1521:31521`, `31522:31522`, `31523:31523`; endpoints `10.244.1.6:1521`, `10.244.1.6:31522`, `10.244.2.4:31523`; all six NodePort lines and all three pod lines `open`.

**The first run tested too early.** It checked the ports in the same second the Services were created (age `0s`), before kube-proxy had set up the new NodePorts, and 31522 and 31523 were refused. Ten seconds later all were open, and kube-proxy showed no errors; the block above now waits (`sleep 10`) and also tests both workers and the pods directly. A refused connection, unlike a timeout, also rules out a firewall drop.

**This lab's output (the first run):**

```text
service/racnode1-0-lsnr-ext created
service/racnode2-0-lsnr-ext created
NAME                  TYPE       CLUSTER-IP       EXTERNAL-IP   PORT(S)           AGE
racnode-scan-lsnr     NodePort   10.99.59.33      <none>        1521:31521/TCP    25h
racnode1-0-lsnr-ext   NodePort   10.105.16.139    <none>        31522:31522/TCP   0s
racnode2-0-lsnr-ext   NodePort   10.109.147.162   <none>        31523:31523/TCP   0s
Warning: v1 Endpoints is deprecated in v1.33+; use discovery.k8s.io/v1 EndpointSlice
NAME                  ENDPOINTS          AGE
racnode-scan-lsnr     10.244.1.6:1521    25h
racnode1-0-lsnr-ext   10.244.1.6:31522   0s
racnode2-0-lsnr-ext   10.244.2.4:31523   0s
10.0.1.21:31521 open
bash: connect: Connection refused
bash: line 1: /dev/tcp/10.0.1.21/31522: Connection refused
10.0.1.21:31522 CLOSED
bash: connect: Connection refused
bash: line 1: /dev/tcp/10.0.1.21/31523: Connection refused
10.0.1.21:31523 CLOSED
```

**This lab's output (the check ten seconds later, with kube-proxy):**

```text
10.0.1.21:31521 open
10.0.1.21:31522 open
10.0.1.21:31523 open
10.0.1.22:31521 open
10.0.1.22:31522 open
10.0.1.22:31523 open
--- straight to the pods
10.244.1.6:1521 open
10.244.1.6:31522 open
10.244.2.4:31523 open
NAME               READY   STATUS    RESTARTS   AGE   IP          NODE              NOMINATED NODE   READINESS GATES
kube-proxy-7sbhj   1/1     Running   0          47h   10.0.1.20   op-controlplane   <none>           <none>
kube-proxy-hqvkq   1/1     Running   1          47h   10.0.1.22   op-worker2        <none>           <none>
kube-proxy-smrqj   1/1     Running   1          47h   10.0.1.21   op-worker1        <none>           <none>
no errors in the last kube-proxy log lines
```

(The kube-proxy lines came from `kubectl -n kube-system get pods -l k8s-app=kube-proxy -o wide` and `kubectl -n kube-system logs -l k8s-app=kube-proxy --tail=5 --prefix 2>&1 | grep -iE 'error|fail|31522|31523' || echo "no errors in the last kube-proxy log lines"`, run with the check.)

Then on Windows:

```powershell
# PowerShell on the Windows PC
$VB = "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
foreach ($p in 31521, 31522, 31523) {
  & $VB natnetwork modify --netname k8s-public --port-forward-4 "op-ora-$($p):tcp:[]:$($p):[10.0.1.21]:$($p)"
}
& $VB natnetwork list | Select-String 'Name:|op-ora-'
foreach ($p in 31521, 31522, 31523) { "127.0.0.1:$p  $(Test-NetConnection 127.0.0.1 -Port $p -InformationLevel Quiet -WarningAction SilentlyContinue)" }
```

**Check:** three `op-ora-…` rules to `[10.0.1.21]`, and `True` for all three ports. (If a port shows `False`, wait a few seconds and run the last line again.)

**This lab's output:**

```text
Name:         k8s-public
        op-ora-31521:tcp:[]:31521:[10.0.1.21]:31521
        op-ora-31522:tcp:[]:31522:[10.0.1.21]:31522
        op-ora-31523:tcp:[]:31523:[10.0.1.21]:31523

127.0.0.1:31521  True
127.0.0.1:31522  True
127.0.0.1:31523  True
```

### 12.5 Connect from Windows through SCAN

**What:** a small Python script opens 10 connections to `127.0.0.1:31521/orclpdbsvc` and prints, for each, which instance, host and container served it.

**Why it proves the whole path:** each connection goes Windows → forward 31521 → `LISTENER_SCAN1` → redirect to `racnode1-0-vip…:31522` or `racnode2-0-vip…:31523` → Windows `hosts` (127.0.0.1) → that forward → that instance's node listener. A line with an instance name has passed every step.

**The password:** asked at a hidden prompt (`getpass`); it isn't written to the file, the screen or the history. It's the database password from Phase 9, which DBCA used for SYS, SYSTEM and the PDB admin.

**Driver:** `python-oracledb` in thin mode needs no Oracle client. Thin mode has no TAF, so failover here means a **new** connection lands on the surviving instance (12.6), not a session that survives unchanged.

```powershell
# PowerShell on the Windows PC
@'
import collections, getpass, oracledb

DSN = "127.0.0.1:31521/orclpdbsvc"
SQL = """select sys_context('USERENV','INSTANCE_NAME'),
                sys_context('USERENV','SERVER_HOST'),
                sys_context('USERENV','CON_NAME') from dual"""

pw = getpass.getpass("SYSTEM password: ")
seen = collections.Counter()
for n in range(1, 11):
    with oracledb.connect(user="system", password=pw, dsn=DSN) as conn:
        with conn.cursor() as cur:
            cur.execute(SQL)
            inst, host, con = cur.fetchone()
    seen[inst] += 1
    print(f"{n:2}  {inst:9} {host:11} {con}")
print("oracledb", oracledb.__version__, "thin mode:", oracledb.is_thin_mode())
print("connections per instance:", dict(seen))
'@ | Set-Content -Encoding UTF8 D:\rac-k8s-poc-operator\scan_test.py
python D:\rac-k8s-poc-operator\scan_test.py
```

**Check:** ten lines with `ORCLCDB1  racnode1-0  ORCLPDB` or `ORCLCDB2  racnode2-0  ORCLPDB`, `thin mode: True`, and both instances in the count. (With the service goal `LONG`, SCAN sends each new connection to the less busy instance, so a run of ten may split unevenly.)

**If it fails, the error says where:** `DPY-6005` or a timeout at the start → the forward or NodePort on 31521; `DPY-6000` / `ORA-12514` → SCAN doesn't know the service; `DPY-6005` naming `racnodeN-0-vip` → the redirect (`hosts` entry or the forward on 31522 / 31523); `ORA-01017` → everything works except the password.

**This lab's output:**

```text
SYSTEM password:
 1  ORCLCDB2  racnode2-0  ORCLPDB
 2  ORCLCDB1  racnode1-0  ORCLPDB
 3  ORCLCDB2  racnode2-0  ORCLPDB
 4  ORCLCDB1  racnode1-0  ORCLPDB
 5  ORCLCDB2  racnode2-0  ORCLPDB
 6  ORCLCDB2  racnode2-0  ORCLPDB
 7  ORCLCDB1  racnode1-0  ORCLPDB
 8  ORCLCDB1  racnode1-0  ORCLPDB
 9  ORCLCDB2  racnode2-0  ORCLPDB
10  ORCLCDB1  racnode1-0  ORCLPDB
oracledb 26.0.1 thin mode: True
connections per instance: {'ORCLCDB2': 5, 'ORCLCDB1': 5}
```

### 12.6 Does it hold: listener restart, and new connections when one instance is out

**What, in three parts:**

- **a. (op-controlplane)** read the RAC pods' health probes; restart the node listeners again as in 12.2 and check that `local_listener` keeps the values from 12.3; take `orclpdbsvc` off ORCLCDB1.
- **b. (Windows)** run the test script: every connection should now land on ORCLCDB2.
- **c. (op-controlplane, then Windows)** put the service back on ORCLCDB1 and run the script again: both instances again.

**Why the service and not the whole instance:** for new connections, stopping the service on one instance has the effect of losing that instance (SCAN stops sending clients there), without touching the database. Part a also reads the pods' probes first, to know whether stopping an instance could make Kubernetes restart a pod.

**Interruption:** a few seconds per node for the listener restart (as in 12.2). Without `-force`, stopping the service on ORCLCDB1 leaves existing sessions there running; only new connections go to ORCLCDB2.

**a.**

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
for p in racnode1-0 racnode2-0; do echo "=== $p probes"; kubectl -n rac get pod $p -o jsonpath='{range .spec.containers[*]}{.name}{"\n"}  liveness:  {.livenessProbe}{"\n"}  readiness: {.readinessProbe}{"\n"}  startup:   {.startupProbe}{"\n"}{end}'; done
for n in racnode1-0 racnode2-0; do
  echo "=== restart LISTENER on $n"
  kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - grid -c "srvctl stop listener -listener LISTENER -node $n; srvctl start listener -listener LISTENER -node $n; srvctl status listener -listener LISTENER -node $n"
  sleep 10
done
sleep 60
kubectl -n rac exec -i racnode1-0 -c racnode1-0 -- su - oracle -c "export ORACLE_SID=ORCLCDB1; sqlplus -s / as sysdba" <<'EOF'
set lines 200 pages 50
col value for a90
select inst_id, value from gv$parameter where name = 'local_listener' order by 1;
EOF
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - oracle -c "srvctl stop service -d ORCLCDB -s orclpdbsvc -i ORCLCDB1; srvctl status service -d ORCLCDB -s orclpdbsvc"
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - grid -c "lsnrctl services LISTENER_SCAN1" | awk '/Service "orclpdbsvc"/{f=1;print;next} /^Service "/{f=0} f && /Instance|ADDRESS/'
```

**Check:** the probes printed; both listeners restarted; `local_listener` still `racnode1-0-vip…:31522` and `racnode2-0-vip…:31523`; `orclpdbsvc` running only on `ORCLCDB2`, and `LISTENER_SCAN1` listing only `Instance "ORCLCDB2"` for it.

**Run it on op-controlplane, not in Git Bash.** The first try of this block ran in Git Bash on the PC (the `$` prompt). There, plain `kubectl` uses the default kubeconfig, whose `127.0.0.1:6443` forward leads to another VM that wasn't running, so every call failed with `TLS handshake timeout` and nothing changed. Had that VM been running, the commands would have gone to the wrong cluster; from Git Bash only `kop` reaches this lab.

**This lab's output (the first try, in Git Bash; first lines):**

```text
$ # op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
…
=== racnode1-0 probes
E1028 22:34:18.848649   90392 memcache.go:265] couldn't get current server API group list: Get "https://127.0.0.1:6443/api?timeout=32s": net/http: TLS handshake timeout
…
Unable to connect to the server: net/http: TLS handshake timeout
```

**This lab's output (on op-controlplane):**

```text
=== racnode1-0 probes
racnode1-0
  liveness:
  readiness: {"failureThreshold":3,"initialDelaySeconds":180,"periodSeconds":5,"successThreshold":1,"tcpSocket":{"port":1522},"timeoutSeconds":1}
  startup:
=== racnode2-0 probes
racnode2-0
  liveness:
  readiness: {"failureThreshold":3,"initialDelaySeconds":180,"periodSeconds":5,"successThreshold":1,"tcpSocket":{"port":1522},"timeoutSeconds":1}
  startup:
=== restart LISTENER on racnode1-0
Listener LISTENER is enabled on node(s): racnode1-0
Listener LISTENER is running on node(s): racnode1-0
=== restart LISTENER on racnode2-0
Listener LISTENER is enabled on node(s): racnode2-0
Listener LISTENER is running on node(s): racnode2-0

   INST_ID VALUE
---------- ------------------------------------------------------------------------------------------
         1 (ADDRESS=(PROTOCOL=TCP)(HOST=racnode1-0-vip.rac.svc.cluster.local)(PORT=31522))
         2 (ADDRESS=(PROTOCOL=TCP)(HOST=racnode2-0-vip.rac.svc.cluster.local)(PORT=31523))

Service orclpdbsvc is running on instance(s) ORCLCDB2
Service "orclpdbsvc" has 1 instance(s).
  Instance "ORCLCDB2", status READY, has 1 handler(s) for this service...
         (ADDRESS=(PROTOCOL=TCP)(HOST=racnode2-0-vip.rac.svc.cluster.local)(PORT=31523))
```

**What a shows:**

- **`local_listener` survives a listener restart.** Unlike in 12.2, Grid's agent didn't rewrite it: an explicit per-instance value in the spfile is left alone.
- **The pods have only a readiness probe:** a TCP check of port 1522 every 5 s, failing after 3 misses (after a first 180 s). No liveness or startup probe, so Kubernetes never restarts a RAC pod because of a failed check; at most it marks it not ready. A stopped *instance* doesn't even do that, because the probe tests the node listener, not the database. A node listener down for longer than about 15 s does make its pod not ready, and Services may then stop sending traffic to it.

**b.**

```powershell
# PowerShell on the Windows PC
python D:\rac-k8s-poc-operator\scan_test.py
```

**Check:** all ten connections on `ORCLCDB2  racnode2-0`.

**This lab's output:**

```text
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

**c.**

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
kubectl -n rac exec racnode1-0 -c racnode1-0 -- su - oracle -c "srvctl start service -d ORCLCDB -s orclpdbsvc -i ORCLCDB1; srvctl status service -d ORCLCDB -s orclpdbsvc"
kubectl -n rac get racdatabase racdb
```

**Check:** the service on both instances again, `racdb` `AVAILABLE`.

**This lab's output:**

```text
Service orclpdbsvc is running on instance(s) ORCLCDB1,ORCLCDB2
NAME    DBNAME    DBSTATE   ROLE      VERSION       PDB CONNECT STR                STATE
racdb   ORCLCDB   OPEN      PRIMARY   19.32.0.0.0   racnode-scan:1521/orclpdbsvc   AVAILABLE
```

```powershell
# PowerShell on the Windows PC
python D:\rac-k8s-poc-operator\scan_test.py
```

**Check:** both instances in the count again.

**This lab's output:**

```text
SYSTEM password:
 1  ORCLCDB2  racnode2-0  ORCLPDB
 2  ORCLCDB1  racnode1-0  ORCLPDB
 3  ORCLCDB2  racnode2-0  ORCLPDB
 4  ORCLCDB1  racnode1-0  ORCLPDB
 5  ORCLCDB2  racnode2-0  ORCLPDB
 6  ORCLCDB1  racnode1-0  ORCLPDB
 7  ORCLCDB2  racnode2-0  ORCLPDB
 8  ORCLCDB1  racnode1-0  ORCLPDB
 9  ORCLCDB1  racnode1-0  ORCLPDB
10  ORCLCDB1  racnode1-0  ORCLPDB
oracledb 26.0.1 thin mode: True
connections per instance: {'ORCLCDB2': 4, 'ORCLCDB1': 6}
```

**Phase 12 result:** from Windows, `127.0.0.1:31521/orclpdbsvc` reaches both instances through SCAN, new connections go to the remaining instance when the service is off one of them, and the settings survive a listener restart. What was changed, for reference or to undo:

| Where | Change | Undo |
| --- | --- | --- |
| Grid (cluster-wide) | `LISTENER` endpoints `TCP:1522/TCP:31522/TCP:31523` | `srvctl modify listener -listener LISTENER -endpoints 'TCP:1522'`, then restart it per node |
| spfile, per instance | `local_listener` = `racnode1-0-vip…:31522` (ORCLCDB1), `racnode2-0-vip…:31523` (ORCLCDB2) | `alter system reset local_listener scope=spfile sid='ORCLCDB1';` (and `ORCLCDB2`); the agent sets it again at the next instance start |
| Kubernetes, namespace `rac` | Services `racnode1-0-lsnr-ext` (31522), `racnode2-0-lsnr-ext` (31523), label `app: rac-ext-access` | `kubectl -n rac delete svc -l app=rac-ext-access` |
| VirtualBox `k8s-public` | forwards `op-ora-31521`, `op-ora-31522`, `op-ora-31523` → 10.0.1.21 | `& $VB natnetwork modify --netname k8s-public --port-forward-4 delete op-ora-31521` (and the other two) |
| Windows | `D:\rac-k8s-poc-operator\scan_test.py`; the `hosts` lines were already there | delete the file; keep or remove the two `hosts` lines |
