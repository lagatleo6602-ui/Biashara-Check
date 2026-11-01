# Deploying Biashara Check

There are two ways to run Biashara Check for real users:

| | A. Laptop + ngrok | B. Cloud server |
| --- | --- | --- |
| Good for | Demonstrations, the supervised pilot | Owners using it any time, live M-Pesa |
| Address | `https://your-name.ngrok-free.dev` | `https://biasharacheck.co.ke` (your domain) |
| Available | Only while the laptop, XAMPP and ngrok are running | Always |
| Cost | Free | About KES 700–1,500 a month for a small server, plus about KES 1,000 a year for a `.co.ke` domain |
| Visitors see | ngrok's warning page once in the browser | The app straight away |

---

## A. Laptop + ngrok

This is the current set-up, described in the README.

1. Start MySQL in XAMPP.
2. Double-click `start-with-ngrok.bat`.
3. In `.env`, set `APP_URL` to your ngrok address so links in emails and SMS work.
4. Keep the laptop awake and on power. In Windows Settings → System → Power, set *Sleep* to **Never** while plugged in.
5. Run `backup.bat` every day, or schedule it (see the README).

---

## B. Cloud server (Ubuntu 24.04)

### 1. What you need

- A small Linux server (VPS) with 2 GB RAM, 1 vCPU and 25 GB disk. Kenyan hosts (for example Truehost or HostPinnacle) keep the data in Kenya. International ones (DigitalOcean, AWS Cape Town) are also fine if your ethics approval and data-protection notice allow data outside Kenya.
- A domain, for example `biasharacheck.co.ke`, from a KENIC-accredited registrar.
- SSH access to the server as a user with `sudo`.

### 2. Point the domain at the server

At the registrar, add an **A record** for `biasharacheck.co.ke` (and `www`) with the server's IP address. It can take up to a few hours to work.

### 3. Install the software

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3.12 python3.12-venv mysql-server caddy git
sudo ufw allow OpenSSH && sudo ufw allow 80 && sudo ufw allow 443 && sudo ufw enable
```

### 4. Create the database

```bash
sudo mysql
```
```sql
CREATE DATABASE sme_risk_db CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
CREATE USER 'biashara'@'localhost' IDENTIFIED BY 'a-long-random-password';
GRANT ALL PRIVILEGES ON sme_risk_db.* TO 'biashara'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

To move your laptop's data across, make a backup with `backup.bat`, copy `sme_risk_db.sql` to the server and load it:
```bash
mysql -u biashara -p sme_risk_db < sme_risk_db.sql
```

### 5. Copy the app

```bash
sudo adduser --system --group --home /opt/biashara biashara
sudo -u biashara git clone https://github.com/YOUR-ACCOUNT/sme-risk.git /opt/biashara/app
cd /opt/biashara/app
sudo -u biashara python3.12 -m venv venv
sudo -u biashara venv/bin/pip install -r requirements.txt
```

(No GitHub? Copy the folder with WinSCP instead, leaving out `venv`, `backups` and `__pycache__`.)

**Copy `instance/contact.key` from the laptop** into `/opt/biashara/app/instance/` if you moved the database. Without it, the saved emails and phone numbers can't be read. Then:
```bash
sudo chown -R biashara:biashara /opt/biashara/app/instance && sudo chmod 600 /opt/biashara/app/instance/*
```

### 6. Settings

```bash
sudo -u biashara cp .env.example .env
sudo -u biashara nano .env
sudo chmod 600 .env
```

Change at least:

