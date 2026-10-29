## Phase 6: Multus and the RAC private networks

**Result of this phase:** pods can have two extra interfaces, `eth1` on 10.0.11.0/24 and `eth2` on 10.0.12.0/24, with addresses you choose. A test between the workers proves the interconnect works before any Oracle software is involved.

### 6.1 Why RAC needs Multus

A Kubernetes pod normally has exactly one network interface, `eth0`, from the cluster network (Flannel here). RAC needs more than that:

- **A public network:** client connections, the VIPs and SCAN. That's `eth0`.
- **A private interconnect:** dedicated, low-latency and not routed through the cluster network. Cache Fusion moves database blocks between the instances over it, and the cluster heartbeat runs on it. If the heartbeat is lost, Grid evicts a node.

**Multus** is a "meta" CNI plugin that attaches additional networks to a pod. Each extra network is described by a **NetworkAttachmentDefinition** (NAD). This lab uses `macvlan`, which gives the pod its own MAC address directly on the worker's `enp0s8` / `enp0s9`. Two networks give Grid's **HAIP** (highly available IP) two paths, so the interconnect survives losing one.

### 6.2 Install Multus (op-controlplane)

The thick-plugin variant runs a small daemon on every node. The URL follows Multus's main branch, as it did in the lab on 23 Oct 2026. For a repeatable build you can replace `master` with a release tag.

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
kubectl apply -f https://raw.githubusercontent.com/k8snetworkplumbingwg/multus-cni/master/deployments/multus-daemonset-thick.yml
kubectl -n kube-system rollout status ds/kube-multus-ds --timeout=300s
```

**Check:** `daemon set "kube-multus-ds" successfully rolled out`.

**This lab's output:**

```text
customresourcedefinition.apiextensions.k8s.io/network-attachment-definitions.k8s.cni.cncf.io created
clusterrole.rbac.authorization.k8s.io/multus created
clusterrolebinding.rbac.authorization.k8s.io/multus created
serviceaccount/multus created
configmap/multus-daemon-config created
daemonset.apps/kube-multus-ds created
Waiting for daemon set "kube-multus-ds" rollout to finish: 0 of 3 updated pods are available...
Waiting for daemon set "kube-multus-ds" rollout to finish: 1 of 3 updated pods are available...
daemon set "kube-multus-ds" successfully rolled out
```

### 6.3 The two RAC networks (op-controlplane)

**Why each setting:**

- **Namespace `rac`:** the operator looks the NADs up in the same namespace as the RAC database it creates, and its samples use `rac`. The manual lab used a separate `multus-rac` namespace; this is the one difference from it.
- **Names `macvlan-conf1` / `macvlan-conf2`:** the names the operator's `privateIPDetails` will refer to.
- **`master: enp0s8` / `enp0s9`:** the worker NICs prepared in Phase 4. The doc uses `ens5` / `ens6`, its own NIC names.
- **`mode: bridge`:** pods on the same parent NIC can reach each other.
- **`host-local` IPAM with a range of 140–150:** the doc's subnets and ranges.
- **`"capabilities": {"ips": true}`:** lets each pod request a **specific** address (10.0.11.141 for racnode1-0, .142 for racnode2-0). Without it, `host-local` ignores the request and picks addresses per node on its own, so both workers can hand out the same IP. The doc's NADs don't have this line; this is a delta.

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
kubectl create namespace rac
cat <<'EOF' | kubectl apply -f -
apiVersion: k8s.cni.cncf.io/v1
kind: NetworkAttachmentDefinition
metadata:
  name: macvlan-conf1
  namespace: rac
spec:
  config: '{ "cniVersion": "0.3.1", "type": "macvlan", "master": "enp0s8", "mode": "bridge",
    "capabilities": { "ips": true },
    "ipam": { "type": "host-local", "subnet": "10.0.11.0/24", "rangeStart": "10.0.11.140", "rangeEnd": "10.0.11.150" } }'
---
apiVersion: k8s.cni.cncf.io/v1
kind: NetworkAttachmentDefinition
metadata:
  name: macvlan-conf2
  namespace: rac
spec:
  config: '{ "cniVersion": "0.3.1", "type": "macvlan", "master": "enp0s9", "mode": "bridge",
    "capabilities": { "ips": true },
    "ipam": { "type": "host-local", "subnet": "10.0.12.0/24", "rangeStart": "10.0.12.140", "rangeEnd": "10.0.12.150" } }'
EOF
kubectl -n rac get network-attachment-definitions
```

