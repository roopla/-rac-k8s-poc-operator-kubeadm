## Phase 4: Personalize each node

**Result of this phase:** each node has its own name and IP address. The workers also have their private NICs ready for Multus, `/scratch` and `/var/lib/containers` on their own disks, the operator's directories, and 4 GB of hugepages.

**Do one node at a time, in the order op-controlplane, op-worker1, op-worker2.** Every clone boots with the golden VM's address 10.0.1.5, and two clones running at once would fight over it. Each node has its own section below with every command written out for it: copy the blocks in order, without changing anything. Start the next node only after the previous one passes its last check.

### 4.1 What happens to each node, and why

| Step | op-controlplane | op-worker1, op-worker2 |
| --- | --- | --- |
| a. Start and connect on 2205 | yes | yes |
| b. Name, identity, kubelet IP | yes | yes |
| c. Private NICs for Multus | no: it has no NIC2/NIC3 | yes |
| d, e. Data disks `/var/lib/containers` and `/scratch` | no: it has only the OS disk | yes |
| f. The operator's directories | no | yes (the same on both workers) |
| g. HugePages | no: 2048 pages would lock all of its 4 GB | yes |
| Move to its own address, then check it | yes | yes |

**Why each step:**

- **Name, identity and kubelet IP:** the host name becomes the Kubernetes node name. New SSH host keys replace the ones the seal removed. `--node-ip` matters on the workers, which have three NICs: without it the kubelet may advertise the wrong address, and pod traffic between nodes breaks.
- **Private NICs with no IP:** `enp0s8` and `enp0s9` are only "parents" for Multus macvlan interfaces. Each RAC pod gets its own interface, IP (10.0.11.x and 10.0.12.x) and MAC address on top of them.
- **Promiscuous mode (`accept-all-mac-addresses yes`):** this was the cause of the hardest network failure in the first build, 100% packet loss between pods. VirtualBox's "Allow All" setting only takes effect when the guest NIC itself is promiscuous. Otherwise the virtual NIC silently drops frames addressed to the pods' macvlan MACs.
- **Data disks chosen by size, not by name:** Linux disk names (`sdb`, `sdc`...) do **not** follow VirtualBox port order. On worker2 in the manual lab's first build, `/dev/sdc` was a shared ASM disk, and formatting by name would have wiped the disk both nodes share. The ASM disks are 50 GB, so the sizes tell the disks apart. They're **mounted by UUID** for the same reason, and **`rsync -aAXH`** copies the images pulled in Phase 2 together with their SELinux labels.
- **The operator's directories with `container_file_t`:** the operator mounts them into the RAC pods as hostPath volumes; their names follow its `racHostSwLocation` (`/scratch/rac/cluster01`) and `racNodeName` (`racnode`) settings. With SELinux enforcing, a container can only use host files with the container file label. `semanage fcontext` makes the label permanent.
- **HugePages:** the database SGA goes into 2 MB hugepages, which are locked, never swapped and cheaper for the CPU to map. Kubernetes only gives hugepages to pods on nodes that reserved them: the RAC pods ask for `hugepages-2Mi: 4Gi`, so each worker reserves 2048 pages. The doc reserves 16384 (32 GB); this lab scales it to the 22 GB workers.
- **Moving the address last, in the background:** changing the public IP cuts the SSH session you're typing in. A first attempt died halfway through for exactly that reason. So the change runs detached from your session and ends with a reboot.
- **`ssh-keygen -R` before connecting:** every clone has its own host key but answers on the same port, 2205. Without the 0.2 SSH settings, SSH refuses the new key with "REMOTE HOST IDENTIFICATION HAS CHANGED"; removing the old entry avoids that.

### 4.2 op-controlplane

**a. Start it and connect** (port 2205 reaches whichever clone has 10.0.1.5):

```powershell
# PowerShell
& "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe" startvm op-controlplane --type headless
ssh-keygen -R "[127.0.0.1]:2205" 2>$null
ssh -p 2205 root@127.0.0.1
```

If SSH says "connection refused" or times out, the VM is still booting: wait 30 seconds and run the `ssh` line again. Answer `yes` to the host key question. **Check:** `hostname` says `ol98-golden`.

**b. Name, identity and kubelet IP:**

```bash
# op-controlplane  (still on 10.0.1.5; connect: ssh -p 2205 root@127.0.0.1)
hostnamectl set-hostname op-controlplane
[ -s /etc/machine-id ] || systemd-machine-id-setup
ssh-keygen -A
echo 'KUBELET_EXTRA_ARGS="--node-ip=10.0.1.20"' >/etc/sysconfig/kubelet
echo "machine-id $(cat /etc/machine-id)  product_uuid $(cat /sys/class/dmi/id/product_uuid)"
hostname; cat /etc/sysconfig/kubelet
```

