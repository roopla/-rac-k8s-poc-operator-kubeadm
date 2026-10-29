## Next steps

After Phase 6 the operator lab is at the same point as the manual lab before its Phase 7, with three deliberate differences the operator asks for: the node directories `racnode1` / `racnode2` on both workers (4f), the worker label `raccluster=raccluster01` (5.4), and the Multus networks in namespace `rac` (6.3). The rest of the worker set-up (kernel settings, SELinux module, `allowedUnsafeSysctls`, hugepages, clock source) was already in the golden image and the kubeadm configuration.

The phases below follow Oracle's [Oracle Database Operator for Kubernetes](https://github.com/oracle/oracle-database-operator) (release v2.2.0, RAC controller `RacDatabase`, API `database.oracle.com/v4`). Phases 7 to 11 are above. Phase 11 is done: the database is open on both nodes (11.5), with the control file and redo fix in 11.6. Phase 12 (above) opened the database to Windows: SCAN at `127.0.0.1:31521/orclpdbsvc` reaches both instances.

| Phase | What | From the operator docs |
| --- | --- | --- |
| 12. Access from Windows (done) | extra node-listener ports, explicit `local_listener`, own NodePorts and Windows forwards, then a SCAN test from Python | `provisioning_oracle_rac_db_with_node_port.md`, `database_connection.md` |

**Open points:**

- **Which image (settled).** The manual lab's image can't be reused: it was built from the OCNE doc's short Containerfile, and the operator drives the setup through the scripts in Oracle's own RAC image (it follows `/tmp/orod/oracle_db_setup.log`). Oracle doesn't publish the slim image on its registry, so Phase 8 builds it on each worker with `buildContainerImage.sh -v 19.3.0 -i -o '--build-arg SLIMMING=true'` (Oracle Linux 9 base).
- **Sizing (settled in 11.1).** 16 GiB pods with 4 GiB of hugepages fit once the operator runs one controller pod instead of three; the `RAC_WEBHOOK_DEV_MODE` way around the 16 GiB minimum isn't needed.
- **Platform.** The operator's README lists OKE, OpenShift and OLCNE 1.9+ as tested, and GKE, AKS, EKS, OKD and Minikube as supported. That table covers the whole operator; the RAC controller's own prerequisites are written only for OCNE. A plain kubeadm cluster with CRI-O isn't on either list, so expect lab-specific workarounds, as in the manual lab. One showed up so far: the ASM discovery string with by-id disk names (`CRS_ASM_DISCOVERY_STRING` in 11.2, recovery in 11.4).
- **Online redo logs land in FRA.** With no `DBREDO` disk group in the YAML, the setup script sets `DB_CREATE_ONLINE_LOG_DEST_1` to the recovery disk group, so the redo logs are only in `+FRA` (one member per group). That works for the lab; the usual layout keeps redo on DATA or its own disk group with a second member in FRA. The control file too ended up only in `+FRA` (11.5). 11.6 adds a second copy of each in `+DATA`. `db_recovery_file_dest_size` isn't set by the operator; DBCA chose 23895M.
- **Access from outside is set up by hand (Phase 12).** The operator's own node-listener NodePort fields (`baseLsnrTargetPort`) only apply when the database is first created. A new build should set them in the YAML instead (not tested here). An instance-down test (`srvctl stop instance`) wasn't run; the pods have no liveness probe, so it wouldn't restart a pod.
- **VIPs are the pod IPs.** Flannel gives each pod one IP, so `racnode1-0-vip` and `racnode2-0-vip` resolve to the pods' own addresses. A VIP can't move to the other node when its pod dies; client failover relies on SCAN and the service running on the other instance.
