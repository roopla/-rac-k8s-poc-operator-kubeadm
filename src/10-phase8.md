## Phase 8: The RAC slim image and the software

**Result of this phase:** fully patched 19.33 gold-image zips of the Grid and DB homes (built once per RU on a separate host), Oracle's RAC slim image, `localhost/oracle/database-rac:19.3.0-slim`, on both workers, and the two 19.32 gold-image zips in `/scratch/software/stage` on both workers.

**Why on both workers:** the operator may start either RAC pod on either labelled worker, and each worker's CRI-O can only start images it has locally. The image never leaves the worker it was built on, so nothing needs a registry.

### 8.0 Build the 19.33 gold-image zips (on a separate build host, once per RU)

**What:** a fully patched, unconfigured Grid home and Oracle (DB) home at **19.33.0.0.261020**, the October 2026 Release Update, each packed into one zip with Oracle's `-createGoldImage`. The `RacDatabase` names these zips (`gridSwZipFile`, `dbSwZipFile`); each RAC pod unzips them and runs only the software-only installs with `-noCopy`, so **nothing is patched during the deployment**.

**Why a separate host:** patching needs a full 19.3 home, a new OPatch and a 2–3 GB Release Update, and the `grid` and `oracle` users, but no cluster, no shared disks and no Kubernetes. Doing it once on a plain Oracle Linux 9.8 server, `oldblab-db1`, keeps that work out of the RAC lab, and the two zips are reused for every RAC build at 19.33.

**Which RU the lab runs:** the RAC database built in Phases 10–11 reports `19.32.0.0.0` (11.5, 11.6c), from the 19.32 zips staged in 8.2. This section builds the **19.33** zips; for a build from them, the zip names in 8.2 and in the `RacDatabase` change to `oracle-gridhome-19.33.zip` and `oracle-dbhome-19.33.zip`.

**The steps, in the order this run did them:**

| Part | Home | What |
| --- | --- | --- |
| a | — | the build host: OS, users, the downloaded software |
| b | — | which patch is which, and unpacking the combo patch |
| c–f | Grid | unzip 19.3, new OPatch, apply OJVM RU, GI RU and JDK patch, software-only install, gold image |
| g–j | Oracle | the same for the DB home |
| k | both | name, test and checksum the zips |