**Check:** `op-controlplane`, `--node-ip=10.0.1.20`, and a machine ID and product UUID different from the other nodes'.

**c. Move to 10.0.1.20 and reboot** (always last):

```bash
# op-controlplane  (still on 10.0.1.5; the session freezes or closes at the end; connect: ssh -p 2205 root@127.0.0.1)
if [ "$(hostname)" = "op-controlplane" ]; then
cat >/root/set-ip.sh <<'EOF'
for u in $(nmcli -g UUID con show); do
  [ "$(nmcli -g connection.interface-name con show $u)" = "enp0s3" ] && nmcli con delete $u
done
nmcli con add type ethernet con-name pub ifname enp0s3 ipv4.method manual ipv4.addresses 10.0.1.20/24 \
  ipv4.gateway 10.0.1.1 ipv4.dns 8.8.8.8 ipv6.method disabled connection.autoconnect yes
sleep 2; reboot
EOF
setsid nohup bash /root/set-ip.sh >/root/set-ip.log 2>&1 </dev/null &
else echo "STOP: this VM is $(hostname), not op-controlplane; run step b first"; fi
```

Your SSH session freezes or closes. That's expected: the VM is moving to 10.0.1.20 and rebooting.

**d. Check it on its own address** (wait about a minute after the move):

```powershell
# PowerShell
ssh -p 2220 root@127.0.0.1 "hostname; ip -4 -br addr show enp0s3; ip -br link show enp0s8; df -h /scratch /var/lib/containers; grep HugePages_Total /proc/meminfo; systemctl is-active crio"
```

**Check:**

- `op-controlplane`, and `10.0.1.20/24`;
- `Device "enp0s8" does not exist` and `df: /scratch: No such file or directory`: correct, it has no private NICs and no data disks;
- `/var/lib/containers` is on the root filesystem (`/dev/mapper/ol-root`);
- `HugePages_Total: 0`, and CRI-O is `active`.

### 4.3 op-worker1

**a. Start it and connect** (port 2205 reaches whichever clone has 10.0.1.5):

```powershell
# PowerShell
& "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe" startvm op-worker1 --type headless
ssh-keygen -R "[127.0.0.1]:2205" 2>$null
ssh -p 2205 root@127.0.0.1
```

If SSH says "connection refused" or times out, the VM is still booting: wait 30 seconds and run the `ssh` line again. Answer `yes` to the host key question. **Check:** `hostname` says `ol98-golden`.

**b. Name, identity and kubelet IP:**

```bash
# op-worker1  (still on 10.0.1.5; connect: ssh -p 2205 root@127.0.0.1)
hostnamectl set-hostname op-worker1
[ -s /etc/machine-id ] || systemd-machine-id-setup
ssh-keygen -A
echo 'KUBELET_EXTRA_ARGS="--node-ip=10.0.1.21"' >/etc/sysconfig/kubelet
echo "machine-id $(cat /etc/machine-id)  product_uuid $(cat /sys/class/dmi/id/product_uuid)"
hostname; cat /etc/sysconfig/kubelet
```

**Check:** `op-worker1`, `--node-ip=10.0.1.21`, and a machine ID and product UUID different from the other nodes'.

**c. Private NICs, up with no IP and promiscuous:**

```bash
# op-worker1  (still on 10.0.1.5; connect: ssh -p 2205 root@127.0.0.1)
for ifn in enp0s8 enp0s9; do
  for u in $(nmcli -g UUID con show); do
    [ "$(nmcli -g connection.interface-name con show $u)" = "$ifn" ] && nmcli con delete $u
  done
  nmcli con add type ethernet con-name rac-$ifn ifname $ifn ipv4.method disabled ipv6.method disabled \
    802-3-ethernet.mtu 1500 802-3-ethernet.accept-all-mac-addresses yes connection.autoconnect yes
done
ip -br link show enp0s8; ip -br link show enp0s9
```

**Check:** both NICs show `UP` and have no IPv4 address. `PROMISC` shows after the reboot in step h.

**d. Find the two data disks by size:**

