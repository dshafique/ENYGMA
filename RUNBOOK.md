# ENYGMA — runbook

Every block says which machine it runs on. **Nothing here is run by an agent.** The
agent never invokes `sudo`; these are handed to the operator to run.

---

## 0. See it running, in about two minutes

Runs on: **your machine**. Nothing here touches the Spark and nothing is permanent.

### Windows, PowerShell

```powershell
Expand-Archive .\enygma.zip -DestinationPath .
Set-Location .\enygma
.\quickstart.cmd
```

Note `;` or separate lines rather than `&&`: Windows PowerShell 5.1 has no `&&`.

Use `quickstart.cmd`, not the `.ps1` directly. The `.cmd` is a two-line wrapper that
runs the script with `-ExecutionPolicy Bypass` **for that one script only**, so an
unsigned script runs without changing anything on the machine.

If it says no usable Python was found: install 3.10 or newer from python.org, tick
**Add python.exe to PATH** in the installer, and open a new PowerShell. If typing
`python` opens the Microsoft Store, turn the alias off under
Settings → Apps → Advanced app settings → App execution aliases.

### macOS or Linux

```bash
unzip enygma.zip && cd enygma
./quickstart.sh
```

It makes a venv, installs the dependencies, writes a local `.env` with a fresh
secret, runs the lint and the tests, and starts the app on
`http://localhost:4073`.

Open `/lock`, create a passkey, then drop an audio file on `/meetings`. With
`ENYGMA_PIPELINE=stub` the transcript is placeholder text and costs nothing, which
is the point: the whole flow works before any key exists.

**Browsers treat `localhost` as a secure origin**, so passkeys work there over plain
http. That is why the generated `.env` sets `ENYGMA_RP_ID=localhost`.

### A public URL in one more minute

```powershell
.\quickstart.cmd -Tunnel          # Windows
```
```bash
./quickstart.sh --tunnel          # macOS or Linux
```

On Windows, `winget install --id Cloudflare.cloudflared` first.

`cloudflared` prints a random `https://something.trycloudflare.com` address that
anyone can open. Good for showing someone; not for keeping.

> **A passkey is bound to one origin.** A passkey created on `localhost` will not
> work on `trycloudflare.com`, and neither will work on `enygma.arkhm.io`. Set
> `ENYGMA_RP_ID` and `ENYGMA_ORIGIN` to whatever hostname you are actually using and
> restart before enrolling. Moving to the real domain later means enrolling once
> more, which takes ten seconds and is not a bug.

### enygma.arkhm.io from your own machine, in about ten minutes

Runs on: **your machine**. The URL answers whenever your PC is on, which is the
trade against putting it on the Spark. Nothing is exposed on your router: a tunnel
dials out to Cloudflare rather than accepting connections.

```powershell
winget install --id Cloudflare.cloudflared
# open a NEW PowerShell so the PATH updates
.\tunnel.cmd
```

It logs in through your browser, which is one click since you are already signed in;
creates the tunnel; writes `config.yml`; creates the DNS record; and repoints `.env`
at the public origin. Then two windows:

```powershell
.\run.ps1
cloudflared tunnel run enygma
```

**Your localhost passkey will not work on the new origin.** Enrol once more at
`https://enygma.arkhm.io`. That is the origin binding working, and it is the same
mechanism that makes a PHNTM cookie useless against ENYGMA. `.env.backup` holds the
local settings if you want to go back.

This is a stepping stone. Sections 1 to 6 below put it on the Spark, which is always
on and is where it belongs.

---

## The short version: one script on the Spark

Sections 1, 2, 3 and 5 below are automated and idempotent. From your Windows machine:

```powershell
scp $HOME\Code\enygma.zip you@spark-4d80:~/
ssh you@spark-4d80
```

Then on the Spark:

```bash
mkdir -p ~/enygma-release && cd ~/enygma-release
unzip -o ~/enygma.zip && cd enygma
sudo bash deploy/install-on-spark.sh
```

