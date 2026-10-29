## Phase 9: The secrets

**Result of this phase:** two Kubernetes Secrets in namespace `rac`: `ssh-key-secret` with an SSH key pair the RAC pods use to reach each other, and `db-user-pass` with the database password, encrypted.

**Why the operator wants them:** Grid's and the database's installers run on one RAC node and work on the other over SSH, so both pods need the same key pair from the start; the manual lab created the same `ssh-key-secret` in its 10.2. The password is for `SYS`, `SYSTEM`, the PDB admin and ASM. The operator only takes it encrypted: the Secret holds the encrypted password file and the private key that decrypts it, and the setup scripts inside the pod decrypt it there.

### 9.1 The SSH key pair (op-controlplane)

The key names inside the Secret, `ssh-privkey` and `ssh-pubkey`, are the ones the `RacDatabase` will refer to.

```bash
# op-controlplane  (connect: ssh -p 2220 root@127.0.0.1)
install -d -m 700 /root/rac-op/secrets
rm -f /root/rac-op/secrets/id_rsa /root/rac-op/secrets/id_rsa.pub
ssh-keygen -q -t rsa -b 4096 -N "" -C "rac-op RAC nodes" -f /root/rac-op/secrets/id_rsa
kubectl -n rac delete secret ssh-key-secret --ignore-not-found
kubectl -n rac create secret generic ssh-key-secret \
  --from-file=ssh-privkey=/root/rac-op/secrets/id_rsa --from-file=ssh-pubkey=/root/rac-op/secrets/id_rsa.pub
kubectl -n rac get secret ssh-key-secret -o jsonpath='{.data}' | grep -o '"ssh-p[a-z]*key"'
```

**Check:** `"ssh-privkey"` and `"ssh-pubkey"`.

**This lab's output:**

```text
secret/ssh-key-secret created
"ssh-privkey"
"ssh-pubkey"
```

### 9.2 The database password, encrypted (op-controlplane)

**What happens to the password:** you type it twice at a hidden prompt. It lives only in a shell variable, is piped straight into OpenSSL, and is encrypted with a new RSA key; the variable is then cleared. It's never written to a file, the screen or this guide. The `-pkeyopt` settings are the operator's default (`rsa_padding_mode:oaep;rsa_oaep_md:sha256;rsa_mgf1_md:sha256`), which the `RacDatabase` names again in Phase 11.

**Password rules:** 8–30 characters with at least one upper-case letter, one lower-case letter and one digit, and only letters, digits, `_`, `#` and `-`. Those rules satisfy Oracle's password checks; leaving out quotes, spaces, `@` and `$` keeps them out of trouble in the operator's shell scripts.

```bash
# op-controlplane  (you type the password twice; connect: ssh -p 2220 root@127.0.0.1)
cd /root/rac-op/secrets
while :; do
  read -rsp "Database password: " PW; echo; read -rsp "Same again: " PW2; echo
  if [ "$PW" != "$PW2" ]; then echo "They differ; try again."; continue; fi
  if [[ ${#PW} -ge 8 && ${#PW} -le 30 && "$PW" =~ [A-Z] && "$PW" =~ [a-z] && "$PW" =~ [0-9] && "$PW" =~ ^[A-Za-z0-9_#-]+$ ]]; then break; fi
  echo "8-30 characters, upper and lower case and a digit, only letters, digits, _ # -; try again."
done
rm -f key.pem key.pub pwdfile.enc
openssl genrsa -out key.pem 2>/dev/null && openssl rsa -in key.pem -pubout -out key.pub 2>/dev/null
printf '%s\n' "$PW" | openssl pkeyutl -encrypt -pubin -inkey key.pub -out pwdfile.enc \
  -pkeyopt rsa_padding_mode:oaep -pkeyopt rsa_oaep_md:sha256 -pkeyopt rsa_mgf1_md:sha256
LEN=$(( ${#PW} + 1 )); unset PW PW2
GOT=$(openssl pkeyutl -decrypt -inkey key.pem -in pwdfile.enc -pkeyopt rsa_padding_mode:oaep -pkeyopt rsa_oaep_md:sha256 -pkeyopt rsa_mgf1_md:sha256 | wc -c)
[ "$GOT" -eq "$LEN" ] && echo "OK: pwdfile.enc decrypts to the password you typed ($LEN bytes with the newline)" || echo "STOP: decrypt test failed"
chmod 600 key.pem pwdfile.enc
kubectl -n rac delete secret db-user-pass --ignore-not-found
kubectl -n rac create secret generic db-user-pass --from-file=pwdfile.enc --from-file=key.pem
kubectl -n rac get secret db-user-pass -o jsonpath='{.data}' | grep -o '"[a-z.]*"' 
```

**Check:** `OK: pwdfile.enc decrypts…` (only the length is shown, never the password), then `"key.pem"` and `"pwdfile.enc"`. Remember the password: it's the one for `SYS`, `SYSTEM` and the PDB admin when you connect in Phase 12.

**Where the files stay:** `/root/rac-op/secrets` on op-controlplane, readable only by root. To change the password later, run 9.2 again and recreate the database.

**This lab's output (the byte count is left out here on purpose: it gives away the password's length):**

```text
Database password:
Same again:
OK: pwdfile.enc decrypts to the password you typed (NN bytes with the newline)
secret/db-user-pass created
"key.pem"
"pwdfile.enc"
```
