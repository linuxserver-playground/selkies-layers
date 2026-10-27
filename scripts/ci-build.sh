#!/usr/bin/env bash
# Build one layer for one architecture in CI. Called by .github/workflows/build.yml with one entry of the
# matrix (scripts/matrix.py) in BUILD_JSON; pushes the arch tag when PUSH is true, otherwise only builds.
#
# docker buildx build runs under retry_ghcr, so a GHCR rate limit while pulling the base image, or a distro
# mirror dropping connections mid apt-get, reruns the build after a backoff instead of failing the job.
# Any other failure is returned at once.
set -euo pipefail
# shellcheck source=SCRIPTDIR/lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

: "${BUILD_JSON:?}"
PUSH="${PUSH:-false}"
REPO_URL="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-linuxserver-playground/selkies-layers}"

field() { jq -r --arg k "$1" '.[$k]' <<< "${BUILD_JSON}"; }
dockerfile=$(field dockerfile)
platform=$(field platform)
version=$(field version)
image=$(field image)
distro=$(field distro)
layer=$(field layer)
arch=$(field arch)

args=(
  --file "${dockerfile}"
  --platform "${platform}"
  --build-arg "DISTRO_VERSION=${version}"
  --provenance=false
  --sbom=false
  --pull
  --no-cache
  --tag "${image}"
  --label "org.opencontainers.image.source=${REPO_URL}"
  --label "org.opencontainers.image.revision=${GITHUB_SHA:-unknown}"
  --label "org.opencontainers.image.title=selkies-layers ${layer} (${distro} ${version})"
  --label "org.opencontainers.image.description=Prebuilt ${layer} layer for linuxserver ${distro} ${version} selkies images"
  --label "io.linuxserver.selkies-layers.distro=${distro}"
  --label "io.linuxserver.selkies-layers.version=${version}"
  --label "io.linuxserver.selkies-layers.layer=${layer}"
  --label "io.linuxserver.selkies-layers.arch=${arch}"
)
# A pull request only proves the layer builds: the result stays in the builder's cache.
if [[ "${PUSH}" == "true" ]]; then
  args+=(--push)
fi

# A whole layer build is retried, so keep the attempts few: the kwin builds take up to 20 minutes.
export RETRY_MAX_ATTEMPTS="${RETRY_MAX_ATTEMPTS:-3}"
export RETRY_BASE_DELAY="${RETRY_BASE_DELAY:-30}"
export RETRY_ALSO="${RETRY_ALSO:-Unable to connect to|Failed to fetch|Unable to fetch some archives|Hash Sum mismatch|Temporary failure resolving|Connection timed out|Connection reset by peer}"

group "docker buildx build ${image} (push=${PUSH})"
start=${SECONDS}
retry_ghcr docker buildx build "${args[@]}" .
seconds=$(( SECONDS - start ))
endgroup

echo "- \`${image}\` built in ${seconds}s (push=${PUSH})" >> "${GITHUB_STEP_SUMMARY:-/dev/stdout}"
