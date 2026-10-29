## Phase 5: Kubernetes with kubeadm and Flannel

**Result of this phase:** a 3-node Kubernetes v1.36 cluster `rac-op`: the op-controlplane plus op-worker1 and op-worker2, all `Ready`, with Flannel as the pod network, and both workers labelled for the operator.

### 5.1 The kubeadm configuration (op-controlplane)

Blocks labelled `# op-controlplane` run in a root shell on the op-controlplane. From here on, keep one PowerShell window connected to it:

```powershell
# PowerShell
ssh -p 2220 root@127.0.0.1
```

**Check:** the prompt says `[root@op-controlplane ~]#`. The same goes for `# op-worker1` (port 2221) and `# op-worker2` (port 2222) when a block needs them.

**Why each part:**

- **`advertiseAddress` / `controlPlaneEndpoint` 10.0.1.20:** the API server listens on the public network, not on any other NIC.
- **`criSocket` CRI-O:** the runtime chosen in Phase 2.
- **`podSubnet` 10.244.0.0/16:** Flannel's default. The doc's Grid response file names `eth0:10.244.0.0` as the public network inside the pods, so this range has to match.
- **`dnsDomain` cluster.local:** the SCAN name becomes `racnode-scan.rac.svc.cluster.local`.
- **`allowedUnsafeSysctls`:** the RAC pods set `kernel.shmall`, `kernel.shmmax`, `kernel.shmmni`, `kernel.sem` and some `net.*` settings for themselves. Kubernetes calls these "unsafe" and the kubelet rejects any pod that sets them, unless they're allowed here. These settings are namespaced: they affect only that pod, not the node. The OCNE doc sets this as a kubelet flag; with kubeadm it belongs in the `KubeletConfiguration`, which every node picks up when it joins.

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
cat >/root/kubeadm-config.yaml <<'EOF'
apiVersion: kubeadm.k8s.io/v1beta4
kind: InitConfiguration
localAPIEndpoint:
  advertiseAddress: 10.0.1.20
  bindPort: 6443
nodeRegistration:
  name: op-controlplane
  criSocket: unix:///var/run/crio/crio.sock
---
apiVersion: kubeadm.k8s.io/v1beta4
kind: ClusterConfiguration
clusterName: rac-op
controlPlaneEndpoint: 10.0.1.20:6443
networking:
  podSubnet: 10.244.0.0/16
  serviceSubnet: 10.96.0.0/12
  dnsDomain: cluster.local
---
apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration
cgroupDriver: systemd
allowedUnsafeSysctls:
  - "kernel.shm*"
  - "kernel.sem"
  - "net.*"
EOF
```

### 5.2 Initialise the control plane (op-controlplane)

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
kubeadm init --config /root/kubeadm-config.yaml
mkdir -p ~/.kube && cp -f /etc/kubernetes/admin.conf ~/.kube/config
kubectl get nodes
```

**Check:** `Your Kubernetes control-plane has initialized successfully!`. The op-controlplane shows `NotReady` until there's a pod network in 5.3, which is expected.

### 5.3 Flannel, the pod network (op-controlplane)

**What:** Flannel gives every pod an `eth0` address in 10.244.0.0/16, and routes pod traffic between nodes over the 10.0.1.x network.

**Why:** Kubernetes needs a CNI network before any pod can start. In the RAC pods, `eth0` is the **public** network: the node names, VIPs and SCAN all resolve to `eth0` addresses.

This URL always fetches the newest Flannel release. The lab used the release current on 23 Oct 2026. If a newer one misbehaves, pick a specific version from Flannel's releases page instead of `latest`.

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
kubectl apply -f https://github.com/flannel-io/flannel/releases/latest/download/kube-flannel.yml
kubectl -n kube-flannel rollout status ds/kube-flannel-ds
kubectl get nodes
```

**Check:** the op-controlplane turns `Ready` within a minute.

### 5.4 Join the workers

**What:** a join command with a fresh token, run on each worker. The PC fetches it from the op-controlplane and runs it on both workers, so there's nothing to copy by hand. The token in it expires after 24 hours.

```powershell
# PowerShell
$join = ssh -p 2220 root@127.0.0.1 "kubeadm token create --print-join-command"; $join
ssh -p 2221 root@127.0.0.1 $join
ssh -p 2222 root@127.0.0.1 $join
```

Each worker ends with `This node has joined the cluster`.

Back on the op-controlplane, label the workers and wait for them. The second label, `raccluster=raccluster01`, is the operator's: its `workerNodeSelector` places RAC pods only on nodes with this label.

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
kubectl label node op-worker1 op-worker2 node-role.kubernetes.io/worker= --overwrite
kubectl label node op-worker1 op-worker2 raccluster=raccluster01 --overwrite
kubectl wait --for=condition=Ready node --all --timeout=600s
kubectl get nodes -o wide
kubectl get pods -A
```

**Check:**

