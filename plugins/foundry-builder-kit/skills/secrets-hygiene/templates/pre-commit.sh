#!/bin/sh
# Plain git pre-commit hook, no framework needed.
# Install:  cp pre-commit.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
# Uses gitleaks when installed, else the stdlib scanner if you copied it to scripts/.
# Bypass once (only for a confirmed false positive):  git commit --no-verify
if command -v gitleaks >/dev/null 2>&1; then
  exec gitleaks git --pre-commit --staged --redact --no-banner -v
fi
if [ -f scripts/scan_secrets.py ]; then
  exec python3 scripts/scan_secrets.py --staged
fi
echo "pre-commit: no secret scanner found. Install gitleaks: https://github.com/gitleaks/gitleaks#installing" >&2
exit 1
