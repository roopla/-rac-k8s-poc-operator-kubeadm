## Phase 7: Install Oracle's database operator

**Result of this phase:** cert-manager and the Oracle Database Operator running in the cluster, watching namespace `rac`, with the extra permissions the RAC controller needs: reading nodes and the Multus networks, and creating the ASM PersistentVolumes itself.

**What the operator is:** a controller that runs in its own namespace, `oracle-database-operator-system`. It adds new object types to Kubernetes, `RacDatabase` among them. When you later apply one `RacDatabase` YAML, the operator creates everything the manual lab built by hand in its Phases 7–12: the PVs, the headless Services, the StatefulSets, the Grid and database installs and the database.

### 7.1 Get the operator's manifests (op-controlplane)

**Why a copy of the repository:** the install files are generated for the namespaces the operator should watch, and the RAC permission files live in the repository. The lab used the version current on 26 Oct 2026 (release v2.2.0). The block prints the exact commit, so you can note it.

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
command -v git >/dev/null || dnf install -y -q git
rm -rf /root/oraop && git clone -q --depth 1 https://github.com/oracle/oracle-database-operator.git /root/oraop
cd /root/oraop && git log -1 --format='commit %h, %cd'
ls oracle-database-operator-rbac.yaml oracle-database-operator-system.yaml scripts/generate-namespace-install.sh rbac docs/rac/rbac
```

**Check:** a commit line, and the files and two `rbac` folders listed without errors.

### 7.2 cert-manager (op-controlplane)

**Why:** the operator checks every `RacDatabase` you apply through a webhook, and Kubernetes only talks to webhooks over TLS. cert-manager issues and renews that certificate. The version is the one the operator's README names.

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.20.2/cert-manager.yaml
kubectl -n cert-manager rollout status deploy/cert-manager deploy/cert-manager-webhook deploy/cert-manager-cainjector --timeout=300s
kubectl -n cert-manager get pods
```

**Check:** three `successfully rolled out` lines, and three cert-manager pods `Running` with `1/1`.

**This lab's output:**

```text
namespace/cert-manager created
customresourcedefinition.apiextensions.k8s.io/challenges.acme.cert-manager.io created
…                                   (about 45 more "created" lines)
deployment.apps/cert-manager-webhook created
mutatingwebhookconfiguration.admissionregistration.k8s.io/cert-manager-webhook created
validatingwebhookconfiguration.admissionregistration.k8s.io/cert-manager-webhook created
Waiting for deployment "cert-manager" rollout to finish: 0 out of 1 new replicas have been updated...
deployment "cert-manager" successfully rolled out
deployment "cert-manager-webhook" successfully rolled out
deployment "cert-manager-cainjector" successfully rolled out
NAME                                       READY   STATUS    RESTARTS   AGE
cert-manager-69c7fcbf78-vv5dd              1/1     Running   0          48s
cert-manager-cainjector-69f8c8cdbf-ptnn2   1/1     Running   0          48s
cert-manager-webhook-84fd89df64-bkjmm      1/1     Running   0          48s
```

### 7.3 The operator, watching namespace rac (op-controlplane)

**Why namespace-scoped:** the operator's recommended mode. It only acts in the namespaces it's told to watch, here its own and `rac`, where the Multus networks from 6.3 already are. The script writes the matching RBAC and sets `WATCH_NAMESPACE`, so the two can't disagree.

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
cd /root/oraop
scripts/generate-namespace-install.sh oracle-database-operator-system,rac
kubectl apply -f dist/install/oracle-database-operator-rbac.yaml
kubectl apply -f dist/install/oracle-database-operator-system.yaml
kubectl -n oracle-database-operator-system rollout status deploy/oracle-database-operator-controller-manager --timeout=600s
kubectl -n oracle-database-operator-system get pods -o wide
kubectl -n oracle-database-operator-system get deploy oracle-database-operator-controller-manager -o jsonpath='{range .spec.template.spec.containers[0].env[?(@.name=="WATCH_NAMESPACE")]}{.name}={.value}{"\n"}{end}'
```

**Check:**

- `successfully rolled out`, and the controller-manager pods `Running`;
- `WATCH_NAMESPACE=oracle-database-operator-system,rac`.

The first start pulls the operator image from `container-registry.oracle.com`, which can take a few minutes. If a pod stays in `ErrImagePull`, run `kubectl -n oracle-database-operator-system describe pod -l control-plane=controller-manager | tail -20` and paste the events.

**This lab's output:**

```text
Generated namespace-scoped install manifests:
  /root/oraop/dist/install/oracle-database-operator-rbac.yaml
  /root/oraop/dist/install/oracle-database-operator-system.yaml

