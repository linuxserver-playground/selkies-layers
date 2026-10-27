#!/usr/bin/env bash
# Create the multi-arch manifest of every layer in MANIFESTS_JSON (the manifests output of scripts/matrix.py),
# one after another in a single job. A layer whose arch tags are not all in the registry (its build failed)
# is skipped with an error and the others still go out; the job fails at the end if any was skipped.
set -euo pipefail
# shellcheck source=SCRIPTDIR/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

: "${MANIFESTS_JSON:?}"
summary="${GITHUB_STEP_SUMMARY:-/dev/stdout}"
failed=()

{
  echo "## Manifests"
  echo
  echo "| Tag | Sources | Result |"
  echo "| --- | --- | --- |"
} >> "${summary}"

while IFS= read -r entry; do
  tag=$(jq -r '.tag' <<< "${entry}")
  image=$(jq -r '.image' <<< "${entry}")
  read -r -a sources <<< "$(jq -r '.sources' <<< "${entry}")"

  group "manifest ${tag}"
  missing=()
  for src in "${sources[@]}"; do
    # GHCR answers a tag of a package that does not exist yet with 403, which retry_ghcr takes for a rate
    # limit: keep the attempts few here.
    if RETRY_MAX_ATTEMPTS=3 retry_ghcr docker buildx imagetools inspect "${src}" > /dev/null; then
      echo "ok      ${src}"
    else
      missing+=("${src}")
    fi
  done
  if (( ${#missing[@]} )); then
    endgroup
    error "${tag}: missing ${missing[*]} (its build failed or never ran); manifest not updated"
    echo "| \`${tag}\` | ${#sources[@]} | missing ${missing[*]} |" >> "${summary}"
    failed+=("${tag}")
    continue
  fi
  if RETRY_ALSO="manifest unknown" retry_ghcr docker buildx imagetools create --tag "${image}" "${sources[@]}"; then
    retry_ghcr docker buildx imagetools inspect "${image}"
    endgroup
    echo "| \`${tag}\` | ${#sources[@]} | created |" >> "${summary}"
  else
    endgroup
    error "${tag}: imagetools create failed"
    echo "| \`${tag}\` | ${#sources[@]} | create failed |" >> "${summary}"
    failed+=("${tag}")
  fi
done < <(jq -c '.[]' <<< "${MANIFESTS_JSON}")

if (( ${#failed[@]} )); then
  die "${#failed[@]} manifest(s) not updated: ${failed[*]}"
fi