- three nodes, all `Ready` and on `v1.36.x`, with INTERNAL-IP 10.0.1.20, .21 and .22;
- every system pod `Running`: coredns, etcd, kube-apiserver, kube-proxy, kube-flannel;
- `kubectl get nodes -l raccluster=raccluster01` lists op-worker1 and op-worker2.

If a worker shows the wrong INTERNAL-IP, the `--node-ip` setting from Phase 4 is missing.

### 5.5 kubectl from your PC (optional)

**Why:** so you can run `kubectl` from Git Bash on Windows without SSH-ing into op-controlplane first. The manual lab may already use `~/.kube/config` and host port 6443, so the operator lab gets **its own file**, `~/.kube/config-op`, and **its own port, 6444**. The two never overwrite each other.

```powershell
# PowerShell
& "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe" natnetwork modify --netname k8s-public --port-forward-4 "k8sapi-op:tcp:[]:6444:[10.0.1.20]:6443"
```

```bash
# Git Bash
mkdir -p ~/.kube
scp -P 2220 root@127.0.0.1:/etc/kubernetes/admin.conf ~/.kube/config-op
kubectl --kubeconfig "$(cygpath -m ~/.kube/config-op)" config set-cluster rac-op --server=https://127.0.0.1:6444 --tls-server-name=kubernetes
sed -i '/alias kop=/d' ~/.bashrc
echo "alias kop='kubectl --kubeconfig \"\$(cygpath -m ~/.kube/config-op)\"'" >> ~/.bashrc
grep -q MSYS_NO_PATHCONV ~/.bashrc || echo 'export MSYS_NO_PATHCONV=1' >> ~/.bashrc
source ~/.bashrc
kop get nodes
```

**Why each line:**

- **`k8sapi-op` on 6444:** the manual lab's forward uses host port 6443. A second rule can't use the same host port, so the operator lab's API server is reached on 6444; inside the lab it still listens on 6443.
- **`--kubeconfig ~/.kube/config-op`:** keeps the operator lab's credentials apart from the manual lab's `~/.kube/config`.
- **`set-cluster rac-op`:** kubeadm names the cluster entry after `clusterName` (`rac-op`), so that's the entry to point at 127.0.0.1:6444.
- **`--tls-server-name=kubernetes`:** the API server's certificate is for `kubernetes` and 10.0.1.20, not 127.0.0.1; this keeps certificate checking on.
- **`kop`:** short for `kubectl --kubeconfig C:/Users/<you>/.kube/config-op`. Use `kop` for the operator lab and plain `kubectl` for the manual lab. `cygpath -m` turns the Git Bash path into a Windows one, because `kubectl.exe` is a Windows program and `MSYS_NO_PATHCONV=1` stops Git Bash from converting `/c/Users/...` for it. Without that, kubectl can't find the file and falls back to `localhost:8080`.

**Check:** `kop get nodes` lists `op-controlplane`, `op-worker1` and `op-worker2`. `admin.conf` gives full control of the cluster; keep it out of anything you share.

**This lab's output:**

```text
admin.conf                                             100% 5617     8.8KB/s   00:00
Cluster "rac-op" set.
kop is aliased to `kubectl --kubeconfig "$(cygpath -m ~/.kube/config-op)"'
    server: https://127.0.0.1:6444
    tls-server-name: kubernetes
NAME              STATUS   ROLES           AGE     VERSION
op-controlplane   Ready    control-plane   9m54s   v1.36.5
op-worker1        Ready    worker          8m33s   v1.36.5
op-worker2        Ready    worker          8m25s   v1.36.5
```

**This lab's output (the first version of the alias, without cygpath -m: kubectl couldn't find the file and fell back to localhost:8080; it also wrote a stray D:\c\Users\alpoo\.kube\config-op, which was deleted):**

```text
E1026 23:07:45 … couldn't get current server API group list: Get "http://localhost:8080/api?timeout=32s": dial tcp [::1]:8080: connectex: No connection could be made …
Unable to connect to the server: dial tcp [::1]:8080: …
```

**The same in PowerShell:** a `kop` function in your PowerShell profile. PowerShell passes Windows paths, so no conversion is needed.

```powershell
# PowerShell
if (-not (Test-Path $PROFILE)) { New-Item -ItemType File -Force -Path $PROFILE | Out-Null }
if (-not (Select-String -Path $PROFILE -Pattern 'function kop' -Quiet)) {
  Add-Content -Path $PROFILE -Value 'function kop { kubectl --kubeconfig "$env:USERPROFILE\.kube\config-op" @args }'
}
. $PROFILE
kop get nodes
```

**Check:** the three `op-*` nodes. If `. $PROFILE` says running scripts is disabled, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and try again. For a whole session on one lab, `$env:KUBECONFIG = "$env:USERPROFILE\.kube\config-op"` points plain `kubectl` at the operator lab until the window closes.

**This lab's output:**

```text
NAME              STATUS   ROLES           AGE   VERSION
op-controlplane   Ready    control-plane   12m   v1.36.5
op-worker1        Ready    worker          11m   v1.36.5
op-worker2        Ready    worker          11m   v1.36.5
```
