#!/usr/bin/env bash
# Upload the pipeline code to the CDE files resource rsingh-mcc-code from a pushed commit.
# The GitHub repo is private, so CDE cannot sync it as a Repository resource: the code goes up as
# a `git archive` of HEAD (only committed files; never .env or local data), and CODE_VERSION in
# the resource names the commit. The jobs mount it at /app/mount, where cde/jobs/ finds config/,
# contracts/, generators/ and stream/ next to it.
#
#   ./cde/scripts/mcc_deploy_code.sh            # refuses when HEAD is not on the remote
#   ALLOW_UNPUSHED=1 ./cde/scripts/mcc_deploy_code.sh

set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

RESOURCE="${RESOURCE:-rsingh-mcc-code}"
SHA="$(git rev-parse HEAD)"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"

if [[ "${ALLOW_UNPUSHED:-0}" != "1" ]] && [[ -z "$(git branch -r --contains "${SHA}" 2>/dev/null)" ]]; then
  echo "HEAD ${SHA:0:12} is not on the remote: git push first (or ALLOW_UNPUSHED=1)" >&2
  exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT
git archive --format=tar --prefix=code/ "${SHA}" cde config contracts generators stream | tar -x -C "${TMP}"
printf '%s %s %s\n' "${SHA}" "${BRANCH}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${TMP}/code/CODE_VERSION"
find "${TMP}/code" -name '__pycache__' -prune -exec rm -rf {} +
(cd "${TMP}/code" && tar -czf "${TMP}/code.tar.gz" .)

if ! cde resource describe --name "${RESOURCE}" &>/dev/null; then
  echo "==> Creating files resource ${RESOURCE}"
  cde resource create --name "${RESOURCE}" --type files >/dev/null
fi
echo "==> Uploading ${SHA:0:12} (${BRANCH}) to ${RESOURCE}"
cde resource upload-archive --name "${RESOURCE}" --local-path "${TMP}/code.tar.gz" --hide-progress-bars >/dev/null
echo "    done: $(du -h "${TMP}/code.tar.gz" | cut -f1) archive"
