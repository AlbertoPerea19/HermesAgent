# Hermes deployment

Configuration for a personal Hermes Agent (Telegram + MCP) running in Docker. This repo holds only the files that
define the deployment. State and secrets never leave the machine that runs it.

## Layout
- `docker-compose.yml`: hardened container (image pinned by digest, no published ports, capabilities dropped).
- `data/config.yaml`, `data/SOUL.md`: agent configuration and persona.
- `data/skills/`: our own skills (bundled skills come with the image).
- `data/scripts/`: zero-token cron scripts (daily lesson reminder, politics briefing).
- `check.sh`, `check_inner.py`, `spend.sh`: health, regression and spend checks. They make no model calls.
- `deploy.sh` (Mac), `ops/update.sh` (server): safe update flow. `ops/briefing.sh`: preview the politics briefing. `ops/bootstrap-audio.sh`: one-time voice setup on a new server.

## Not in git (by design)
`data/.env`, `data/auth.json`, `data/state.db`, `data/memories/`, `data/cron/`, caches, logs and the notes folder.
See `env.example` for the variables the server needs.

## Update flow
1. Edit and test locally on the Mac.
2. `./deploy.sh "what changed"` commits and pushes.
3. On the server: `cd ~/HermesAgent && ./ops/update.sh`. It re-runs itself as root (`data/` is owned by the container user),
   saves and drops the keys Hermes rewrites in `config.yaml`, refuses to continue on any other local change, fast-forward
   pulls, fixes ownership, restarts only when config, persona or skills changed, then prints the `check.sh` problems.
4. Roll back with `git revert`, `./deploy.sh`, and `./ops/update.sh` again.

Preview the briefing: `./ops/briefing.sh` (prints, does not send) or `./ops/briefing.sh send` (real job, to Telegram).

Hermes upgrades: change the image digest in `docker-compose.yml`, deploy, update, check; revert the digest to roll back.