It creates the `enygma` user, copies the code, builds the venv, writes a `.env` with
a fresh secret at mode 600, locks the home to 750 and the data and uploads
directories to 700, runs the migrations, the token lint and the tests, installs the
systemd unit, starts it, and then **proves** rather than assumes: healthz answers,
the memory ceiling is really in force, and no other account can read the database,
the audio or the secret.

It deliberately does not touch the cloudflared config or the disk ceiling. Those are
two more scripts, run in this order:

```bash
sudo bash deploy/add-tunnel-route.sh      # enygma.arkhm.io, safely
sudo bash deploy/disk-ceiling.sh 200      # 200GB, before the first upload
```

`add-tunnel-route.sh` backs the config up, inserts the rule above the catch-all,
validates it, and then **prints where every existing hostname routes and waits for
you to confirm** before it restarts anything. If validation fails it restores the
backup and stops. If the other hostnames stop answering afterwards, it tells you the
one command that undoes it.

Re-running it is safe. An existing `.env` is left alone, and `data/` and `uploads/`
are never overwritten.

---

## 1. Create the unix user

Runs on: **spark-4d80**, as a user with sudo.

Isolation is enforced by filesystem permissions, not by remembering to keep two
directories apart. A folder under `arkhm` is not isolation.

```bash
sudo adduser --disabled-password --gecos "" enygma
sudo mkdir -p /home/enygma/app
sudo chown -R enygma:enygma /home/enygma
```

Verify, rather than trusting that it worked:

```bash
id enygma
sudo -u enygma test -w /home/enygma/app && echo "writable by enygma"
sudo -u arkhm test -r /home/enygma/app/data 2>/dev/null && echo "PROBLEM: arkhm can read it"
```

The last line should print nothing.

## 2. Put the code in place

Runs on: **spark-4d80**, as the operator.

```bash
sudo -u enygma git clone <repo> /home/enygma/app
cd /home/enygma/app
sudo -u enygma python3 -m venv .venv
sudo -u enygma .venv/bin/pip install -r requirements.txt
```

## 3. Configure

Runs on: **spark-4d80**, as `enygma`.

```bash
sudo -u enygma cp .env.example .env
sudo -u enygma python3 -c "import secrets; print(secrets.token_urlsafe(48))"
sudo -u enygma nano .env      # paste the secret, set the port, the Gemini key, the token
sudo chmod 600 /home/enygma/app/.env
```

`.env` is never committed. Neither is `*.db`, `uploads/`, `transcripts/`,
`summaries/`, `backups/` or any audit log. That is already in `.gitignore`; check it
before the first push rather than after.

## 4. Disk ceiling

Runs on: **spark-4d80**, as a user with sudo.

The filesystem is shared. A runaway backfill on ENYGMA's side eats space PHNTM needs,
and SQLite behaves badly on a full disk. Set this **before first ingest**, not after.

If the filesystem supports quotas:

```bash
sudo quotaon -ug /
sudo setquota -u enygma 209715200 220200960 0 0 /   # 200 GB soft, 210 GB hard
sudo quota -u enygma
```

If it does not, a disk alarm is the minimum:

```bash
sudo tee /etc/cron.hourly/enygma-disk >/dev/null <<'EOS'
#!/bin/sh
USED=$(du -sk /home/enygma | cut -f1)
[ "$USED" -gt 209715200 ] && echo "enygma over 200GB: ${USED}k" | logger -t enygma-disk
EOS
sudo chmod +x /etc/cron.hourly/enygma-disk
```

## 5. The service

Runs on: **spark-4d80**, as a user with sudo.

```bash
sudo cp /home/enygma/app/deploy/enygma.service /etc/systemd/system/enygma.service
sudo systemctl daemon-reload
sudo systemctl enable --now enygma
systemctl status enygma --no-pager
```

