---
name: secrets-hygiene
description: Keep API keys and passwords out of git, and rotate one correctly when it leaks. Sets up .env patterns, .gitignore, a gitleaks pre-commit hook and CI scan, then runs the probe-first rotation flow (probe the leaked key, map every consumer, mint new, swap all consumers, revoke old, re-probe until dead). Use when the user says "I committed my API key", "a key leaked", "GitHub sent a secret scanning alert", "rotate this key", "set up .env", "keep secrets out of git", "add gitleaks", or before a repo goes public.
---

# secrets-hygiene: prevent leaks, and handle the one that happens anyway

Two jobs. **Prevent** (set up once per repo, 10 minutes) and **respond** (when a key leaks). Do the response first if a key is already out.

Bundled tools (all Python 3 stdlib):

- `${CLAUDE_SKILL_DIR}/scripts/scan_secrets.py`: fallback secret scanner (`--staged`, `--worktree`, `--all`, or paths). Redacted output.
- `${CLAUDE_SKILL_DIR}/scripts/probe_key.py`: asks a provider whether a key still authenticates (`LIVE`, `DEAD`, `ERR`).
- `${CLAUDE_SKILL_DIR}/scripts/commit_secret_guard.py`: the plugin hook (runs automatically only when this skill is installed as part of the foundry-builder-kit plugin). It blocks a `git commit` the agent runs when the staged change contains a secret.
- Templates in `${CLAUDE_SKILL_DIR}/templates/`.

## Part 1: prevent

### 1. Where secrets live

| Value | Where it goes |
|---|---|
| Local dev secrets | `.env.local` (or `.env`), gitignored |
| The list of variable names | `.env.example`, committed, values empty |
| Production secrets | the hosting platform's env settings (Vercel, Netlify, Fly, Render), or a secret manager |
| CI secrets | GitHub Actions repository secrets, read as `${{ secrets.NAME }}` |
| Anything in the browser bundle | only values that are public by design (`NEXT_PUBLIC_*`, `VITE_*`). A secret with that prefix is published to every visitor. |

Code reads secrets by name (`process.env.OPENAI_API_KEY`, `os.environ["OPENAI_API_KEY"]`). A literal key in source code is a leak waiting for a push.

### 2. Set it up

```bash
# from the repo root
cat "${CLAUDE_SKILL_DIR}/templates/gitignore-secrets.txt" >> .gitignore
cp "${CLAUDE_SKILL_DIR}/templates/env.example" .env.example   # then edit the names
git rm --cached .env .env.local 2>/dev/null   # stop tracking if they were committed (they stay on disk)
git check-ignore -v .env.local                 # must print the matching .gitignore rule
```

If `git rm --cached` removed a tracked env file, its contents are still in history. Go to Part 2 for every real key in it.

### 3. Scan before every commit (gitleaks)

Install gitleaks: `brew install gitleaks` (macOS), `winget install gitleaks` or `scoop install gitleaks` (Windows), or a release binary from github.com/gitleaks/gitleaks. Then pick one:

- **pre-commit framework:** copy `${CLAUDE_SKILL_DIR}/templates/pre-commit-config.yaml` to `.pre-commit-config.yaml`, then `pre-commit install`.
- **plain git hook:** `cp "${CLAUDE_SKILL_DIR}/templates/pre-commit.sh" .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit`.

Scan what is already there, once:

```bash
gitleaks git --redact -v .            # full git history
gitleaks dir --redact -v .            # the files on disk, including untracked
python3 "${CLAUDE_SKILL_DIR}/scripts/scan_secrets.py" --all   # no gitleaks available
```

Add the CI scan so a teammate without the hook is still caught: copy `${CLAUDE_SKILL_DIR}/templates/secret-scan.yml` to `.github/workflows/secret-scan.yml`. Also turn on GitHub's own secret scanning and push protection (repo Settings, Code security).

### 4. False positives

Mark a line on purpose, and say why in the same comment:

```python
TEST_FIXTURE = "sk-test-not-a-real-key-000000000000"  # secrets-hygiene: allow (fake fixture)  gitleaks:allow
```

Or use a `.gitleaksignore` file with the finding fingerprints gitleaks prints.

### Acceptance check for Part 1

```bash
echo "OPENAI_API_KEY=sk-proj-$(openssl rand -hex 24)" > leak-test.txt   # a random fake key, built at run time
git add leak-test.txt && git commit -m "should be blocked"; echo "exit=$?"   # expect a non-zero exit and a redacted finding
git restore --staged leak-test.txt && rm leak-test.txt
```