**Why `-applyRU` before installing:** `gridSetup.sh -applyRU` and `runInstaller -applyRU` patch the unzipped home first and then stop (there's no response file). The software-only install that follows then already runs the 19.33 installer, which knows Oracle Linux 9; the unpatched 19.3 installer doesn't, and would need `CV_ASSUME_DISTID`. In this run neither install needed it.

**Why the software-only install before `-createGoldImage`:** it relinks the binaries for this OS and registers the home in the inventory; `-createGoldImage` then packs the home as installed: patched, relinked, not configured (no cluster, no ASM, no database, no listener). The pod's own software-only install with `-noCopy` registers it again on each RAC node.

#### a. The build host

The host has the `oracle` and `grid` users with the standard 19c groups, and these directories, owned `oracle:oinstall` (DB side) and `grid:oinstall` (Grid side): `/u01/app/19.0.0/grid`, `/u01/app/grid`, `/u01/app/oraInventory`, `/u01/app/oracle/product/19.0.0/dbhome_1`, and `/u01/app/oracle/software` holding the downloads. (How the users and directories were created wasn't captured; the output below shows the result.) The home paths may differ from the RAC pods' (`/u01/app/19c/…`): a gold image unzips into any home path.

```bash
# oldblab-db1 as labadmin  (the build host)
cd
uname -a
cat /etc/os-release
id oracle
id grid
ls -altrh /u01/app/oracle/software/
```

**Check:** Oracle Linux 9.8 on UEK; `oracle` in `oinstall`, `dba`, `oper`, `backupdba`, `dgdba`, `kmdba`, `racdba`, `asmdba`; `grid` in `oinstall`, `racdba`, `asmdba`, `asmoper`, `asmadmin`; the two 19.3 base zips, the RUs, the JDK patch and OPatch (17 GB in all).

**This lab's output:**

```text
[labadmin@oldblab-db1 ~]$ uname -a
Linux oldblab-db1 6.12.0-207.111.5.1.el9uek.x86_64 #2 SMP PREEMPT_DYNAMIC Thu Oct  1 11:42:26 PDT 2026 x86_64 x86_64 x86_64 GNU/Linux
[labadmin@oldblab-db1 ~]$ cat /etc/os-release
NAME="Oracle Linux Server"
VERSION="9.8"
ID="ol"
ID_LIKE="fedora"
VARIANT="Server"
VARIANT_ID="server"
VERSION_ID="9.8"
PLATFORM_ID="platform:el9"
PRETTY_NAME="Oracle Linux Server 9.8"
ANSI_COLOR="0;31"
CPE_NAME="cpe:/o:oracle:linux:9:8:server"
HOME_URL="https://linux.oracle.com/"
BUG_REPORT_URL="https://github.com/oracle/oracle-linux"

ORACLE_BUGZILLA_PRODUCT="Oracle Linux 9"
ORACLE_BUGZILLA_PRODUCT_VERSION=9.8
ORACLE_SUPPORT_PRODUCT="Oracle Linux"
ORACLE_SUPPORT_PRODUCT_VERSION=9.8
[labadmin@oldblab-db1 ~]$ id oracle
uid=54321(oracle) gid=54321(oinstall) groups=54321(oinstall),54322(dba),54323(oper),54324(backupdba),54325(dgdba),54326(kmdba),54330(racdba),54327(asmdba)
[labadmin@oldblab-db1 ~]$ id grid
uid=54331(grid) gid=54321(oinstall) groups=54321(oinstall),54330(racdba),54327(asmdba),54328(asmoper),54329(asmadmin)
[labadmin@oldblab-db1 ~]$ ls -altrh /u01/app/oracle/software/
total 17G
-rwxrwxrwx. 1 labadmin labadmin 2.9G Oct 28 12:00 LINUX.X64_193000_db_home.zip
-rwxrwxrwx. 1 labadmin labadmin 2.7G Oct 28 12:09 LINUX.X64_193000_grid_home.zip
-rwxrwxrwx. 1 labadmin labadmin 124M Oct 28 12:09 p39803650_190000_Linux-x86-64.zip
-rwxrwxrwx. 1 labadmin labadmin 125M Oct 28 12:10 p39902038_210000_Linux-x86-64.zip
-rwxrwxrwx. 1 labadmin labadmin 125M Oct 28 12:10 p39902051_190000_Linux-x86-64.zip
-rwxrwxrwx. 1 labadmin labadmin 2.3G Oct 28 12:17 p39915792_190000_Linux-x86-64.zip
-rwxrwxrwx. 1 labadmin labadmin 2.7G Oct 28 12:31 p39922757_190000_Linux-x86-64.zip
-rwxrwxrwx. 1 labadmin labadmin 2.4G Oct 28 12:44 p40121635_190000_Linux-x86-64.zip
-rwxrwxrwx. 1 labadmin labadmin 2.8G Oct 28 12:56 p40121665_190000_Linux-x86-64.zip
-rwxrwxrwx. 1 labadmin labadmin 129M Oct 28 12:57 p6880880_190000_Linux-x86-64.zip
-rwxrwxrwx. 1 labadmin labadmin 129M Oct 28 12:58 p6880880_210000_Linux-x86-64.zip
drwxr-xr-x. 4 oracle   oinstall   37 Oct 28 13:16 ..
drwxr-xr-x. 2 oracle   oinstall 4.0K Oct 28 13:19 .
```

#### b. Which patch is which, and unpacking the combo patch

The patches were downloaded from My Oracle Support on a separate machine, `z11devrm473`, with a README listing each file. Only four of them are used: OPatch, the GI + OJVM combo, and the JDK patch (the two 21c files and the single RU zips aren't needed; the combo contains the GI RU and the OJVM RU).

```bash
# z11devrm473  (the download machine, in the patch folder)
cat README-patch-numbers-with-descriptions
```

**This lab's output:**

```text
[apreddy@z11devrm473 OCT2026-patches]$ cat README-patch-numbers-with-descriptions
 p40121665_190000_Linux-x86-64.zip   -  Combo OJVM Release Update 19.33.0.0.261020 and GI Release Update 19.33.0.0.261020 PATCH 40121665
 p40121635_190000_Linux-x86-64.zip   -  Combo OJVM Release Update 19.33.0.0.261020 and Database Release Update 19.33.0.0.261020 PATCH 40121635  for UNIX, or
 p39915792_190000_Linux-x86-64.zip   -  Database Release Update 19.33.0.0.261020 PATCH 39915792  for UNIX, or
 p39922757_190000_Linux-x86-64.zip   -  GI Release Update 19.33.0.0.261020 PATCH 39922757
 p39803650_190000_Linux-x86-64.zip   -  OJVM Release Update 19.33.0.0.261020 PATCH 39803650 for all platforms
 p39902051_190000_Linux-x86-64.zip   -  JDK8u511 PATCH 39902051
 p6880880_190000_Linux-x86-64.zip    -  Opatch for 19C

p39902038_210000_Linux-x86-64.zip   -  JDK for 21C
p6880880_210000_Linux-x86-64.zip    -  Opatch for 21C
```

| Patch | What it is | Used here |
| --- | --- | --- |
| `p6880880_190000` | OPatch for 19c (12.2.0.1.54) | both homes; 19.3 ships 12.2.0.1.17, too old for the RU |
| `p40121665_190000` | Combo: OJVM RU 19.33 + GI RU 19.33 | unpacked to `40121665/39922757` (GI RU) and `40121665/39803650` (OJVM RU), both homes |
| `p39902051_190000` | JDK 8u511 bundle patch | both homes |
| `p40121635`, `p39915792`, `p39922757`, `p39803650` | the OJVM + DB RU combo, and the RUs as single zips | not used; the combo above contains them |
| `p39902038_210000`, `p6880880_210000` | JDK and OPatch for 21c | not used |

**Why the GI RU in the Oracle home too:** the GI RU contains the Database RU (`39915792`) and the OCW RU (`39922783`) that a RAC database home needs, so with the same patch on both homes, Grid and DB are at exactly the same level (see the `lspatches` in e and i).

```bash
# oldblab-db1 as oracle  (sudo su - oracle)
cd /u01/app/oracle/software
unzip p40121665_190000_Linux-x86-64.zip
unzip p39902051_190000_Linux-x86-64.zip
cd 40121665
pwd
ls -altrh
```

**Check:** `40121665` holds `39803650` (OJVM RU) and `39922757` (GI RU), plus Oracle's README; `/u01/app/oracle/software/39902051` exists for the JDK patch. (Only the `pwd` and `ls` were captured in this run.)

**This lab's output:**

```text
[oracle@oldblab-db1 40121665]$ pwd
/u01/app/oracle/software/40121665
[oracle@oldblab-db1 40121665]$ ls -altrh
total 64K
drwxrwxrwx. 4 oracle oinstall   67 Oct  1 07:41 39803650
drwxrwxrwx. 8 oracle oinstall  159 Oct 16 05:24 39922757
-rwxrwxrwx. 1 oracle oinstall  34K Oct 19 04:16 PatchSearch.xml
-rwxrwxrwx. 1 oracle oinstall  23K Oct 19 06:28 README.html
drwxrwxrwx. 4 oracle oinstall   80 Oct 19 06:28 .
drwxr-xr-x. 3 oracle oinstall 4.0K Oct 28 13:29 ..
```

#### c. Grid home: unzip 19.3 and replace OPatch

19c homes are image-based: the base zip's contents **are** the home, so it's unzipped straight into the Grid home directory. The 19.3 home ships OPatch 12.2.0.1.17; the 19.33 RU needs a newer one, so the old `OPatch` directory is removed and the new one unzipped in its place.

```bash
# oldblab-db1 as grid  (sudo su - grid)
cd /u01/app/19.0.0/grid/
pwd
unzip /u01/app/oracle/software/LINUX.X64_193000_grid_home.zip
cd OPatch/
./opatch version
cd ..
rm -rf OPatch/
unzip /u01/app/oracle/software/p6880880_190000_Linux-x86-64.zip
cd OPatch/
./opatch version
cd ..
```

**Check:** `12.2.0.1.17` before and `12.2.0.1.54` after.

**This lab's output (the unzip listings left out):**

```text
[grid@oldblab-db1 grid]$ pwd
/u01/app/19.0.0/grid
[grid@oldblab-db1 grid]$ unzip /u01/app/oracle/software/LINUX.X64_193000_grid_home.zip
…
[grid@oldblab-db1 grid]$ cd OPatch/
[grid@oldblab-db1 OPatch]$ ./opatch version
OPatch Version: 12.2.0.1.17

[grid@oldblab-db1 grid]$ rm -rf OPatch/
[grid@oldblab-db1 grid]$ unzip /u01/app/oracle/software/p6880880_190000_Linux-x86-64.zip
…
[grid@oldblab-db1 grid]$ cd OPatch/
[grid@oldblab-db1 OPatch]$ ./opatch version
OPatch Version: 12.2.0.1.54

OPatch succeeded.
```

#### d. Grid home: apply the OJVM RU, the GI RU and the JDK patch

```bash
# oldblab-db1 as grid  (sudo su - grid)
cd /u01/app/19.0.0/grid
./gridSetup.sh -applyRU /u01/app/oracle/software/40121665/39803650/ -silent
./gridSetup.sh -applyRU /u01/app/oracle/software/40121665/39922757/ -silent
./gridSetup.sh -applyOneOffs /u01/app/oracle/software/39902051 -silent
```

**Check:** each ends with `Successfully applied the patch.`

**This lab's output:**

```text
[grid@oldblab-db1 grid]$ ./gridSetup.sh -applyRU /u01/app/oracle/software/40121665/39803650/ -silent
Preparing the home to patch...
Applying the patch /u01/app/oracle/software/40121665/39803650/...
Successfully applied the patch.

[grid@oldblab-db1 grid]$ ./gridSetup.sh -applyRU /u01/app/oracle/software/40121665/39922757/ -silent
Preparing the home to patch...
Applying the patch /u01/app/oracle/software/40121665/39922757/...
Successfully applied the patch.

[grid@oldblab-db1 grid]$ pwd
/u01/app/19.0.0/grid
[grid@oldblab-db1 grid]$ ./gridSetup.sh -applyOneOffs /u01/app/oracle/software/39902051 -silent
Preparing the home to patch...
Applying the patch /u01/app/oracle/software/39902051...
Successfully applied the patch.
```

#### e. Grid home: software-only install and root scripts

`CRS_SWONLY` installs the Grid software on this host without configuring a cluster: it relinks the binaries and registers the home in `/u01/app/oraInventory`. Then the root scripts set the inventory and home permissions.

```bash
# oldblab-db1 as grid  (sudo su - grid)
cd /u01/app/19.0.0/grid
./gridSetup.sh \
  -silent \
  -waitforcompletion \
  oracle.install.option=CRS_SWONLY \
  ORACLE_BASE=/u01/app/grid \
  INVENTORY_LOCATION=/u01/app/oraInventory \
  UNIX_GROUP_NAME=oinstall \
  oracle.install.asm.OSDBA=asmdba \
  oracle.install.asm.OSOPER=asmoper \
  oracle.install.asm.OSASM=asmadmin
cd OPatch/
./opatch lspatches
```

**Check:** `Successfully Setup Software with warning(s).` (the warnings are optional prerequisite checks), and seven patches in `lspatches`: the JDK bundle patch, the OJVM RU, and five that the GI RU brings: ACFS, OCW, Database RU, Tomcat and DBWLM.

**This lab's output:**

```text
[grid@oldblab-db1 grid]$ ./gridSetup.sh -silent -waitforcompletion oracle.install.option=CRS_SWONLY … oracle.install.asm.OSASM=asmadmin
Launching Oracle Grid Infrastructure Setup Wizard...

The response file for this session can be found at:
 /u01/app/19.0.0/grid/install/response/grid_2026-10-28_03-44-56PM.rsp

You can find the log of this install session at:
 /tmp/GridSetupActions2026-10-28_03-44-56PM/gridSetupActions2026-10-28_03-44-56PM.log

As a root user, execute the following script(s):
	1. /u01/app/oraInventory/orainstRoot.sh
	2. /u01/app/19.0.0/grid/root.sh

Execute /u01/app/oraInventory/orainstRoot.sh on the following nodes: 
[oldblab-db1]
Execute /u01/app/19.0.0/grid/root.sh on the following nodes: 
[oldblab-db1]


Successfully Setup Software with warning(s).
Moved the install session logs to:
 /u01/app/oraInventory/logs/GridSetupActions2026-10-28_03-44-56PM
[grid@oldblab-db1 grid]$ cd OPatch/
[grid@oldblab-db1 OPatch]$ ./opatch lspatches
39902051;JDK BUNDLE PATCH 19.0.0.0.261020
39922802;ACFS RELEASE UPDATE 19.33.0.0.0 (39922802)
39922783;OCW RELEASE UPDATE 19.33.0.0.0 (39922783)
39915792;Database Release Update : 19.33.0.0.261020 (39915792)
39107855;TOMCAT RELEASE UPDATE 19.0.0.0.0 (39107855)
39107825;DBWLM RELEASE UPDATE 19.0.0.0.0 (39107825)
39803650;OJVM RELEASE UPDATE: 19.33.0.0.261020 (39803650)

OPatch succeeded.
```

```bash
# oldblab-db1 as root  (after the install above has finished)
/u01/app/oraInventory/orainstRoot.sh
/u01/app/19.0.0/grid/root.sh
```

**Check:** `The execution of the script is complete.` from `orainstRoot.sh`; `root.sh` writes its output to the log file it names.

**This lab's output:**

```text
[root@oldblab-db1 ~]# /u01/app/oraInventory/orainstRoot.sh
Changing permissions of /u01/app/oraInventory.
Adding read,write permissions for group.
Removing read,write,execute permissions for world.

Changing groupname of /u01/app/oraInventory to oinstall.
The execution of the script is complete.
[root@oldblab-db1 ~]# /u01/app/19.0.0/grid/root.sh
Check /u01/app/19.0.0/grid/install/root_oldblab-db1_2026-10-28_15-48-28-438221666.log for the output of root script
```

#### f. Grid home: create the gold image

```bash
# oldblab-db1 as grid  (sudo su - grid)
cd /u01/app/19.0.0/grid/
./gridSetup.sh -createGoldImage -destinationLocation /tmp/grid-gold -silent
```

**Check:** `Successfully Setup Software.` and the zip's path.

**This lab's output:**

```text
[grid@oldblab-db1 grid]$ ./gridSetup.sh   -createGoldImage   -destinationLocation /tmp/grid-gold   -silent
Launching Oracle Grid Infrastructure Setup Wizard...

Successfully Setup Software.
Gold Image location: /tmp/grid-gold/grid_home_2026-10-28_03-48-55PM.zip
```

#### g. Oracle home: unzip 19.3 and replace OPatch

The same as c, as `oracle`, into the DB home. (In this run the Oracle home was unzipped first, before the Grid home; the order doesn't matter.) The `ls` shows what an unpacked 19.3 home looks like: every directory dated April 2019, including `OPatch`, `.patch_storage` and `.opatchauto_storage`.

```bash
# oldblab-db1 as oracle  (sudo su - oracle)
cd /u01/app/oracle/product/19.0.0/dbhome_1/
pwd
unzip /u01/app/oracle/software/LINUX.X64_193000_db_home.zip
ls -altrh
cd OPatch/
./opatch version
cd ../
rm -rf OPatch/
unzip /u01/app/oracle/software/p6880880_190000_Linux-x86-64.zip
cd OPatch/
./opatch version
cd ..
```

**Check:** the home's directories (`bin`, `rdbms`, `OPatch`, `runInstaller` …) directly under `dbhome_1`; OPatch `12.2.0.1.17` before and `12.2.0.1.54` after.

**This lab's output (the unzip listings left out):**

```text
[oracle@oldblab-db1 dbhome_1]$ pwd
/u01/app/oracle/product/19.0.0/dbhome_1
[oracle@oldblab-db1 dbhome_1]$ unzip /u01/app/oracle/software/LINUX.X64_193000_db_home.zip
…
[oracle@oldblab-db1 dbhome_1]$ ls -altrh
total 92K
-rw-r--r--.  1 oracle oinstall  852 Aug 18  2015 env.ora
-rw-r--r--.  1 oracle oinstall 2.9K Oct 14  2016 schagent.conf
-rwxr-x---.  1 oracle oinstall 1.8K Mar  8  2017 runInstaller
drwxr-x---. 14 oracle oinstall 4.0K Apr 12  2019 OPatch
drwxr-x---.  7 oracle oinstall   69 Apr 17  2019 xdk
drwxr-xr-x.  3 oracle oinstall   19 Apr 17  2019 wwg
drwxr-xr-x.  4 oracle oinstall   31 Apr 17  2019 usm
drwxr-xr-x.  5 oracle oinstall   45 Apr 17  2019 suptools
drwxr-xr-x.  6 oracle oinstall   54 Apr 17  2019 srvm
drwxr-xr-x.  3 oracle oinstall   17 Apr 17  2019 sqlj
drwxr-xr-x.  4 oracle oinstall   41 Apr 17  2019 sqldeveloper
drwxr-xr-x.  3 oracle oinstall   18 Apr 17  2019 slax
-rw-r-----.  1 oracle oinstall   10 Apr 17  2019 root.sh.old.1
drwxr-xr-x.  3 oracle oinstall   21 Apr 17  2019 relnotes
drwxr-xr-x.  4 oracle oinstall   29 Apr 17  2019 racg
drwxr-xr-x.  5 oracle oinstall   52 Apr 17  2019 R
drwxr-xr-x.  5 oracle oinstall   39 Apr 17  2019 perl
drwxr-xr-x.  4 oracle oinstall   33 Apr 17  2019 owm
drwxr-xr-x.  3 oracle oinstall   19 Apr 17  2019 oss
drwxr-xr-x.  6 oracle oinstall   52 Apr 17  2019 ord
drwxr-xr-x.  4 oracle oinstall   34 Apr 17  2019 oracore
drwxr-xr-x.  7 oracle oinstall   65 Apr 17  2019 opmn
drwxr-xr-x.  5 oracle oinstall   42 Apr 17  2019 olap
drwxr-xr-x.  5 oracle oinstall   46 Apr 17  2019 nls
drwxr-xr-x.  4 oracle oinstall   31 Apr 17  2019 mgw
drwxr-xr-x.  9 oracle oinstall   98 Apr 17  2019 md
drwxr-xr-x. 10 oracle oinstall  112 Apr 17  2019 ldap
drwxr-xr-x.  3 oracle oinstall   18 Apr 17  2019 has
drwxr-xr-x.  3 oracle oinstall   19 Apr 17  2019 dv
drwxr-xr-x.  3 oracle oinstall   20 Apr 17  2019 diagnostics
drwxr-xr-x.  3 oracle oinstall   20 Apr 17  2019 demo
drwxr-xr-x.  3 oracle oinstall   19 Apr 17  2019 dbjava
drwxr-xr-x.  3 oracle oinstall   20 Apr 17  2019 data
drwxr-xr-x.  7 oracle oinstall   71 Apr 17  2019 cv
drwxr-xr-x.  3 oracle oinstall   18 Apr 17  2019 css
drwxr-xr-x.  6 oracle oinstall   55 Apr 17  2019 crs
drwxr-xr-x.  6 oracle oinstall   78 Apr 17  2019 plsql
drwxr-xr-x.  2 oracle oinstall   22 Apr 17  2019 dbs
drwxr-xr-x.  2 oracle oinstall   33 Apr 17  2019 utl
drwxr-xr-x.  2 oracle oinstall   29 Apr 17  2019 instantclient
drwxr-xr-x. 13 oracle oinstall 4.0K Apr 17  2019 dmu
drwxr-xr-x.  3 oracle oinstall   35 Apr 17  2019 ucp
drwxr-xr-x.  3 oracle oinstall   35 Apr 17  2019 jdbc
drwxr-xr-x.  2 oracle oinstall   26 Apr 17  2019 QOpatch
drwxr-xr-x.  4 oracle oinstall   66 Apr 17  2019 ords
drwxr-xr-x.  5 oracle oinstall  119 Apr 17  2019 sdk
drwxr-xr-x.  6 oracle oinstall 4.0K Apr 17  2019 apex
drwxr-xr-x.  8 oracle oinstall  101 Apr 17  2019 odbc
drwxr-xr-x.  2 oracle oinstall 4.0K Apr 17  2019 jlib
drwxr-xr-x.  4 oracle oinstall   30 Apr 17  2019 drdaas
drwxr-xr-x. 11 oracle oinstall  119 Apr 17  2019 ctx
-rwx------.  1 oracle oinstall  786 Apr 17  2019 root.sh.old
drwxr-xr-x. 10 oracle oinstall  106 Apr 17  2019 network
drwxr-xr-x.  5 oracle oinstall   41 Apr 17  2019 hs
drwxr-xr-x.  9 oracle oinstall   93 Apr 17  2019 assistants
drwxr-xr-x.  6 oracle oinstall   53 Apr 18  2019 sqlplus
-rwx------.  1 oracle oinstall  638 Apr 18  2019 root.sh
drwxr-xr-x.  8 oracle oinstall 4.0K Apr 18  2019 oui
drwxr-xr-x.  5 oracle oinstall  191 Apr 18  2019 deinstall
drwxr-xr-x.  4 oracle oinstall   87 Apr 18  2019 clone
drwxr-xr-x.  2 oracle oinstall  102 Apr 18  2019 addnode
drwxr-xr-x.  4 oracle oinstall 4.0K Apr 18  2019 sqlpatch
drwxr-xr-x.  3 oracle oinstall   28 Apr 18  2019 .opatchauto_storage
drwxr-xr-x.  5 oracle oinstall  188 Apr 18  2019 .patch_storage
drwxr-xr-x. 13 oracle oinstall  140 Apr 18  2019 rdbms
drwxr-xr-x.  6 oracle oinstall   56 Apr 18  2019 precomp
drwxr-xr-x.  4 oracle oinstall  12K Apr 18  2019 lib
drwxr-xr-x.  6 oracle oinstall 4.0K Apr 18  2019 jdk
drwxr-xr-x.  8 oracle oinstall   82 Apr 18  2019 javavm
drwxr-x---. 13 oracle oinstall 4.0K Apr 18  2019 inventory
drwxr-xr-x.  2 oracle oinstall 8.0K Apr 18  2019 bin
drwxr-xr-x. 10 oracle oinstall 4.0K Apr 18  2019 install
drwxrwxr-x.  3 oracle oinstall   22 Oct 28 11:38 ..
drwxrwxr-x. 68 oracle oinstall 4.0K Oct 28 13:26 .
[oracle@oldblab-db1 dbhome_1]$ cd OPatch/
[oracle@oldblab-db1 OPatch]$ ./opatch version
OPatch Version: 12.2.0.1.17

OPatch succeeded.
[oracle@oldblab-db1 OPatch]$ cd ../
[oracle@oldblab-db1 dbhome_1]$ rm -rf OPatch/
[oracle@oldblab-db1 dbhome_1]$ unzip /u01/app/oracle/software/p6880880_190000_Linux-x86-64.zip
…
[oracle@oldblab-db1 dbhome_1]$ cd OPatch/
[oracle@oldblab-db1 OPatch]$ ./opatch version
OPatch Version: 12.2.0.1.54

OPatch succeeded.
```

#### h. Oracle home: apply the OJVM RU, the GI RU and the JDK patch

The same three patches as d, with `runInstaller` instead of `gridSetup.sh`.

```bash
# oldblab-db1 as oracle  (sudo su - oracle)
cd /u01/app/oracle/product/19.0.0/dbhome_1
./runInstaller -applyRU /u01/app/oracle/software/40121665/39803650/ -silent
./runInstaller -applyRU /u01/app/oracle/software/40121665/39922757/ -silent
./runInstaller -applyOneOffs /u01/app/oracle/software/39902051 -silent
```

**Check:** each ends with `Successfully applied the patch.`

**This lab's output:**

```text
[oracle@oldblab-db1 dbhome_1]$ ./runInstaller -applyRU /u01/app/oracle/software/40121665/39803650/ -silent
Preparing the home to patch...
Applying the patch /u01/app/oracle/software/40121665/39803650/...
Successfully applied the patch.

[oracle@oldblab-db1 dbhome_1]$ ./runInstaller -applyRU /u01/app/oracle/software/40121665/39922757/ -silent
Preparing the home to patch...
Applying the patch /u01/app/oracle/software/40121665/39922757/...
Successfully applied the patch.

[oracle@oldblab-db1 dbhome_1]$ ./runInstaller -applyOneOffs /u01/app/oracle/software/39902051 -silent
Preparing the home to patch...
Applying the patch /u01/app/oracle/software/39902051...
Successfully applied the patch.
```

#### i. Oracle home: software-only install, root script and patch list

`INSTALL_DB_SWONLY` installs Enterprise Edition without creating a database; the OS groups map the database's admin roles to the `oracle` user's groups from a.

```bash
# oldblab-db1 as oracle  (sudo su - oracle)
cd /u01/app/oracle/product/19.0.0/dbhome_1
./runInstaller \
  -silent \
  -waitforcompletion \
  -responseFile \
  /u01/app/oracle/product/19.0.0/dbhome_1/install/response/db_install.rsp \
  oracle.install.option=INSTALL_DB_SWONLY \
  UNIX_GROUP_NAME=oinstall \
  ORACLE_HOME=/u01/app/oracle/product/19.0.0/dbhome_1 \
  ORACLE_BASE=/u01/app/oracle \
  oracle.install.db.InstallEdition=EE \
  oracle.install.db.OSDBA_GROUP=dba \
  oracle.install.db.OSOPER_GROUP=oper \
  oracle.install.db.OSBACKUPDBA_GROUP=backupdba \
  oracle.install.db.OSDGDBA_GROUP=dgdba \
  oracle.install.db.OSKMDBA_GROUP=kmdba \
  oracle.install.db.OSRACDBA_GROUP=racdba \
  DECLINE_SECURITY_UPDATES=true
```

**Check:** `Successfully Setup Software with warning(s).` and the request to run `root.sh`.

**This lab's output:**

```text
[oracle@oldblab-db1 dbhome_1]$ ./runInstaller -silent -waitforcompletion -responseFile … DECLINE_SECURITY_UPDATES=true
Launching Oracle Database Setup Wizard...



As a root user, execute the following script(s):
	1. /u01/app/oracle/product/19.0.0/dbhome_1/root.sh

Execute /u01/app/oracle/product/19.0.0/dbhome_1/root.sh on the following nodes: 
[oldblab-db1]


Successfully Setup Software with warning(s).
```

```bash
# oldblab-db1 as root  (after the install above has finished)
/u01/app/oracle/product/19.0.0/dbhome_1/root.sh
```

**This lab's output:**

```text
[root@oldblab-db1 ~]# /u01/app/oracle/product/19.0.0/dbhome_1/root.sh
Check /u01/app/oracle/product/19.0.0/dbhome_1/install/root_oldblab-db1_2026-10-28_16-05-07-235984924.log for the output of root script
```

```bash
# oldblab-db1 as oracle  (sudo su - oracle)
cd /u01/app/oracle/product/19.0.0/dbhome_1/OPatch/
./opatch lspatches
```

**Check:** four patches: JDK, OCW, Database RU and OJVM, all 19.33 / 261020. The DB home has no ACFS, Tomcat or DBWLM: those parts of the GI RU apply only to a Grid home.

**This lab's output:**

```text
[oracle@oldblab-db1 OPatch]$ ./opatch lspatches
39902051;JDK BUNDLE PATCH 19.0.0.0.261020
39922783;OCW RELEASE UPDATE 19.33.0.0.0 (39922783)
39915792;Database Release Update : 19.33.0.0.261020 (39915792)
39803650;OJVM RELEASE UPDATE: 19.33.0.0.261020 (39803650)

OPatch succeeded.
```

#### j. Oracle home: create the gold image

```bash
# oldblab-db1 as oracle  (sudo su - oracle)
mkdir -p /tmp/db-gold
cd /u01/app/oracle/product/19.0.0/dbhome_1
./runInstaller \
  -createGoldImage \
  -destinationLocation /tmp/db-gold \
  -silent
```

**Check:** `Successfully Setup Software.` and the zip's path.

**This lab's output:**

```text
[oracle@oldblab-db1 dbhome_1]$ ./runInstaller -createGoldImage -destinationLocation /tmp/db-gold -silent
Launching Oracle Database Setup Wizard...

Successfully Setup Software.
Gold Image location: /tmp/db-gold/db_home_2026-10-28_04-05-17PM.zip
```

**The two homes side by side** (from e and i):

| Patch | Grid home | Oracle home |
| --- | --- | --- |
| `39915792` Database Release Update 19.33.0.0.261020 | yes | yes |
| `39922783` OCW Release Update 19.33.0.0.0 | yes | yes |
| `39803650` OJVM Release Update 19.33.0.0.261020 | yes | yes |
| `39902051` JDK bundle patch 19.0.0.0.261020 | yes | yes |
| `39922802` ACFS Release Update 19.33.0.0.0 | yes | — |
| `39107855` Tomcat Release Update 19.0.0.0.0 | yes | — |
| `39107825` DBWLM Release Update 19.0.0.0.0 | yes | — |

**For the next RU** (all of this worked, so the 19.33 homes are fine as built): the OJVM RU is meant for database homes, so the Grid home doesn't need `39803650`; and Oracle's OJVM README applies it after the database RU, as a one-off. A one-command form per home for the next RU (not tested in this lab):

```bash
# build host as grid: next RU (untested form)
./gridSetup.sh -applyRU <stage>/<combo>/<GI RU> -applyOneOffs <stage>/<JDK patch> -silent
# build host as oracle: next RU (untested form)
./runInstaller -applyRU <stage>/<combo>/<GI RU> -applyOneOffs <stage>/<combo>/<OJVM RU>,<stage>/<JDK patch> -silent
```

#### k. Name, test and checksum the zips (not run yet)

The operator finds the zips by the names in the `RacDatabase`, so they get names that say what and which RU; `/tmp` is cleaned over time, so they move next to the software.

```bash
# oldblab-db1 as root
mkdir -p /u01/app/oracle/software/gold
mv /tmp/grid-gold/grid_home_2026-10-28_03-48-55PM.zip /u01/app/oracle/software/gold/oracle-gridhome-19.33.zip
mv /tmp/db-gold/db_home_2026-10-28_04-05-17PM.zip /u01/app/oracle/software/gold/oracle-dbhome-19.33.zip
cd /u01/app/oracle/software/gold
chmod 644 oracle-*.zip
unzip -tq oracle-gridhome-19.33.zip; unzip -tq oracle-dbhome-19.33.zip
sha256sum oracle-gridhome-19.33.zip oracle-dbhome-19.33.zip | tee oracle-gold-19.33.sha256
ls -lh
```

**Check:** two `No errors detected in compressed data of …` lines, two checksums and both zips listed. Copy both zips and the `.sha256` file to the PC's stage folder; from there 8.2 copies them to the workers and checks them against this file.

### 8.1 Build the slim image (op-worker1, then op-worker2)

**What the slim image is:** Oracle Linux 9 with the OS packages, users and groups Oracle needs, plus Oracle's own setup scripts, but **no** Oracle software. The operator starts this image and drives the scripts in it; they install Grid and the database from the zips in 8.2 into `/u01`, on the worker's disk. That's why the manual lab's image, built from the OCNE doc's short Containerfile, can't be used here: it doesn't have those scripts.

**Why each line:**

- **`podman-docker`:** Oracle's build script calls `docker`. This package makes `docker` run Podman, which writes into the same image store CRI-O reads (`/var/lib/containers`). `/etc/containers/nodocker` silences its "emulating docker" notice.
- **A sparse clone:** only Oracle's RAC folder of the large `docker-images` repository is downloaded.
- **`-v 19.3.0`:** the 19c folder, which the README says to use for all 19c builds, RUs such as 19.32 included. Its `Containerfile` uses Oracle Linux 9.
- **`-i`:** skip the checksum of install zips; the slim image doesn't contain any.
- **`SLIMMING=true`:** build without the Oracle software.
- **`TMPDIR` on `/scratch`:** Podman's temporary files go to the 80 GB disk instead of the small root disk.

The build downloads Oracle Linux packages and takes about 10–20 minutes. You can run it in op-worker1 and op-worker2 at the same time, in two windows.

```bash
# op-worker1, then op-worker2  (10-20 minutes each; connect: ssh -p 2221 root@127.0.0.1; for op-worker2: ssh -p 2222 root@127.0.0.1)
dnf install -y -q git podman-docker && touch /etc/containers/nodocker
mkdir -p /scratch/image/tmp && rm -rf /scratch/image/docker-images
git clone -q --depth 1 --filter=blob:none --sparse https://github.com/oracle/docker-images.git /scratch/image/docker-images
cd /scratch/image/docker-images && git sparse-checkout set OracleDatabase/RAC/OracleRealApplicationClusters && git log -1 --format='docker-images commit %h, %cd'
cd OracleDatabase/RAC/OracleRealApplicationClusters/containerfiles
export TMPDIR=/scratch/image/tmp
./buildContainerImage.sh -v 19.3.0 -t localhost/oracle/database-rac:19.3.0-slim -i -o '--build-arg SLIMMING=true' > /scratch/image/build.log 2>&1; echo "build exit $?"
tail -8 /scratch/image/build.log
podman images localhost/oracle/database-rac
crictl images | grep database-rac
```

**Check, on each worker:**

- `build exit 0`, and the log ends with `Oracle Database container Image for Real Application Clusters (RAC) version 19.3.0 is ready to be extended` and `--> localhost/oracle/database-rac:19.3.0-slim`;
- `podman images` and `crictl images` both list `localhost/oracle/database-rac` with tag `19.3.0-slim`. `crictl` seeing it proves CRI-O, and so Kubernetes, can start it.

If the build fails, the full log is `/scratch/image/build.log`; paste its last 40 lines (`tail -40 /scratch/image/build.log`).

**This lab's output** (the two image IDs differ because each worker builds its own copy; that's expected):

```text
[root@op-worker1 containerfiles]#
build exit 0
e9302892b20d51de90d6eaba11a31d25a830538ca1c7fc432cc65620ec895556

  Oracle Database container Image for Real Application Clusters (RAC) version 19.3.0 is ready to be extended:

    --> localhost/oracle/database-rac:19.3.0-slim

  Build completed in 168 seconds.

REPOSITORY                     TAG          IMAGE ID      CREATED       SIZE
localhost/oracle/database-rac  19.3.0-slim  e9302892b20d  1 second ago  443 MB
localhost/oracle/database-rac                 19.3.0-slim         e9302892b20d5       443MB

[root@op-worker2 containerfiles]#
build exit 0
ad073d6cdfc02e06a761d0ede9daa43c9972042bdc1e5786cc19752e82ad5b68
  …
    --> localhost/oracle/database-rac:19.3.0-slim

  Build completed in 169 seconds.

REPOSITORY                     TAG          IMAGE ID      CREATED       SIZE
localhost/oracle/database-rac  19.3.0-slim  ad073d6cdfc0  1 second ago  443 MB
localhost/oracle/database-rac                 19.3.0-slim         ad073d6cdfc02       443MB
```

### 8.2 Stage the gold-image zips (from the PC)

**What:** both 19.32 gold-image zips copied from `C:\Users\alpoo\Downloads\oracle-stage` to `/scratch/software/stage` on **both** workers, then checked against the PC's own checksums.

**Why each part:**

- **Both workers:** the operator installs from the stage directory of the worker each RAC pod runs on, and either pod may land on either worker. It mounts the directory as `hostSwStageLocation`.
- **Zipped, not unpacked:** the operator unzips them itself; the `RacDatabase` names them in `gridSwZipFile` and `dbSwZipFile`. Oracle's prerequisites accept a 19.28 or later gold image, and these are 19.32.
- **Mode 755:** the permissions Oracle's prerequisites ask for on the zips.
- **`restorecon`:** gives the files the `container_file_t` label set up in 4f, so the pods may read them under SELinux.
- **Checksums:** 9.6 GB through a NAT port forward is easy to cut short. `sha256sum -c` on each worker compares against the checksums taken on the PC; a truncated or damaged copy fails here instead of an hour into the Grid install.

The copy takes a few minutes per worker. The checksums take about a minute on each side.

```bash
# Git Bash
cd ~/Downloads/oracle-stage
sha256sum oracle-gridhome-19.32.zip oracle-dbhome-19.32.zip | tee /tmp/zips.sha256
for p in 2221 2222; do for f in oracle-gridhome-19.32.zip oracle-dbhome-19.32.zip; do
  for try in 1 2 3; do
    echo "--- port $p: $f (try $try)"
    scp -P $p $f root@127.0.0.1:/scratch/software/stage/ && grep " \*$f$" /tmp/zips.sha256 | ssh -p $p root@127.0.0.1 "cd /scratch/software/stage && sha256sum -c" && break
  done
done; done
for p in 2221 2222; do echo "--- checking port $p"
  ssh -p $p root@127.0.0.1 "hostname; cd /scratch/software/stage && chmod 755 oracle-*.zip && restorecon -F oracle-*.zip && ls -lhZ oracle-*.zip && sha256sum -c" < /tmp/zips.sha256
done
```

**Check:** for `op-worker1` and `op-worker2`, both zips listed with `-rwxr-xr-x`, about 4.8 G and `container_file_t`, and two lines ending in **`OK`**. Each file is checked right after its copy and copied again, up to three times, if the checksum doesn't match: a copy through the NAT port forward can drop just before the end (`lost connection` at 99%). A `FAILED` line in the final check means all three tries failed for that file; paste the output.

**This lab's output (the first run, before the block had its retry loop: the copy to op-worker1 dropped at 99 % and the checksum caught it):**

```text
d02d04276e767d7715006fa3690851f2203ff578ff35e963e18b67b15ddcc917 *oracle-gridhome-19.32.zip
da75d72a2c1491d129e70ac0c3cdbb86c19024d5d80931f0e9c7714d25ef7e5f *oracle-dbhome-19.32.zip
--- copying to port 2221
oracle-gridhome-19.32.zip                      99% 4832MB  57.6MB/s   00:00 ETAlost connection
--- copying to port 2222
oracle-gridhome-19.32.zip                     100% 4864MB  23.1MB/s   03:30
oracle-dbhome-19.32.zip                       100% 4904MB  26.2MB/s   03:06
--- checking port 2221
op-worker1
-rwxr-xr-x. 1 root root system_u:object_r:container_file_t:s0 4.8G Oct 27 19:27 oracle-gridhome-19.32.zip
oracle-gridhome-19.32.zip: FAILED
oracle-dbhome-19.32.zip: FAILED open or read
sha256sum: WARNING: 1 listed file could not be read
sha256sum: WARNING: 1 computed checksum did NOT match
--- checking port 2222
op-worker2
-rwxr-xr-x. 1 root root system_u:object_r:container_file_t:s0 4.8G Oct 27 19:34 oracle-dbhome-19.32.zip
-rwxr-xr-x. 1 root root system_u:object_r:container_file_t:s0 4.8G Oct 27 19:31 oracle-gridhome-19.32.zip
oracle-gridhome-19.32.zip: OK
oracle-dbhome-19.32.zip: OK
```

**This lab's output (op-worker1 again, with the retry loop):**

```text
--- port 2221: oracle-gridhome-19.32.zip (try 1)
oracle-gridhome-19.32.zip                     100% 4864MB 163.4MB/s   00:29
oracle-gridhome-19.32.zip: OK
--- port 2221: oracle-dbhome-19.32.zip (try 1)
oracle-dbhome-19.32.zip                       100% 4904MB  59.0MB/s   01:23
oracle-dbhome-19.32.zip: OK
op-worker1
-rwxr-xr-x. 1 root root system_u:object_r:container_file_t:s0 4.8G Oct 27 19:39 oracle-dbhome-19.32.zip
-rwxr-xr-x. 1 root root system_u:object_r:container_file_t:s0 4.8G Oct 27 19:37 oracle-gridhome-19.32.zip
oracle-gridhome-19.32.zip: OK
oracle-dbhome-19.32.zip: OK
```
