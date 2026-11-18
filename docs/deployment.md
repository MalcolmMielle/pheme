# Deploying to your own server

These steps assume a fresh Linux server (a "VPS" from any provider) with a
domain name pointing at it. Everything below is copy-paste — no coding
required. Replace `reviews.example.com` and `malcolm` with your own domain
and server username.

## 1. What you need before you start

- A server with a public IP address that you can SSH into (1 GB RAM is
  enough to start).
- A domain name whose **A record** points at that IP: in your domain
  registrar's DNS settings, add `reviews.example.com → <your server IP>`.
  (DNS can take minutes to hours to propagate.)
- Ports **80 and 443** open in your provider's firewall / security group.

## 2. Install the tools

SSH into the server, then:

```bash
# git + sqlite3 (sqlite3 is used for backups)
sudo apt update
sudo apt install -y git sqlite3 curl

# uv — installs and manages Python 3.13 for you
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc   # or log out and back in

# Node.js 20+ — needed once to build the map frontend
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash -
sudo apt install -y nodejs

# Caddy — web server that provides HTTPS automatically (free certificate)
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
```

## 3. Get the code and build it

```bash
git clone https://forge.mielle.dev/MielleLabs/pheme.git pheme
cd pheme
uv sync                                  # backend dependencies
cd react-app && npm ci && npm run build && cd ../..   # map frontend
```

Or install the published package from PyPI instead — its wheel already
bundles the built interface (`react-app/dist`), so the `npm run build` step
is not needed:

```bash
uv tool install pheme-reviews
# then continue at step 4 (create the .env in the directory you run from)
```

## 4. Create the production `.env`

```bash
cp .env.example .env
uv run python -c "import secrets; print(secrets.token_hex(32))"  # copy the output
```

Edit `.env` (`nano .env`) and set:

```dotenv
BASE_URL=https://reviews.example.com
HOST=127.0.0.1
PORT=8000
RELOAD=false
PROXY_HEADERS=true
DATABASE_PATH=/home/malcolm/pheme/data/reviews.db
SECRET_KEY=<the random key you just generated — do NOT reuse your dev key>
REGISTRATION_MODE=invite
```

`BASE_URL` is the public address other federated servers use
to find you (must be `https://`); the app itself only listens on
`127.0.0.1:8000`, so only the local Caddy server can reach it;
`PROXY_HEADERS=true` tells the app to trust Caddy's `X-Forwarded-For` header
so login rate-limiting works per real visitor; `SECRET_KEY` signs login
sessions — keep it secret and never commit it; `REGISTRATION_MODE=invite`
means only people with an invite link can register (you create invite links
from the admin panel after logging in).

## 5. HTTPS + security headers (Caddy)

Write `/etc/caddy/Caddyfile`:

```caddy
reviews.example.com {
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
        Referrer-Policy "strict-origin-when-cross-origin"
    }
    reverse_proxy 127.0.0.1:8000
}
```

```bash
sudo systemctl reload caddy
```

Caddy automatically obtains and renews a free HTTPS certificate (Let's
Encrypt). HTTPS is required — other federated servers only talk to you over
`https://`.

## 6. Keep the app running (systemd)

Create `/etc/systemd/system/pheme.service`:

```ini
[Unit]
Description=Pheme — federated reviews
After=network.target

[Service]
Type=simple
User=malcolm
WorkingDirectory=/home/malcolm/pheme
ExecStart=/home/malcolm/.local/bin/uv run pheme
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now pheme
sudo systemctl status pheme   # should say "active (running)"
```

The app loads `.env` from its working directory automatically.

## 7. Firewall

Only ports 80/443 need to be public — port 8000 stays internal:

```bash
sudo apt install -y ufw
sudo ufw allow OpenSSH
sudo ufw allow 80
sudo ufw allow 443
sudo ufw enable
```

## 8. Create your admin account (one-time)

Run this **immediately after starting the service**, before sharing the URL —
the endpoint works only once, but anyone on the internet could hit it first:

```bash
curl -X POST https://reviews.example.com/api/bootstrap \
  -d "username=admin&display_name=Admin&password=<choose-a-strong-password>"
```

The first account automatically becomes the admin. Then log in at
**<https://reviews.example.com/login>**. With `REGISTRATION_MODE=invite`,
create invite links for other people from the admin panel on your profile
page.

## 9. Backups

The database is SQLite in WAL mode, so use the `.backup` command — copying
the `.db` file directly can miss the latest changes:

```bash
mkdir -p ~/backups
crontab -e
```

Add this line (backs up daily at 03:00):

```
0 3 * * * sqlite3 /home/malcolm/pheme/data/reviews.db ".backup '/home/malcolm/backups/reviews.db'"
```

## 10. Check that it works

```bash
curl https://reviews.example.com/api/meta
curl "https://reviews.example.com/.well-known/webfinger?resource=acct:admin@reviews.example.com"
```

Both should return JSON. Then open **<https://reviews.example.com>** in a
browser — you should see the map.

## Updating later

```bash
cd ~/pheme
git pull
uv sync
cd react-app && npm ci && npm run build && cd ..
sudo systemctl restart pheme
```

Also keep the server itself updated: `sudo apt update && sudo apt upgrade`.
