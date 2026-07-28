#!/usr/bin/env bash
# Verify a PUBLISHED websieve release by installing it from PyPI into clean
# Docker containers and exercising it there.
#
# This catches what CI structurally cannot. CI tests an artifact it just built,
# in an environment it controls. This tests what a stranger actually receives
# from `pip install websieve`, on stock images, with no repository present.
#
# Usage:
#   scripts/verify-published.sh              # latest, on 3.10 / 3.11 / 3.12
#   scripts/verify-published.sh 0.1.0        # a specific version
#   scripts/verify-published.sh 0.1.0 3.12   # one Python version

set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERSION="${1:-}"
if [[ -n "${2:-}" ]]; then PYTHONS=("$2"); else PYTHONS=(3.10 3.11 3.12); fi

SPEC="websieve"
[[ -n "$VERSION" ]] && SPEC="websieve==$VERSION"

red=$'\033[31m'; grn=$'\033[32m'; off=$'\033[0m'
[[ -t 1 ]] || { red=""; grn=""; off=""; }

pass=0; fail=0; failed_versions=()

for PY in "${PYTHONS[@]}"; do
  echo
  echo "=============================================================="
  echo "python:${PY}-slim   installing ${SPEC} from PyPI"
  echo "=============================================================="

  # The container script arrives on stdin, so nothing from this repository is
  # mounted and there is no nested-quoting to get wrong.
  if docker run --rm -i -e "SPEC=${SPEC}" "python:${PY}-slim" \
       bash -s < "${HERE}/_verify-in-container.sh"; then
    echo "${grn}PASS${off}  python:${PY}-slim"
    pass=$((pass+1))
  else
    echo "${red}FAIL${off}  python:${PY}-slim"
    fail=$((fail+1)); failed_versions+=("$PY")
  fi
done

echo
echo "=============================================================="
printf 'published-artifact verification: %d passed, %d failed\n' "$pass" "$fail"
[[ $fail -gt 0 ]] && printf 'failed on: %s\n' "${failed_versions[*]}"
echo "=============================================================="
[[ $fail -eq 0 ]]
