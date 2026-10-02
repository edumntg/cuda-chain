# Self-hosting: a company server

This procedure installs a plasmon coordinator for a company, connects employee machines,
and sets the rules for when those machines train. It is written for one administrator and
a fleet of 10 to 1,000 machines. For one or two computers at home, use
[HOME-LAB.md](HOME-LAB.md) instead.

## What you get

- A coordinator at `https://plasmon.your-company.com` with the dashboard, the API and the
  scheduler.
- PostgreSQL for state and MinIO for blobs, both in containers, or your own database and
  S3 bucket.
- Automatic TLS from Let's Encrypt through Caddy.
- Login with your identity provider (OpenID Connect) and groups that map to roles, or
  local accounts with invite links.
- A trainer on each employee machine that runs as a user service and follows the org
  policy: availability windows and the battery rule.

## Requirements

- One Linux host with Docker 24 or newer and Docker Compose v2. Start with 4 CPUs, 16 GB
  RAM and 200 GB of disk.
- A DNS name for the host, for example `plasmon.acme.com`, with ports 80 and 443 open from
  the machines that will connect. Port 443 is the only one the trainers use.
- Optional: an OpenID Connect application in your identity provider. You need the issuer
  URL, a client id, a client secret, and the name of the group for administrators. Set the
  redirect URL to `https://plasmon.acme.com/auth/oidc/callback`.
- Optional: an S3 bucket if you do not want the bundled MinIO.

## Step 1: install the CLI and the engine on the server

```bash
curl -fsSL https://raw.githubusercontent.com/edumntg/plasmon/main/install/install.sh | sh
python3 -m pip install "plasmon[engine] @ git+https://github.com/edumntg/plasmon.git"
```

The CLI writes the deployment bundle. The engine is not required on the host after that,
because the containers include it.

## Step 2: write the bundle

With the bundled PostgreSQL and MinIO, and SSO:

```bash
plasmon server init --bundle compose \
    --domain plasmon.acme.com \
    --mode private --org acme \
    --storage minio \
    --sso-issuer https://login.microsoftonline.com/<tenant>/v2.0 \
    --sso-client-id <client id> --sso-client-secret <client secret> \
    --admin-group plasmon-admins
```

With your own database and bucket:

```bash
plasmon server init --bundle compose --domain plasmon.acme.com --mode private --org acme \
    --db "postgresql+psycopg://plasmon:<password>@db.internal:5432/plasmon" \
    --storage "s3://acme-plasmon-blobs@https://s3.eu-central-1.amazonaws.com"
```

The command writes a directory `plasmon-deploy/` with:

| File | Content |
|---|---|
| `docker-compose.yml` | Services `api`, `worker`, `caddy`, and `postgres`, `minio`, `minio-init` when bundled |
| `Caddyfile` | TLS and the reverse proxy for your domain |
| `.env` | Generated secrets: session secret, database password, MinIO keys. Mode 600. |
| `plasmon-server.yaml` | The server configuration |

Review `.env`. If you use an external bucket, set `S3_ACCESS_KEY` and `S3_SECRET_KEY` in it.
If you use SSO, the client secret is in `plasmon-server.yaml` as well; keep the directory
readable only by the administrator.

For a test without a public DNS name, add `--tls-internal`. Caddy then issues a
self-signed certificate, and the trainers need `--insecure` or the Caddy root certificate
in their trust store.

## Step 3: start

```bash
cd plasmon-deploy
docker compose pull
docker compose up -d
docker compose logs -f api worker
```

Caddy requests the certificate on the first HTTPS connection. Open
`https://plasmon.acme.com`. The login page appears.

## Step 4: the first account

With SSO: log in. The first person to log in becomes the owner. Members of the admin
group become admins on their first login.

Without SSO: create the owner from the server:

```bash
docker compose exec api python -m plasmon server bootstrap --owner you@acme.com --config /config/plasmon-server.yaml
```

The command prints a password. Log in with it.

Registration is closed in private mode. Invite people from the **Users** page or with:

```bash
plasmon login --server https://plasmon.acme.com
plasmon users invite --email person@acme.com --role member
```

The command prints a link. The person opens it and creates the account.

## Step 5: set the policy

Open **Settings** or use the command line:

```bash
plasmon policy set --windows "weekdays 19:00-08:00" "weekends 00:00-23:59" --battery pause
plasmon policy show
```

Trainers read the policy at each heartbeat. Outside a window a machine shows
`unavailable` on the dashboard and does not take rounds. A person can make their own
machine stricter with `plasmon trainer start --hours "daily 22:00-06:00"`.

## Step 6: connect the machines

On each employee machine, or with your device management tool:

```bash
curl -fsSL https://raw.githubusercontent.com/edumntg/plasmon/main/install/install.sh | sh
python3 -m pip install "plasmon[engine] @ git+https://github.com/edumntg/plasmon.git"
plasmon login --server https://plasmon.acme.com
plasmon trainer enable
```

On Windows, in PowerShell:

```powershell
irm https://raw.githubusercontent.com/edumntg/plasmon/main/install/install.ps1 | iex
py -m pip install "plasmon[engine] @ git+https://github.com/edumntg/plasmon.git"
plasmon login --server https://plasmon.acme.com
plasmon trainer enable
```

`trainer enable` installs a user service: a systemd user unit on Linux, a launchd agent
on macOS, a scheduled task on Windows. The service starts the trainer at login as the
user, with no administrator rights. Add `--dry-run` to see the file before it is written.
Remove it with `plasmon trainer disable`.

