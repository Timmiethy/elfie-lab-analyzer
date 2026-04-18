# Elfie Lab Analyzer — Production Deployment Guide

**Stack:** Vercel (frontend) + Akamai Cloud / Linode VPS (backend + Postgres + reverse proxy) + Supabase (auth).

Render is **disintegrated** — no Render-specific config remains. Everything below is provider-agnostic except the Linode VPS provisioning and Vercel project setup.

---

## 0. Pre-flight checklist

- Domain you control (e.g. `elfie.health`). Subdomain plan:
  - `elfie.health` (or `app.elfie.health`) → Vercel (frontend).
  - `api.elfie.health` → Linode VPS (backend).
- Supabase project already created (you have one; reuse it).
- Linode account, $100 credit, SSH key ready (`~/.ssh/id_ed25519.pub`).
- Local: `gh`, `docker`, `vercel` CLIs (`npm i -g vercel`).
- DashScope (Qwen) API key.

---

## 1. Provision Linode VPS (Akamai Cloud)

### 1.1 Create Linode

1. Linode Cloud Manager → **Create → Linode**.
2. **Image:** Debian 12.
3. **Region:** Singapore or your nearest user region.
4. **Plan:** **Shared CPU → Linode 4 GB** (`g6-standard-2`, 2 vCPU, 4 GB RAM, 80 GB SSD, ~$24/mo). Sterling-class 19-page PDFs need >2 GB peak with VLM rendering; 2 GB plan OOMs.
5. **Linode Label:** `elfie-prod-1`.
6. **Root Password:** strong random; you'll disable password auth later.
7. **SSH Keys:** paste your public key.
8. Optional add-ons: **Backups** ($2.40/mo, recommended). Skip Block Storage (artifacts kept on local disk + can be moved later).
9. **Create Linode.** Note the public IPv4.

### 1.2 DNS

In your DNS provider:

```
A  api.elfie.health  →  <linode-ipv4>   TTL 300
```

Apex/`app` will be set later by Vercel.

### 1.3 First SSH + harden

```bash
ssh root@<linode-ipv4>

# Create deploy user
adduser --disabled-password --gecos "" elfie
usermod -aG sudo elfie
mkdir -p /home/elfie/.ssh
cp ~/.ssh/authorized_keys /home/elfie/.ssh/
chown -R elfie:elfie /home/elfie/.ssh
chmod 700 /home/elfie/.ssh && chmod 600 /home/elfie/.ssh/authorized_keys

# Disable root SSH + password auth
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart ssh

# Firewall
apt update && apt install -y ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# Auto-security updates
apt install -y unattended-upgrades
dpkg-reconfigure -fnoninteractive unattended-upgrades

exit
```

Reconnect as `elfie`:

```bash
ssh elfie@<linode-ipv4>
```

### 1.4 Install Docker

```bash
sudo apt update
sudo apt install -y ca-certificates curl gnupg git
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | \
  sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/debian $(lsb_release -cs) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER
exit
```

Re-SSH so the docker group takes effect.

---

## 2. Pull repo + configure secrets

```bash
ssh elfie@<linode-ipv4>
sudo mkdir -p /opt/elfie && sudo chown elfie:elfie /opt/elfie
cd /opt/elfie
git clone https://github.com/<your-org>/elfie-lab-analyzer.git .
git checkout main

cp .env.prod.example .env.prod
```

Edit `.env.prod` (`nano .env.prod`) and set real values:

```bash
POSTGRES_USER=elfie
POSTGRES_PASSWORD=<openssl rand -base64 32>
POSTGRES_DB=elfie_labs

ELFIE_QWEN_API_KEY=sk-...                         # rotate the dev key
ELFIE_QWEN_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1
ELFIE_QWEN_MODEL=qwen-turbo
ELFIE_QWEN_VL_MODEL=qwen3-vl-flash-2026-01-22

ELFIE_IMAGE_BETA_ENABLED=true
ELFIE_MAX_UPLOAD_SIZE_MB=20
ELFIE_MAX_PDF_PAGES=30

ELFIE_SUPABASE_JWT_SECRET=<from Supabase dashboard → Settings → API → JWT Secret>
ELFIE_SUPABASE_URL=https://<project>.supabase.co

ELFIE_DEV_AUTH_BYPASS=false                       # MUST be false in prod
ELFIE_CORS_ORIGINS=["https://app.elfie.health"]   # or your Vercel domain
ELFIE_CORS_ALLOW_CREDENTIALS=true

ELFIE_DEBUG=false
ELFIE_ALLOW_DEBUG_ARTIFACTS=false
```

