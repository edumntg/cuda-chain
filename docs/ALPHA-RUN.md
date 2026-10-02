# Alpha run: one shared model, many volunteers

This runbook starts the first public plasmon network: one coordinator on a server, one
reference job that everyone trains, and a public dashboard. It is the deployment for the
"closed alpha" phase. Use [SELF-HOSTING.md](SELF-HOSTING.md) for the server steps and this
document for the differences.

## Differences from a company server

| Setting | Company | Alpha |
|---|---|---|
| `--mode` | `private` | `public` |
| Registration | invite only | open; the dashboard has **Create account** |
| Roles | SSO groups | the operators are the first accounts; everyone else is a member |
| Jobs | anyone with a member role | only operators submit during the alpha; members lend machines |
| Data | private | public datasets only |

## Step 1: the server

```bash
plasmon server init --bundle compose --domain alpha.plasmon.example --mode public --org alpha --storage minio
cd plasmon-deploy
docker compose up -d
```

Create your account on the dashboard first. The first account is the owner. Give the
other operators their role on **Users**.

Then close job submission to members for the alpha period. A member role can submit
jobs; to limit this, give volunteers the `viewer` role until they lend a machine, or
leave it open and watch **Jobs**.

## Step 2: the reference job

Use a job that finishes in days, not weeks, on consumer CPUs and GPUs. The MNIST example
is for a first smoke test. For the alpha itself, write a `job.yaml` with:

- `requirements.min_trainers` at 4 or more, so a round waits for several machines.
- `requirements.round_timeout_s` at 600 or more, so a slow home connection completes a
  round.
- `budget.rounds` at a value that gives one to two days at the expected round time.

Submit it from an operator account:

```bash
plasmon login --server https://alpha.plasmon.example
plasmon job submit alpha-job.yaml
```

## Step 3: invite volunteers

Send the dashboard address and these steps:

1. Create an account on the dashboard.
2. Install the CLI and the engine (see the install commands in README).
3. `plasmon login --server https://alpha.plasmon.example`
4. `plasmon trainer enable`

The **Leaderboard** page shows every machine by verified samples and honesty.

## Step 4: watch

- `plasmon fleet --watch` for the machines.
- `plasmon job watch <id>` or the job page for the loss curve.
- `plasmon server status --watch` for the scheduler, the database and the ledger.
- Add a webhook in `plasmon-server.yaml` to get a message when the job finishes or a
  machine goes to `error`:

```yaml
webhooks:
  - url: https://hooks.slack.com/services/XXX/YYY/ZZZ
    format: slack
    events: [job.completed, job.failed, machine.error]
```

## Step 5: publish

When the job completes, download the weights with `plasmon job download <id>` and publish
them with the loss curve, the rounds table and the ledger export. The ledger lists every
accepted and rejected update by node id.

## Exit criteria for the alpha

- The reference job reaches its target loss.
- No round was lost to a coordinator restart (the scheduler resumes from the database).
- At least one seeded misbehaving trainer was rejected on the job page.
- The dashboard, the CLI and the trainer service worked on Linux, macOS and Windows
  machines of volunteers.
