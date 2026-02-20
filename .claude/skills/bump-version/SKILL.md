---
name: bump-version
description: Bump project version, update changelogs, commit, tag, and push. Use when the user wants to release a new version (e.g. "bump v1.x.0", "release version x").
---

# Bump Version Skill

## Steps

### 1. Determine new version
- User provides target version (e.g. `v1.9.0`)
- Strip the `v` prefix for file edits

### 2. Update version files
- `pyproject.toml`: update `version = "x.x.x"`
- `perplexity/server/web/package.json`: update `"version": "x.x.x"` — Vite reads this via `vite.config.ts` to inject `__APP_VERSION__` into the frontend build, which displays as `MANAGER_vX.X.X` in the admin UI

### 3. Update changelogs
Add a new entry at the top of the changelog section in **both** files:

**README.md** — under `## Changelog`:
```
+ **<YYYY-MM-DD>**: v<VERSION> — <summary in English>
```

**README-zh.md** — under `## 更新记录`:
```
+ **<YYYY-MM-DD>**：v<VERSION> — <summary in Chinese>
```

Use today's date. Summarize the changes since the last version based on recent commits or what the user describes.

### 4. Build frontend
```bash
cd perplexity/server/web && npm run build
```

- If build **succeeds**: proceed to commit.
- If build **fails**: fix all TypeScript/lint errors in `perplexity/server/web/src/`, then re-run the build until it passes. Do not proceed to commit until the build is green.

The `dist/` folder is gitignored — do not force-add it.

### 5. Commit
Stage only source files (never `dist/`):
```bash
git add pyproject.toml README.md README-zh.md \
  perplexity/server/web/package.json \
  perplexity/server/web/src/
```
Also stage any other modified source files relevant to the release.

Commit message format:
```
feat: v<VERSION> - <short summary>

<bullet points of key changes>

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

### 6. Tag and push
```bash
git tag v<VERSION>
git push origin main
git push origin v<VERSION>
```

## Notes
- Always confirm the changelog summary with the user if the changes aren't obvious
- If the build fails, fix errors before committing
- Do not amend previous commits — always create a new commit