Lock it down:

```bash
chmod 600 .env.prod
```

Edit `deploy/Caddyfile` and replace `api.example.com` with `api.elfie.health`.

---

## 3. Bring stack up

```bash
cd /opt/elfie
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml logs -f backend
```

Wait for `Application startup complete.` Then in another shell:

```bash
curl -fsS https://api.elfie.health/api/health
curl -fsS https://api.elfie.health/api/health/ready
```

Caddy auto-issues a Let's Encrypt cert on first request to `api.elfie.health`.

If healthy:

```bash
docker compose -f docker-compose.prod.yml ps
```

All three containers `Up` and backend `(healthy)`.

---

## 4. Frontend on Vercel

### 4.1 Install + login

Local machine:

```bash
npm i -g vercel
cd frontend
vercel login
```

### 4.2 Link + first deploy

```bash
vercel link        # answer: new project, scope=your-team, name=elfie-lab-analyzer
vercel env add VITE_API_URL production
# Value: https://api.elfie.health

vercel env add VITE_SUPABASE_URL production
# Value: https://<project>.supabase.co

vercel env add VITE_SUPABASE_ANON_KEY production
# Value: <Supabase Settings → API → anon/public>

vercel env add VITE_DISABLE_API_MOCK production
# Value: true

vercel --prod
```

Vercel will assign a `*.vercel.app` URL. Visit it and confirm:
- Login screen renders.
- Network tab: requests go to `https://api.elfie.health/api/...`.
- After Supabase login, `/api/upload` succeeds with a real `job_id`.

### 4.3 Custom domain

Vercel dashboard → Project → **Domains** → add `app.elfie.health`. Vercel shows DNS records (one CNAME or A). Add them at your DNS provider. Cert provisions in ~1 min.

Update `.env.prod` on the VPS so `ELFIE_CORS_ORIGINS=["https://app.elfie.health"]` matches the real frontend domain, then:

```bash
ssh elfie@<linode-ipv4> "cd /opt/elfie && docker compose -f docker-compose.prod.yml restart backend"
```

---

## 5. Supabase

In Supabase dashboard:

1. **Authentication → URL Configuration:**
   - Site URL: `https://app.elfie.health`
   - Redirect URLs: `https://app.elfie.health/**`
2. **Authentication → Providers:** enable email + (optional) Google/Apple.
3. **Settings → API:** copy `anon/public` key → already in Vercel env. Copy `JWT Secret (HS256 legacy)` → already in `.env.prod` on VPS.

No DB tables in Supabase needed — Elfie's app DB lives in Postgres on the VPS. Supabase is **auth only**.

---

## 6. Smoke test (full e2e)

```bash
# From local machine, with a Supabase access token:
TOKEN=$(curl -s -X POST "https://<project>.supabase.co/auth/v1/token?grant_type=password" \
  -H "apikey: <anon-key>" -H "Content-Type: application/json" \
  -d '{"email":"...", "password":"..."}' | jq -r .access_token)

curl -s -X POST https://api.elfie.health/api/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@pdfs/hard/var_sterling_pathology_two_column_crop.pdf"
# → {"job_id":"...","status":"completed",...}

JOB=<from above>
curl -s -H "Authorization: Bearer $TOKEN" \
  https://api.elfie.health/api/artifacts/$JOB/patient | jq '.support_banner, (.flagged_cards | length)'

# PDF download
curl -s -H "Authorization: Bearer $TOKEN" \
  https://api.elfie.health/api/artifacts/$JOB/patient/pdf -o /tmp/p.pdf
file /tmp/p.pdf   # → PDF document, version 1.4
```

Then click through in the browser at `https://app.elfie.health` and verify:
- Upload → processing → patient artifact shows real analytes (not mock fixtures).
- Export PDF button downloads a server-rendered PDF (not browser print dialog).