```bash
# op-worker1  (still on 10.0.1.5; connect: ssh -p 2205 root@127.0.0.1)
lsblk -d -o NAME,SIZE,TYPE
pick() { lsblk -dbno NAME,SIZE,TYPE | awk -v lo=$(( ($1-2)*1024**3 )) -v hi=$(( ($1+2)*1024**3 )) '$3=="disk" && $2>=lo && $2<=hi {print "/dev/"$1}'; }
CONT=$(pick 100); SCRATCH=$(pick 80); echo "containers=$CONT scratch=$SCRATCH"
[ $(echo "$CONT" | wc -w) -eq 1 ] && [ $(echo "$SCRATCH" | wc -w) -eq 1 ] && [ -z "$(blkid -s TYPE -o value $CONT $SCRATCH)" ] && echo "OK: two blank disks found" || echo "STOP: check lsblk before formatting"
```

**Check:** it prints `OK: two blank disks found`. If it prints STOP, don't go on; paste the `lsblk` output.

**e. Format and mount them** (same session as d; it formats nothing unless d found the two blank disks):

```bash
# op-worker1  (still on 10.0.1.5, same session as step d; connect: ssh -p 2205 root@127.0.0.1)
if [ -b "$CONT" ] && [ -b "$SCRATCH" ] && [ "$CONT" != "$SCRATCH" ] && [ -z "$(blkid -s TYPE -o value $CONT $SCRATCH)" ]; then
systemctl stop kubelet crio
mkfs.xfs -q -f -L containers $CONT
mkdir -p /mnt/newcont && mount $CONT /mnt/newcont
rsync -aAXH /var/lib/containers/ /mnt/newcont/
umount /mnt/newcont && rmdir /mnt/newcont
echo "UUID=$(blkid -o value -s UUID $CONT)  /var/lib/containers  xfs  defaults  0 0" >>/etc/fstab
mkfs.xfs -q -f -L scratch $SCRATCH
mkdir -p /scratch
echo "UUID=$(blkid -o value -s UUID $SCRATCH)  /scratch  xfs  defaults  0 0" >>/etc/fstab
systemctl daemon-reload
mount /var/lib/containers && mount /scratch
restorecon -R /var/lib/containers
df -h /scratch /var/lib/containers
else echo "STOP: nothing formatted. Run step d in this same session; it must print OK"; fi
```

**Check:** `/scratch` about 80 G and `/var/lib/containers` about 100 G.

**f. The operator's directories, with SELinux labels:** `/scratch/rac/cluster01/racnode1` and `/scratch/rac/cluster01/racnode2` (the operator mounts one of them into each RAC pod as `/u01`), and `/scratch/software/stage` (the Oracle zips). **Both workers get both node directories:** the operator may place either RAC pod on either labelled worker.

```bash
# op-worker1  (still on 10.0.1.5; connect: ssh -p 2205 root@127.0.0.1)
for d in /scratch/rac/cluster01/racnode1 /scratch/rac/cluster01/racnode2 /scratch/software/stage; do mkdir -p $d; done
chown -R 54321:54321 /scratch/rac/cluster01
semanage fcontext -a -t container_file_t "/scratch/rac/cluster01(/.*)?"
semanage fcontext -a -t container_file_t "/scratch/software/stage(/.*)?"
restorecon -RF /scratch/rac/cluster01 /scratch/software/stage
ls -Zd /scratch/rac/cluster01/racnode1 /scratch/rac/cluster01/racnode2 /scratch/software/stage; ls -ld /scratch/rac/cluster01/racnode*
```

**Check:** all three directories show `container_file_t`, and both `racnode*` directories are owned by `54321 54321`, shown as `oracle oinstall` if the host has those users: the IDs of `oracle` and `oinstall` inside the RAC image.

**g. HugePages:**

```bash
# op-worker1  (still on 10.0.1.5; connect: ssh -p 2205 root@127.0.0.1)
echo "vm.nr_hugepages = 2048" >/etc/sysctl.d/92-hugepages.conf
sysctl -p /etc/sysctl.d/92-hugepages.conf
grep -E 'HugePages_Total|Hugepagesize' /proc/meminfo
```

**Check:** `HugePages_Total: 2048` and `Hugepagesize: 2048 kB`.

**h. Move to 10.0.1.21 and reboot** (always last):

```bash
# op-worker1  (still on 10.0.1.5; the session freezes or closes at the end; connect: ssh -p 2205 root@127.0.0.1)
if [ "$(hostname)" = "op-worker1" ]; then
cat >/root/set-ip.sh <<'EOF'
for u in $(nmcli -g UUID con show); do
  [ "$(nmcli -g connection.interface-name con show $u)" = "enp0s3" ] && nmcli con delete $u
done
nmcli con add type ethernet con-name pub ifname enp0s3 ipv4.method manual ipv4.addresses 10.0.1.21/24 \
  ipv4.gateway 10.0.1.1 ipv4.dns 8.8.8.8 ipv6.method disabled connection.autoconnect yes
sleep 2; reboot
EOF
setsid nohup bash /root/set-ip.sh >/root/set-ip.log 2>&1 </dev/null &
else echo "STOP: this VM is $(hostname), not op-worker1; run step b first"; fi
```

