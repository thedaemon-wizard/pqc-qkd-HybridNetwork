#!/usr/bin/env bash
# Run gitleaks if installed; otherwise warn.
set -euo pipefail
if command -v gitleaks >/dev/null 2>&1; then
  gitleaks detect --source . --no-banner --redact
else
  echo "gitleaks not installed. Install via: brew install gitleaks (or release binary)"
  echo "Falling back to a basic regex scan..."
  set +e
  grep -rEn --binary-files=without-match \
       --exclude-dir={.git,node_modules,.venv,submodules,benchmarks/results} \
       'PRIVATE KEY|BEGIN OPENSSH|password\s*=\s*['\''"][^'\''"]{8,}' . | head -n 50
fi