---

## 7. Operations

### Logs

```bash
ssh elfie@<linode-ipv4>
cd /opt/elfie
docker compose -f docker-compose.prod.yml logs -f --tail=200 backend
docker compose -f docker-compose.prod.yml logs -f --tail=200 caddy
```

### Update / redeploy

Push to main → on VPS:

```bash
cd /opt/elfie
git pull
docker compose -f docker-compose.prod.yml build backend
docker compose -f docker-compose.prod.yml up -d backend
```

Vercel: `git push` to the branch Vercel watches → auto-deploys.

### Backup Postgres

Linode Backups (enabled in §1.1) snapshots the whole disk. Add a logical pg_dump cron for portability:

```bash
sudo tee /etc/cron.daily/elfie-pgdump >/dev/null <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
TS=$(date +%Y%m%d-%H%M)
docker exec elfie-db-1 pg_dump -U elfie elfie_labs | gzip > /opt/elfie/backups/pg-$TS.sql.gz
find /opt/elfie/backups -name "pg-*.sql.gz" -mtime +14 -delete
EOF
sudo chmod +x /etc/cron.daily/elfie-pgdump
sudo mkdir -p /opt/elfie/backups
```

(Container name may differ; check with `docker ps`.)

### Rotate Qwen key / Supabase JWT secret

Edit `.env.prod` → `docker compose -f docker-compose.prod.yml restart backend`.

### Upload size / page limits

Adjust `ELFIE_MAX_UPLOAD_SIZE_MB` + `ELFIE_MAX_PDF_PAGES` in `.env.prod`. Caddy `max_size 25MB` in `Caddyfile` should be `>= ELFIE_MAX_UPLOAD_SIZE_MB`.

---

## 8. Cost estimate (monthly)

| Item | Plan | $/mo |
|---|---|---|
| Linode 4 GB | g6-standard-2 | ~$24 |
| Linode Backups | optional | ~$2.40 |
| Vercel | Hobby (free) for personal, Pro $20/seat | $0–$20 |
| Supabase | Free tier covers auth | $0 |
| Domain | varies | ~$1 |
| **Total baseline** | | **~$25–$50** |

$100 Akamai credit covers ~3 months. Scale to Linode 8 GB ($48) if VLM throughput becomes the bottleneck.

---

## 9. Hardening checklist before public launch

- [ ] `ELFIE_DEV_AUTH_BYPASS=false` confirmed on VPS (`docker exec elfie-backend-1 env | grep BYPASS`).
- [ ] Qwen key rotated from any key ever committed to git.
- [ ] Supabase JWT secret never logged.
- [ ] CORS allows only the production Vercel domain (no `*`, no localhost).
- [ ] HTTPS enforced (Caddy auto-redirects 80→443).
- [ ] `git log -p .env*` shows no real secrets ever committed (run `gitleaks` if unsure).
- [ ] Daily Postgres dump verified (`ls /opt/elfie/backups`).
- [ ] Linode Backups enabled.
- [ ] Monitoring: at minimum, an external uptime check (UptimeRobot free) on `https://api.elfie.health/api/health`.

---

## 10. Rollback

```bash
cd /opt/elfie
git log --oneline -10                 # find the last good commit
git checkout <good-sha>
docker compose -f docker-compose.prod.yml build backend
docker compose -f docker-compose.prod.yml up -d backend
```

Vercel: dashboard → Deployments → find previous → **Promote to Production**.

---

## Appendix A — File map

| Path | Purpose |
|---|---|
| `docker-compose.prod.yml` | Prod stack: Postgres + backend + Caddy reverse proxy |
| `backend/Dockerfile` | Slim, non-root, fonts + libmagic for production |
| `backend/scripts/docker_start.sh` | Migrations + multi-worker uvicorn |
| `deploy/Caddyfile` | TLS + reverse proxy + sane timeouts for long VLM extractions |
| `.env.prod.example` | Server env template (copy to `.env.prod`, fill, `chmod 600`) |
| `frontend/vercel.json` | Vercel SPA rewrite rules |
| `frontend/.env.example` | Vercel env vars template |