The login step needs the person to confirm a code in the browser once. For a silent
rollout, run `trainer enable` from your management tool and ask people to run
`plasmon login` the first time. The trainer waits and retries until the login exists.

Machines appear on **Fleet** within one heartbeat.

## Step 7: watch the fleet

| View | Dashboard | Terminal |
|---|---|---|
| All machines, live | **Fleet** | `plasmon fleet --watch` |
| One machine, metrics and log | **Fleet**, then the machine | `plasmon fleet show <node> --watch` |
| A machine's log | the machine page | `plasmon fleet logs <node> -f` |
| Server health | **Server** | `plasmon server status --watch` |
| People and roles | **Users** | `plasmon users list` |
| Admin actions | **Users**, audit section | `plasmon audit --since-hours 24` |

Pause, resume and drain a machine from its page or with `plasmon fleet pause|resume|drain <node>`.
Drain lets the machine finish the current round, then stops it.

## Roles

| Role | Can |
|---|---|
| owner | everything, and give the owner role |
| admin | fleet control, users, invites, policy, every job, audit log |
| operator | fleet control, server status, every job, audit log |
| member | submit jobs, lend a machine, see own jobs and machines |
| viewer | aggregate statistics only |

With SSO, set `--admin-group` and `--operator-group` to the groups that give those roles.
Other people become members on their first login.

## Operations

| Task | Command |
|---|---|
| Update | `docker compose pull && docker compose up -d` |
| Back up the database | `docker compose exec postgres pg_dump -U plasmon plasmon > plasmon-$(date +%F).sql` |
| Back up the blobs | copy the `minio-data` volume, or use your bucket's versioning |
| Metrics for Prometheus | `https://plasmon.acme.com/v1/metrics` |
| Health check | `https://plasmon.acme.com/v1/healthz` |
| More API replicas | `docker compose up -d --scale api=3` (one `worker` only) |
| Logs | `docker compose logs -f api worker` |

Retention defaults: heartbeats 24 hours, trainer logs 7 days. Change `retention` in
`plasmon-server.yaml` and restart.

## Credits and chargeback

Credits are off by default. Turn them on to attribute compute to teams, or to pay
volunteers on a public network:

```yaml
credits:
  enabled: true
  fee_pct: 10            # kept by the server, shown as the fee account
  grant_on_register: 0   # welcome credits for a new account
```

- A job sets its price in `budget.credits_per_1k_samples`. Each round moves
  `price × accepted samples / 1000` from the job owner to the owners of the machines
  that trained, weighted by score × samples, minus the fee.
- A job owner needs a positive balance to submit a priced job, and `budget.max_credits`
  or more when that is set. A job stops with `out of credits` when the owner's balance
  reaches zero.
- Admins grant credits on **Credits** or with `plasmon credits grant <email> <amount>`.
- Export movements for chargeback: `plasmon credits export --since-days 30 -o march.csv`
  or the link on the Credits page.

No payment provider is connected. Buying credits with a card or a token transfer is a
later milestone; the entry table and the API are the place to connect one.

## Network and data

- Trainers open connections to the server only. No port is opened on a trainer.
- Datasets, weights and updates stay in your PostgreSQL and your bucket.
- The server makes no outbound call.
- Telemetry from a machine is hardware state and the trainer's own log lines. Nothing else
  on the machine is read.

## Hosting on Railway

Railway builds the container from `deploy/Dockerfile` and gives the service a public
address. One service is enough for a team. The steps:

1. Create a project from the repository. In the service settings, set the variable
   `RAILWAY_DOCKERFILE_PATH` to `deploy/Dockerfile`.
2. Add a volume and mount it at `/data`. The database, the blobs and the server key are
   stored there.
3. Set these variables:

   | Variable | Value |
   |---|---|
   | `PLASMON_PUBLIC_URL` | `https://${{RAILWAY_PUBLIC_DOMAIN}}` |
   | `PLASMON_SESSION_SECRET` | a long random string |
   | `PLASMON_DB_URL` | optional: `${{Postgres.DATABASE_URL}}` when you add a Railway PostgreSQL service. Without it, the server uses SQLite in the volume. |

   The server listens on the port that Railway gives in `PORT`. You do not set a port.
4. Set the health check path to `/v1/healthz` and deploy.
5. Open the public address and register. The first account becomes the owner. Then set
   `PLASMON_OPEN_REGISTRATION=0` and redeploy, so that new people join by invite only.
6. On each machine: `plasmon login https://<your-domain>`, then `plasmon trainer start`.

The dashboard, the API and the CLI use the same address. The server starts with its
defaults when `/data/plasmon-server.yaml` does not exist; the variables above are all
that a Railway deployment needs.

## Problems and solutions

| Problem | Cause | Solution |
|---|---|---|
| The certificate is not issued | Port 80 or 443 closed, or DNS not pointing at the host | Open the ports; check `dig plasmon.acme.com`; read `docker compose logs caddy` |
| `single sign-on is not configured` on the login page | `oidc.issuer` or `client_id` missing | Check `plasmon-server.yaml`, restart `api` |
| SSO login ends with `invalid id token` | Wrong issuer URL or client id | The issuer must match the `iss` claim exactly, including `https://` and no trailing slash |
| A machine shows `unavailable` | Outside a policy window, or on battery | Check **Settings**. The machine's page shows the reason |
| A machine stays `offline` | The service is not running | On the machine: `systemctl --user status plasmon-trainer` (Linux), `launchctl list \| grep plasmon` (macOS), Task Scheduler (Windows) |
