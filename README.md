# RAC on Kubernetes: operator lab (kubeadm)

A 2-node Oracle RAC 19c (19.32 gold images) on a 3-node kubeadm cluster in VirtualBox, created by Oracle's Database Operator for Kubernetes (v2.2.0, `RacDatabase`). It sits beside the manual lab (`rac-k8s-poc-manual-kubeadm`) with its own VM names, IPs, ports and disks; only one lab runs at a time.

- `guide/rac-k8s-operator-lab-guide.html` and `.pdf`: the step-by-step guide (Phases 0, 3–12), every block copy-and-paste ready with its connect line and this lab's output. Phase 8.0 builds the 19.33 gold-image zips on a separate host; Phase 12 opens the database to Windows through SCAN.
- `design/rac-operator-lab-design.html` and `.pdf`: the system design: what the lab is, its networks, storage, what the operator does and the install sequence, each diagram with commands and output from the lab.
- `design/diagrams/`: the six diagrams as SVG (`op-<name>.svg` follows light/dark mode; `-light` / `-dark` are fixed) and PNG.
- `src/`: the guide's Markdown sections and the build script.

Not in this repository: passwords, SSH keys, kubeconfig files, the Secrets' key files, Oracle software zips and Oracle's documentation.