Your SSH session freezes or closes. That's expected: the VM is moving to 10.0.1.21 and rebooting.

**i. Check it on its own address** (wait about a minute after the move):

```powershell
# PowerShell
ssh -p 2221 root@127.0.0.1 "hostname; ip -4 -br addr show enp0s3; ip -br link show enp0s8; df -h /scratch /var/lib/containers; grep HugePages_Total /proc/meminfo; systemctl is-active crio"
```

**Check:**

- `op-worker1`, and `10.0.1.21/24`;
- `enp0s8` shows `UP` and `PROMISC`, with no address;
- `/scratch` is 80 G, and `/var/lib/containers` is 100 G;
- `HugePages_Total: 2048`;
- CRI-O is `active`.

### 4.4 op-worker2

**a. Start it and connect** (port 2205 reaches whichever clone has 10.0.1.5):

```powershell
# PowerShell
& "C:\Program Files\Oracle\VirtualBox\VBoxManage.exe" startvm op-worker2 --type headless
ssh-keygen -R "[127.0.0.1]:2205" 2>$null
ssh -p 2205 root@127.0.0.1
```

If SSH says "connection refused" or times out, the VM is still booting: wait 30 seconds and run the `ssh` line again. Answer `yes` to the host key question. **Check:** `hostname` says `ol98-golden`.

**b. Name, identity and kubelet IP:**

```bash
# op-worker2  (still on 10.0.1.5; connect: ssh -p 2205 root@127.0.0.1)
hostnamectl set-hostname op-worker2
[ -s /etc/machine-id ] || systemd-machine-id-setup
ssh-keygen -A
echo 'KUBELET_EXTRA_ARGS="--node-ip=10.0.1.22"' >/etc/sysconfig/kubelet
echo "machine-id $(cat /etc/machine-id)  product_uuid $(cat /sys/class/dmi/id/product_uuid)"
hostname; cat /etc/sysconfig/kubelet
```

**Check:** `op-worker2`, `--node-ip=10.0.1.22`, and a machine ID and product UUID different from the other nodes'.

**c. Private NICs, up with no IP and promiscuous:**

```bash
# op-worker2  (still on 10.0.1.5; connect: ssh -p 2205 root@127.0.0.1)
for ifn in enp0s8 enp0s9; do
  for u in $(nmcli -g UUID con show); do
    [ "$(nmcli -g connection.interface-name con show $u)" = "$ifn" ] && nmcli con delete $u
  done
  nmcli con add type ethernet con-name rac-$ifn ifname $ifn ipv4.method disabled ipv6.method disabled \
    802-3-ethernet.mtu 1500 802-3-ethernet.accept-all-mac-addresses yes connection.autoconnect yes
done
ip -br link show enp0s8; ip -br link show enp0s9
```

**Check:** both NICs show `UP` and have no IPv4 address. `PROMISC` shows after the reboot in step h.

**d. Find the two data disks by size:**

```bash
# op-worker2  (still on 10.0.1.5; connect: ssh -p 2205 root@127.0.0.1)
lsblk -d -o NAME,SIZE,TYPE
pick() { lsblk -dbno NAME,SIZE,TYPE | awk -v lo=$(( ($1-2)*1024**3 )) -v hi=$(( ($1+2)*1024**3 )) '$3=="disk" && $2>=lo && $2<=hi {print "/dev/"$1}'; }
CONT=$(pick 100); SCRATCH=$(pick 80); echo "containers=$CONT scratch=$SCRATCH"
[ $(echo "$CONT" | wc -w) -eq 1 ] && [ $(echo "$SCRATCH" | wc -w) -eq 1 ] && [ -z "$(blkid -s TYPE -o value $CONT $SCRATCH)" ] && echo "OK: two blank disks found" || echo "STOP: check lsblk before formatting"
```

**Check:** it prints `OK: two blank disks found`. If it prints STOP, don't go on; paste the `lsblk` output.

**e. Format and mount them** (same session as d; it formats nothing unless d found the two blank disks):