**This lab's output:**

```text
namespace/rac created
networkattachmentdefinition.k8s.cni.cncf.io/macvlan-conf1 created
networkattachmentdefinition.k8s.cni.cncf.io/macvlan-conf2 created
NAME            AGE
macvlan-conf1   0s
macvlan-conf2   0s
```

### 6.4 Prove the interconnect (op-controlplane)

**What:** one throwaway pod on each worker, each with `eth1` and `eth2` at chosen addresses. Then pings across.

**Why now:** if the private network doesn't work, Grid's installer fails much later with a far less obvious error. In the first build, this test is what exposed the promiscuous-mode problem. `NET_RAW` is added because CRI-O drops it by default and `ping` needs it.

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
for n in 1 2; do o=$((147+n)); cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: nettest-w$n
  namespace: rac
  annotations:
    k8s.v1.cni.cncf.io/networks: '[{"name":"macvlan-conf1","interface":"eth1","ips":["10.0.11.$o/24"]},{"name":"macvlan-conf2","interface":"eth2","ips":["10.0.12.$o/24"]}]'
spec:
  nodeSelector: { kubernetes.io/hostname: op-worker$n }
  containers:
  - name: net
    image: docker.io/library/busybox:1.36
    command: ["sleep", "infinity"]
    securityContext: { capabilities: { add: ["NET_RAW"] } }
EOF
done
kubectl -n rac wait --for=condition=Ready pod/nettest-w1 pod/nettest-w2 --timeout=300s
kubectl -n rac exec nettest-w1 -- ip -4 addr
kubectl -n rac exec nettest-w1 -- ping -c3 10.0.11.149
kubectl -n rac exec nettest-w1 -- ping -c3 10.0.12.149
kubectl -n rac exec nettest-w2 -- ping -c3 10.0.11.148
kubectl -n rac exec nettest-w2 -- ping -c3 10.0.12.148
```

**Check:**

- `nettest-w1` has `eth1` 10.0.11.148/24 and `eth2` 10.0.12.148/24;
- all four pings get 0% packet loss.

If you get 100% loss, check that `enp0s8` / `enp0s9` show `PROMISC` on both workers (Phase 4, step c on each worker), and that 3.2's check showed `Promisc Policy: allow-all` for both workers.

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
kubectl -n rac delete pod nettest-w1 nettest-w2
```

**This lab's output:**

```text
pod/nettest-w1 created
pod/nettest-w2 created
pod/nettest-w1 condition met
pod/nettest-w2 condition met
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue qlen 1000
    inet 127.0.0.1/8 scope host lo
2: eth0@if7: <BROADCAST,MULTICAST,UP,LOWER_UP,M-DOWN> mtu 1450 qdisc noqueue qlen 1000
    inet 10.244.1.2/24 brd 10.244.1.255 scope global eth0
3: eth1@eth1: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue qlen 1000
    inet 10.0.11.148/24 brd 10.0.11.255 scope global eth1
4: eth2@eth2: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc noqueue qlen 1000
    inet 10.0.12.148/24 brd 10.0.12.255 scope global eth2
PING 10.0.11.149 (10.0.11.149): 56 data bytes
64 bytes from 10.0.11.149: seq=0 ttl=64 time=0.855 ms
…
3 packets transmitted, 3 packets received, 0% packet loss
PING 10.0.12.149 (10.0.12.149): 56 data bytes
…
3 packets transmitted, 3 packets received, 0% packet loss
PING 10.0.11.148 (10.0.11.148): 56 data bytes
…
3 packets transmitted, 3 packets received, 0% packet loss
PING 10.0.12.148 (10.0.12.148): 56 data bytes
…
3 packets transmitted, 3 packets received, 0% packet loss
pod "nettest-w1" deleted from rac namespace
pod "nettest-w2" deleted from rac namespace
```
