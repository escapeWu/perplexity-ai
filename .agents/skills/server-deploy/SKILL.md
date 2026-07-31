---
name: server-deploy
description: Deploy perplexity-ai to its configured production server from the latest GitHub main source. Use when the user asks to deploy, publish, update, rebuild, restart, or roll out this project on the server.
---

# Server Deploy

## Target

- Local Git remote: `origin`
- Branch: `main`
- SSH host: `oralce-chunchuan`
- Server directory: `/root/perplexity`
- Remote Git remote: `origin`
- Remote deployment entrypoint: `./deploy/compose.sh`

## Workflow

Perform the following sequence exactly.

1. Confirm the local branch is `main`, review the intended diff, commit only the
   requested files, and push the exact commit.

   ```bash
   git push origin main
   ```

2. Record the local commit and confirm `origin/main` resolves to the same SHA.
   Stop if the push or equality check fails.

   ```bash
   git rev-parse HEAD
   git ls-remote origin refs/heads/main
   ```

3. Require a clean remote tracked worktree, fast-forward the server checkout,
   and verify that the remote commit equals the local commit. Substitute the
   recorded full SHA for `<commit>`.

   ```bash
   ssh oralce-chunchuan \
     "cd /root/perplexity && \
      test -z \"\$(git status --porcelain --untracked-files=no)\" && \
      git pull --ff-only origin main && \
      test \"\$(git rev-parse HEAD)\" = '<commit>'"
   ```

4. Build the application image from that checked-out source on the server,
   replace the running container, wait for health, and verify the service.

   ```bash
   ssh oralce-chunchuan \
     'cd /root/perplexity && ./deploy/compose.sh up'
   ```

5. Recheck health and status after deployment.

   ```bash
   ssh oralce-chunchuan \
     'cd /root/perplexity && \
      ./deploy/compose.sh verify && \
      ./deploy/compose.sh status && \
      docker inspect perplexity-mcp \
        --format "image={{.Image}} status={{.State.Status}} health={{.State.Health.Status}}"'
   ```

## Invariants

- Build the application from the server checkout. Do not pull, publish, or wait
  for a Docker Hub application image.
- Preserve the server `.env`, `token_pool_config.json`, `data/`, and Docker volumes.
- Stop when the remote tracked worktree is dirty; inspect and preserve changes
  instead of overwriting them.
- Never force-push, run `git reset` or `git clean`, run `docker compose down`, or
  delete images or volumes.
- Stop on a failed push, commit mismatch, build, health check, or status check.
- Do not add authorship or attribution trailers unless the user explicitly
  requests them and provides the exact identity.

Report the deployed commit, image ID, `/health` result, and final container state.
