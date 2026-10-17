# Hermes deployment

Configuration for a personal Hermes Agent (Telegram + MCP) running in Docker. This repo holds only the files that
define the deployment. State and secrets never leave the machine that runs it.

## Layout
- `docker-compose.yml`: hardened container (image pinned by digest, no published ports, capabilities dropped).
- `data/config.yaml`, `data/SOUL.md`: agent configuration and persona.
- `data/skills/`: our own skills (bundled skills come with the image).
- `data/scripts/`: zero-token cron scripts (daily lesson reminder, politics briefing).
- `check.sh`, `check_inner.py`, `spend.sh`: health, regression and spend checks. They make no model calls.
- `ops/apply.sh`, `deploy.sh`: safe update flow.

## Not in git (by design)
`data/.env`, `data/auth.json`, `data/state.db`, `data/memories/`, `data/cron/`, caches, logs and the notes folder.
See `env.example` for the variables the server needs.

## Update flow
1. Edit and test locally, then commit.
2. `./deploy.sh` pushes and runs `ops/apply.sh` on the server: refuses to continue if the server has local drift,
   fast-forward pulls, restarts only what changed, then runs `check.sh`.
3. Roll back with `git revert` and another `./deploy.sh`.

Hermes upgrades: change the image digest in `docker-compose.yml`, deploy, run `check.sh`; revert the digest to roll back.
