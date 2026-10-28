#!/bin/sh
# Plain git pre-commit hook, no framework needed.
# Install:  cp pre-commit.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
#           and copy scan_secrets.py to scripts/ (the fallback when gitleaks is not installed;
#           without either one this hook refuses every commit).
# Uses gitleaks when installed, else scripts/scan_secrets.py.
# Bypass once (only for a confirmed false positive):  git commit --no-verify
if command -v gitleaks >/dev/null 2>&1; then
  exec gitleaks git --pre-commit --staged --redact --no-banner -v
fi
if [ -f scripts/scan_secrets.py ]; then
  exec python3 scripts/scan_secrets.py --staged
fi
echo "pre-commit: no secret scanner found. Install gitleaks (https://github.com/gitleaks/gitleaks#installing) or copy scan_secrets.py from the secrets-hygiene skill to scripts/scan_secrets.py" >&2
exit 1