WATCH_NAMESPACE=oracle-database-operator-system,rac
Operator namespace=oracle-database-operator-system
…
namespace/oracle-database-operator-system created
serviceaccount/oracle-database-operator-controller-manager created
…
customresourcedefinition.apiextensions.k8s.io/racdatabases.database.oracle.com created
…
deployment.apps/oracle-database-operator-controller-manager created
Waiting for deployment "oracle-database-operator-controller-manager" rollout to finish: 0 out of 3 new replicas have been updated...
…
deployment "oracle-database-operator-controller-manager" successfully rolled out
NAME                                                           READY   STATUS    RESTARTS   AGE    IP           NODE
oracle-database-operator-controller-manager-54cf89dd45-9rjws   1/1     Running   0          101s   10.244.2.4   op-worker2
oracle-database-operator-controller-manager-54cf89dd45-f644n   1/1     Running   0          101s   10.244.1.5   op-worker1
oracle-database-operator-controller-manager-54cf89dd45-xl646   1/1     Running   0          101s   10.244.2.5   op-worker2
WATCH_NAMESPACE=oracle-database-operator-system,rac
```

### 7.4 The RAC controller's extra permissions (op-controlplane)

**Why:** the namespace-scoped install can only touch objects inside the watched namespaces. The RAC controller also needs a few cluster-wide ones:

| File | Lets the operator | Needed because |
| --- | --- | --- |
| `rbac/node-rbac.yaml` | read nodes | it picks workers by the `raccluster` label and builds NodePort connect strings |
| `rbac/persistent-volume-rbac.yaml` | read PersistentVolumes | it checks the ASM PVs |
| `docs/rac/rbac/pv-rbac.yaml` | create and delete PersistentVolumes | it creates the ASM PVs from the disk paths you list |
| `docs/rac/rbac/multus-rbac.yaml` | read NetworkAttachmentDefinitions | it attaches `macvlan-conf1` / `macvlan-conf2` to the RAC pods |

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
cd /root/oraop
kubectl apply -f rbac/node-rbac.yaml -f rbac/persistent-volume-rbac.yaml -f docs/rac/rbac/pv-rbac.yaml -f docs/rac/rbac/multus-rbac.yaml
SA=system:serviceaccount:oracle-database-operator-system:oracle-database-operator-controller-manager
for c in "list nodes" "create persistentvolumes" "delete persistentvolumes" "list network-attachment-definitions.k8s.cni.cncf.io -n rac" "create statefulsets.apps -n rac" "create racdatabases.database.oracle.com -n rac"; do
  printf '%-62s %s\n' "$c" "$(kubectl auth can-i $c --as=$SA)"
done
kubectl get crd racdatabases.database.oracle.com
```

**Check:** every line ends in `yes`, and the `racdatabases.database.oracle.com` CRD is listed. A `no` names the permission that's missing; paste the output.

**This lab's output:**

```text
clusterrole.rbac.authorization.k8s.io/oracle-database-operator-manager-role-node created
clusterrolebinding.rbac.authorization.k8s.io/oracle-database-operator-manager-role-node-cluster-role-binding created
clusterrole.rbac.authorization.k8s.io/oracle-database-operator-manager-role-persistent-volume created
clusterrolebinding.rbac.authorization.k8s.io/oracle-database-operator-manager-role-persistent-volume-cluster-role-binding created
clusterrole.rbac.authorization.k8s.io/oracle-operator-pv-role created
clusterrolebinding.rbac.authorization.k8s.io/oracle-operator-pv-rolebinding created
clusterrole.rbac.authorization.k8s.io/oracle-operator-multus-nad-role created
clusterrolebinding.rbac.authorization.k8s.io/oracle-operator-multus-nad-rolebinding created
Warning: resource 'nodes' is not namespace scoped
list nodes                                                     yes
Warning: resource 'persistentvolumes' is not namespace scoped
create persistentvolumes                                       yes
Warning: resource 'persistentvolumes' is not namespace scoped
delete persistentvolumes                                       yes
list network-attachment-definitions.k8s.cni.cncf.io -n rac     yes
create statefulsets.apps -n rac                                yes
create racdatabases.database.oracle.com -n rac                 yes
NAME                               CREATED AT
racdatabases.database.oracle.com   2026-10-27T12:06:53Z
```

The `Warning: resource '…' is not namespace scoped` lines are normal: `kubectl auth can-i` notes that nodes and PersistentVolumes are cluster-wide objects.