| Setting | Value on the server |
| --- | --- |
| `DATABASE_URL` | `mysql+pymysql://biashara:a-long-random-password@localhost:3306/sme_risk_db` |
| `COOKIE_SECURE` | `true` |
| `APP_URL` | `https://biasharacheck.co.ke` |
| `MPESA_CALLBACK_URL` | `https://biasharacheck.co.ke` (there's no ngrok on the server) |
| `MPESA_ENV`, keys, `MPESA_SHORTCODE`, `MPESA_PASSKEY` | Live values after Safaricom's go-live approval (see step 10) |
| `SMTP_*`, `TEXTBEE_*` or `AT_*` | As on the laptop |
| `ADMIN_SIGNUP_CODE` | Only if this is a fresh database without an admin |

### 7. Run the app as a service

Create `/etc/systemd/system/biashara.service`:

```ini
[Unit]
Description=Biashara Check
After=network.target mysql.service

[Service]
User=biashara
WorkingDirectory=/opt/biashara/app
ExecStart=/opt/biashara/app/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now biashara
sudo systemctl status biashara        # should say active (running)
journalctl -u biashara -f             # the server window: emails and errors appear here
```

Use **one worker**. The monthly reminders run inside the app, and two workers would each run them. They would still skip owners who were already reminded, but a race could send a reminder twice.

### 8. HTTPS with Caddy

Replace `/etc/caddy/Caddyfile` with:

```
biasharacheck.co.ke, www.biasharacheck.co.ke {
    reverse_proxy 127.0.0.1:8000
    encode gzip
    header Strict-Transport-Security "max-age=31536000"
}
```

```bash
sudo systemctl reload caddy
```

Caddy gets and renews the https certificate by itself. Open https://biasharacheck.co.ke/login.

### 9. Train the model on the server

The trained model isn't part of the code. Train it once: either Admin → **Risk model** → **Train the model**, or:
```bash
cd /opt/biashara/app && sudo -u biashara venv/bin/python -m ml.train
```

### 10. Live M-Pesa (Daraja go-live)

1. Register a Paybill or Till with Safaricom (business registration documents needed).
2. On developer.safaricom.co.ke, **Go Live** with that shortcode. Safaricom emails the production consumer key, secret and passkey.
3. Set `MPESA_ENV=production`, the keys, `MPESA_SHORTCODE`, `MPESA_PASSKEY` (and `MPESA_TILL` for Buy Goods), and `MPESA_CALLBACK_URL`. Restart: `sudo systemctl restart biashara`.
4. Admin → **Check M-Pesa connection**, then **Test callback address**, then pay KES 300 yourself as a test.

### 11. Daily backups on the server

Create `/opt/biashara/backup.sh`:

```bash
#!/bin/sh
set -e
D=/opt/biashara/backups/$(date +%F_%H%M)
mkdir -p "$D"
mysqldump --single-transaction sme_risk_db > "$D/sme_risk_db.sql"
cp /opt/biashara/app/instance/* /opt/biashara/app/.env "$D/"
ls -1dt /opt/biashara/backups/* | tail -n +15 | xargs -r rm -rf
```

```bash
sudo chmod 700 /opt/biashara/backup.sh
sudo crontab -e        # add the line below: every day at 20:00 Nairobi time (server set to Africa/Nairobi)
0 20 * * * /opt/biashara/backup.sh
sudo timedatectl set-timezone Africa/Nairobi
```

Root can run `mysqldump` without a password on Ubuntu. Copy the backups off the server regularly too, for example with WinSCP or `rclone` to Google Drive.

### 12. Updating the app

```bash
cd /opt/biashara/app
sudo -u biashara git pull
sudo -u biashara venv/bin/pip install -r requirements.txt
sudo systemctl restart biashara
```

New database columns are added automatically at start-up. Owners get the new pages straight away: the phone app always checks for new pages and scripts first.

---

## Checklist before inviting owners

- [ ] `https://` address works, with a padlock
- [ ] `COOKIE_SECURE=true`, and `.env` and `instance/` readable only by the app user
- [ ] Email works (Admin → Email and SMS → send a test)
- [ ] SMS works (test send)
- [ ] M-Pesa: connection check and callback test pass
- [ ] Model trained (Admin → Risk model shows the model and its metrics)
- [ ] Backups run, and one restore has been tried
- [ ] `APP_URL` set, so links in messages open the site
- [ ] The privacy notice and consent wording match the ethics approval