```bash
# op-worker2  (still on 10.0.1.5, same session as step d; connect: ssh -p 2205 root@127.0.0.1)
if [ -b "$CONT" ] && [ -b "$SCRATCH" ] && [ "$CONT" != "$SCRATCH" ] && [ -z "$(blkid -s TYPE -o value $CONT $SCRATCH)" ]; then
systemctl stop kubelet crio
mkfs.xfs -q -f -L containers $CONT
mkdir -p /mnt/newcont && mount $CONT /mnt/newcont
rsync -aAXH /var/lib/containers/ /mnt/newcont/
umount /mnt/newcont && rmdir /mnt/newcont
echo "UUID=$(blkid -o value -s UUID $CONT)  /var/lib/containers  xfs  defaults  0 0" >>/etc/fstab
mkfs.xfs -q -f -L scratch $SCRATCH
mkdir -p /scratch
echo "UUID=$(blkid -o value -s UUID $SCRATCH)  /scratch  xfs  defaults  0 0" >>/etc/fstab
systemctl daemon-reload
mount /var/lib/containers && mount /scratch
restorecon -R /var/lib/containers
df -h /scratch /var/lib/containers
else echo "STOP: nothing formatted. Run step d in this same session; it must print OK"; fi
```

**Check:** `/scratch` about 80 G and `/var/lib/containers` about 100 G.

**f. The operator's directories, with SELinux labels:** `/scratch/rac/cluster01/racnode1` and `/scratch/rac/cluster01/racnode2` (the operator mounts one of them into each RAC pod as `/u01`), and `/scratch/software/stage` (the Oracle zips). **Both workers get both node directories:** the operator may place either RAC pod on either labelled worker.

```bash
# op-worker2  (still on 10.0.1.5; connect: ssh -p 2205 root@127.0.0.1)
for d in /scratch/rac/cluster01/racnode1 /scratch/rac/cluster01/racnode2 /scratch/software/stage; do mkdir -p $d; done
chown -R 54321:54321 /scratch/rac/cluster01
semanage fcontext -a -t container_file_t "/scratch/rac/cluster01(/.*)?"
semanage fcontext -a -t container_file_t "/scratch/software/stage(/.*)?"
restorecon -RF /scratch/rac/cluster01 /scratch/software/stage
ls -Zd /scratch/rac/cluster01/racnode1 /scratch/rac/cluster01/racnode2 /scratch/software/stage; ls -ld /scratch/rac/cluster01/racnode*
```

**Check:** all three directories show `container_file_t`, and both `racnode*` directories are owned by `54321 54321`, shown as `oracle oinstall` if the host has those users: the IDs of `oracle` and `oinstall` inside the RAC image.

**g. HugePages:**

```bash
# op-worker2  (still on 10.0.1.5; connect: ssh -p 2205 root@127.0.0.1)
echo "vm.nr_hugepages = 2048" >/etc/sysctl.d/92-hugepages.conf
sysctl -p /etc/sysctl.d/92-hugepages.conf
grep -E 'HugePages_Total|Hugepagesize' /proc/meminfo
```

**Check:** `HugePages_Total: 2048` and `Hugepagesize: 2048 kB`.

**h. Move to 10.0.1.22 and reboot** (always last):

```bash
# op-worker2  (still on 10.0.1.5; the session freezes or closes at the end; connect: ssh -p 2205 root@127.0.0.1)
if [ "$(hostname)" = "op-worker2" ]; then
cat >/root/set-ip.sh <<'EOF'
for u in $(nmcli -g UUID con show); do
  [ "$(nmcli -g connection.interface-name con show $u)" = "enp0s3" ] && nmcli con delete $u
done
nmcli con add type ethernet con-name pub ifname enp0s3 ipv4.method manual ipv4.addresses 10.0.1.22/24 \
  ipv4.gateway 10.0.1.1 ipv4.dns 8.8.8.8 ipv6.method disabled connection.autoconnect yes
sleep 2; reboot
EOF
setsid nohup bash /root/set-ip.sh >/root/set-ip.log 2>&1 </dev/null &
else echo "STOP: this VM is $(hostname), not op-worker2; run step b first"; fi
```

Your SSH session freezes or closes. That's expected: the VM is moving to 10.0.1.22 and rebooting.

**i. Check it on its own address** (wait about a minute after the move):

```powershell
# PowerShell
ssh -p 2222 root@127.0.0.1 "hostname; ip -4 -br addr show enp0s3; ip -br link show enp0s8; df -h /scratch /var/lib/containers; grep HugePages_Total /proc/meminfo; systemctl is-active crio"
```

**Check:**

- `op-worker2`, and `10.0.1.22/24`;
- `enp0s8` shows `UP` and `PROMISC`, with no address;
- `/scratch` is 80 G, and `/var/lib/containers` is 100 G;
- `HugePages_Total: 2048`;
- CRI-O is `active`.

When op-worker2 passes its check, all three nodes are on their own addresses. Go on to Phase 5.