Confirm the ceiling actually applied. A unit file that says `MemoryMax` and a cgroup
that enforces it are two different facts:

```bash
systemctl show enygma -p MemoryMax
curl -s http://127.0.0.1:4073/healthz
```

## 6. enygma.arkhm.io

Runs on: **spark-4d80**, as the operator. You own `arkhm.io`, so this is a DNS
record and an ingress rule, not a purchase.

A subdomain is a separate origin: separate cookies, separate service worker,
separate storage, separate installable app, zero code changes. The cost is one DNS
record.

**If cloudflared already serves arkhm.io from this box**, which the handoff says it
does, add a second hostname to the tunnel you already have:

```bash
# Name of the existing tunnel:
cloudflared tunnel list

# Point the subdomain at it. This creates the CNAME for you.
cloudflared tunnel route dns <tunnel-name> enygma.arkhm.io

sudo nano /etc/cloudflared/config.yml
```

```yaml
ingress:
  - hostname: enygma.arkhm.io
    service: http://127.0.0.1:4073
  - hostname: arkhm.io
    service: http://127.0.0.1:4063
  - service: http_status:404
```

```bash
sudo systemctl restart cloudflared
curl -s https://enygma.arkhm.io/healthz
```

Expect `{"ok":true,"app":"enygma","port":4073}`.

**Then point the app at its real origin**, or the passkey will refuse to enrol:

```bash
sudo -u enygma nano /home/enygma/app/.env
#   ENYGMA_RP_ID=enygma.arkhm.io
#   ENYGMA_ORIGIN=https://enygma.arkhm.io
#   ENYGMA_INSECURE_COOKIES=0
sudo systemctl restart enygma
```

**If you would rather not touch the existing tunnel**, a second one is fine and
keeps the two apps independent, which is the whole theme of this document:

```bash
cloudflared tunnel login
cloudflared tunnel create enygma
cloudflared tunnel route dns enygma enygma.arkhm.io
# then a config.yml with a single ingress rule to 127.0.0.1:4073
sudo cloudflared service install
```

## 7. Prove the origins are separate

Runs on: **any machine**. This is step 5 of the handoff and it is the point of all
of the above.

```bash
# Sign in to PHNTM in a browser, copy its session cookie value, then:
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "Cookie: session=<the PHNTM cookie value>" \
  https://enygma.arkhm.io/auth/devices
```

**Expect 401.** Anything else means the isolation is not real and nothing else should
be built until it is.

Two more checks worth doing once:

```bash
# The ENYGMA cookie must carry no Domain attribute.
curl -sI https://enygma.arkhm.io/lock | grep -i set-cookie

# The two databases must be different files, owned by different users.
sudo ls -la /home/enygma/app/data/enygma.db /home/arkhm/*/notes.db
```

## 8. Android, before Yahya installs it

Runs on: **spark-4d80**.

Without this the passkey works in Chrome and silently fails inside the installed
app, on the exact device he uses.

```bash
sudo -u enygma mkdir -p /home/enygma/app/src/static/.well-known
sudo -u enygma nano /home/enygma/app/src/static/.well-known/assetlinks.json
```

```json
[{
  "relation": ["delegate_permission/common.handle_all_urls",
               "delegate_permission/common.get_login_creds"],
  "target": { "namespace": "android_app",
              "package_name": "io.arkhm.enygma",
              "sha256_cert_fingerprints": ["<the signing fingerprint>"] }
}]
```

```bash
curl -s https://enygma.arkhm.io/.well-known/assetlinks.json | head -3
```

## Routine

```bash
sudo systemctl restart enygma
journalctl -u enygma -f --no-pager
sudo -u enygma sqlite3 /home/enygma/app/data/enygma.db "SELECT version, applied_at FROM schema_migrations"
```

Never `journalctl | grep -i secret` and paste the result anywhere. Keys, tokens,
challenges and recovery codes are never printed, echoed, logged or masked.