## Part 2: respond to a leak (probe first, rotate second)

A leaked key is any key that was ever committed (even if deleted in a later commit), pasted in a chat, issue, screenshot, or log, or sent to a model provider that retains data. Deleting the line does not un-leak it: `git show <old-commit>:path` still prints it, and bots scrape public GitHub within minutes.

### Step 1: probe liveness

```bash
export LEAKED_KEY='...'                     # paste into your own shell, not into a file
python3 "${CLAUDE_SKILL_DIR}/scripts/probe_key.py" openai:LEAKED_KEY
python3 "${CLAUDE_SKILL_DIR}/scripts/probe_key.py" --list   # supported providers
```

- `LIVE`: incident. Continue with Step 2 now.
- `DEAD`: the provider rejects it. Still scrub it (Step 6), but nobody can use it.
- `ERR`: unknown (network, 403, rate limit). **ERR is never an all-clear.** Retry, or check the provider dashboard by hand.

For a provider not in the list, the pattern is one cheap read-only GET with the key: 2xx means live, 401 means dead, anything else means unknown. Add it to `PROVIDERS` in `probe_key.py`.

### Step 2: map every consumer before you rotate

A key almost always lives in more than one place. List them all first, or the rotation breaks production.

```bash
PREFIX='sk-proj-ab'   # the first 10 or so characters, never the whole key
grep -rIl --exclude-dir=node_modules --exclude-dir=.git "$PREFIX" . "$HOME"/.config 2>/dev/null
grep -l "$PREFIX" "$HOME"/.zshrc "$HOME"/.bashrc "$HOME"/.profile 2>/dev/null
crontab -l 2>/dev/null | grep -c "$PREFIX"
```

Also check by hand: the hosting platform's env settings, GitHub Actions secrets, teammates' machines, any scheduled job definitions (launchd plists, systemd units, Task Scheduler), and any app or script that copies config into a backup folder (it can re-introduce the old value later).

### Step 3: mint the new key, keep the old one alive for now

Create the new key in the provider dashboard. Both keys are valid during the swap, so nothing goes down.

### Step 4: swap every consumer in one pass

Update every location from Step 2 together. Then restart what caches env at start-up:

- dev server: restart it
- hosting platform: redeploy (Vercel and similar do not apply new env vars to an existing build)
- launchd: `launchctl bootout gui/$(id -u)/<label>` then `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/<label>.plist` (`kickstart` does not re-read plist env)
- systemd: `systemctl --user daemon-reload && systemctl --user restart <unit>`

Smoke test each consumer with one real call.

### Step 5: revoke the old key, then prove it is dead

Revoke it in the dashboard, then re-run the probe with the OLD value. Done means `DEAD`, not "I clicked revoke":

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/probe_key.py" openai:LEAKED_KEY ; echo "exit=$?"   # expect DEAD and exit=0
```

If you cannot finish today, schedule the probe daily until it reports `DEAD` (see the `scheduled-agents` skill). The off condition is the probe result, never a note that says "rotated".

### Step 6: scrub history (only AFTER rotation)

Rotation is the fix; history scrubbing is cleanup. Order matters: scrub before rotating and you have spent time while the key still works.

```bash
git bundle create ../repo-backup.bundle --all && git bundle verify ../repo-backup.bundle
pipx install git-filter-repo
echo 'sk-proj-THE-OLD-KEY==>REDACTED' > ../replacements.txt
git filter-repo --replace-text ../replacements.txt
git push --force --all && git push --force --tags      # confirm with the team first: this rewrites history
```

Everyone with a clone must re-clone. Forks and cached copies keep the old history, which is why rotation comes first. Also scrub the key from issues, PR comments, chat logs, and notes.

## Gotchas

- Never print a full secret into a log, a chat, or a commit message. Use a prefix for searches.
- A JWT carries an `iat` (issued at) claim; decode it to prove whether a key was really re-issued.
- A stale exported variable in a shell profile or a long-running process shadows a corrected `.env`. Check the value in the same process that is failing (`python3 -c "import os; print(os.environ.get('NAME','')[:6])"`).
- An OAuth token and an API key are different credentials even from the same vendor; put each under the variable name the tool expects.

## Verify (all must hold)

1. `git check-ignore .env.local` prints the path.
2. The Part 1 acceptance check blocks the commit.
3. After a rotation: the old key probes `DEAD`, every consumer passes one real call, and a prefix search of the old key returns nothing outside backups you deliberately kept.
