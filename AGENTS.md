# AGENTS.md - selkies-layers

## Purpose

Prebuilt, patched components (labwc, wtype, kwin, Xvfb) for the Selkies-based images, one layer image per
distro and layer, published as `ghcr.io/linuxserver-playground/selkies-layers:<distrotag>-<layer>` (plus the
`amd64-` and `arm64v8-` arch tags). Images copy them in with `COPY --from=...selkies-layers:<tag> / /`. In the
playground that is `docker-baseimage-selkies`, `docker-kali-linux`, `docker-lm-studio` and `docker-pelorus`, which
still name `ghcr.io/linuxserver/selkies-layers`. This is not an image repo: it has no `image.yml`, so control
lists it as a helper repo and the hub and site ignore it.

It is a batch build project that shares the org's 20 concurrent job slots with every image build, so it is
capped (workspace `DECISIONS.md`).

## Layout

| Path | What |
| --- | --- |
| `Dockerfile.<distro>.<layer>` | One per layer per distro. A builder stage on the playground base image, then `FROM scratch` with only the built files at their final paths. |
| `bases.yml` | distro -> version. Sets the tag (`alpine324`, `debiantrixie`, `kali`...) and the patch directory. |
| `patches/<distro>/<version>/<layer>/` | Patches the Dockerfile copies in. |
| `scripts/matrix.py` | Turns the Dockerfiles and `bases.yml` into the build jobs (distro x layer x arch) and the manifests. |
| `scripts/ci-build.sh` | One build job: `docker buildx build` under `retry_ghcr`, pushing the arch tag. |
| `scripts/ci-manifests.sh` | The multi-arch manifests, all in one job. |
| `scripts/lib.sh` | `retry_ghcr` and friends, vendored unchanged from `workflows/scripts/lib.sh`. Copy fixes across from there. |
| `build.sh` | Local helper: build one layer. |
| `.github/workflows/build.yml` | "Build Layers", the only workflow. |

## The workflow

Triggers: push and pull request to `main`, a daily schedule (04:30 UTC) and `workflow_dispatch`. Pull requests
build and push nothing, with no registry login. A full run is 46 build jobs (about 230 job-minutes; the kwin
builds take up to 20 minutes each) and one manifest job.

Dispatch inputs:

| Input | Default | What |
| --- | --- | --- |
| `distro` | all | Comma separated distros, e.g. `kali,fedora`. |
| `layer` | all | Comma separated layers, e.g. `kwin`. |
| `arch` | both | `amd64`, `arm64` or both. The manifest always names both arch tags, so a one-arch run keeps the other arch's last build. |
| `push` | `true` | Push the images and manifests. |
| `parallel` | `4` | Build jobs at once, clamped to 1-10. Control will dispatch with a value worked out from the free runner slots. |

Push, schedule and pull request runs take `parallel` 4. One publishing run at a time: push, schedule and
dispatch share one concurrency group, so a second run waits (GitHub keeps only the newest pending one).

```bash
gh workflow run build.yml -R linuxserver-playground/selkies-layers -f distro=kali -f parallel=4
```

Retries: `retry_ghcr` reruns a build up to three times on a GHCR rate limit (`toomanyrequests`) or an apt
mirror failure (`Unable to connect to`, `Failed to fetch`...), and the Debian, Ubuntu and Kali builder stages
set `Acquire::Retries "5"` so apt retries single downloads first. Any other failure fails the job at once.
Upstream rot (a distro package moved, a patch no longer applies) is not ours to fix here: see the workspace's
`docs/build-failure-triage.md`.

## What you may edit

Everything, by pull request or on `main`. The source is `linuxserver/selkies-layers` (remote `upstream`, read
only): keep the Dockerfiles and patches close to it so its changes merge, and keep the playground's own changes
(the `FROM` and image namespace, the retries, the workflow) as separate commits. Every `ghcr.io/linuxserver/`
name rewritten to the playground is listed in the workspace's `docs/playground-references.md`. Never raise the
`parallel` clamp or remove `max-parallel` without the maintainers.

## How to validate

```bash
actionlint .github/workflows/build.yml
shellcheck -x scripts/*.sh build.sh
python3 scripts/matrix.py | jq '.builds | length'      # every Dockerfile maps to bases.yml and its patches
BUILD_JSON=$(python3 scripts/matrix.py --distro kali --layer wtype --arch amd64 | jq -c '.builds[0]') \
  PUSH=false scripts/ci-build.sh                        # one real build, nothing pushed
```

Then dispatch a filtered run (one distro or layer) before a full one.

## Pull request rules

Disclose AI use in the description. One change per PR. Commit subjects are short imperative sentences without
prefixes, emoji or trailers.
