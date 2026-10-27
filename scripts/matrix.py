#!/usr/bin/env python3
"""Generate the build/manifest matrix for selkies-layers.

Inputs:
  bases.yml                    distro -> version (tagging + patch lookup)
  Dockerfile.<distro>.<layer>  one file per layer per distro

Outputs (JSON):
  builds     one entry per (distro, layer, arch) -> a build job
  manifests  one entry per (distro, layer)       -> a multi-arch manifest job

Usage:
  scripts/matrix.py                       # pretty JSON to stdout
  scripts/matrix.py --github              # write builds=/manifests= to $GITHUB_OUTPUT
  scripts/matrix.py --distro alpine,arch --layer labwc --arch amd64
"""
import argparse
import glob
import json
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGE = os.environ.get("LAYERS_IMAGE", "ghcr.io/linuxserver-playground/selkies-layers")

ARCHES = {
    "amd64": {
        "platform": "linux/amd64",
        "runner": os.environ.get("RUNNER_AMD64", "ubuntu-24.04"),
        "tag_prefix": "amd64-",
    },
    "arm64": {
        "platform": "linux/arm64",
        "runner": os.environ.get("RUNNER_ARM64", "ubuntu-24.04-arm"),
        "tag_prefix": "arm64v8-",
    },
}

DOCKERFILE_RE = re.compile(r"^Dockerfile\.([a-z0-9]+)\.([a-z0-9-]+)$")


def load_bases(path):
    """Parse bases.yml. Uses PyYAML when present, otherwise a flat key: "value" parser."""
    with open(path) as fh:
        text = fh.read()
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text) or {}
        return {str(k): str(v) for k, v in data.items()}
    except ImportError:
        pass
    data = {}
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        m = re.match(r'^([A-Za-z0-9_-]+)\s*:\s*"?([^"]*?)"?\s*$', line)
        if not m:
            sys.exit(f"bases.yml: cannot parse line: {line!r}")
        data[m.group(1)] = m.group(2)
    return data


def tag_base(distro, version):
    if version == distro:
        return distro
    return f"{distro}{version.replace('.', '')}"


def split_filter(value):
    return {v.strip() for v in value.split(",") if v.strip()} if value else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--distro", default="", help="comma separated distro filter")
    ap.add_argument("--layer", default="", help="comma separated layer filter")
    ap.add_argument("--arch", default="", help="comma separated arch filter (amd64,arm64)")
    ap.add_argument("--github", action="store_true", help="write outputs to $GITHUB_OUTPUT")
    args = ap.parse_args()

    distro_filter = split_filter(args.distro)
    layer_filter = split_filter(args.layer)
    arch_filter = split_filter(args.arch)
    if arch_filter and not arch_filter <= set(ARCHES):
        sys.exit(f"unknown arch in filter: {sorted(arch_filter - set(ARCHES))}")

    bases = load_bases(os.path.join(REPO_ROOT, "bases.yml"))

    dockerfiles = sorted(
        os.path.basename(p) for p in glob.glob(os.path.join(REPO_ROOT, "Dockerfile.*.*"))
    )
    if not dockerfiles:
        sys.exit("no Dockerfile.<distro>.<layer> files found")

    builds, manifests, errors = [], [], []
    seen_distros = set()
    for name in dockerfiles:
        m = DOCKERFILE_RE.match(name)
        if not m:
            errors.append(f"{name}: does not match Dockerfile.<distro>.<layer>")
            continue
        distro, layer = m.groups()
        if distro not in bases:
            errors.append(f"{name}: distro {distro!r} is not defined in bases.yml")
            continue
        seen_distros.add(distro)
        if distro_filter and distro not in distro_filter:
            continue
        if layer_filter and layer not in layer_filter:
            continue

        version = bases[distro]
        base = tag_base(distro, version)
        patch_dir = os.path.join("patches", distro, version, layer)
        with open(os.path.join(REPO_ROOT, name)) as fh:
            uses_patches = "COPY patches/" in fh.read()
        if uses_patches and not os.path.isdir(os.path.join(REPO_ROOT, patch_dir)):
            errors.append(f"{name}: copies patches but {patch_dir}/ does not exist")
            continue

        arch_tags = {}
        for arch, info in ARCHES.items():
            if arch_filter and arch not in arch_filter:
                continue
            tag = f"{info['tag_prefix']}{base}-{layer}"
            arch_tags[arch] = tag
            builds.append(
                {
                    "name": f"{base}-{layer}-{arch}",
                    "distro": distro,
                    "version": version,
                    "layer": layer,
                    "arch": arch,
                    "platform": info["platform"],
                    "runner": info["runner"],
                    "dockerfile": name,
                    "patch_dir": patch_dir if uses_patches else "",
                    "tag": tag,
                    "image": f"{IMAGE}:{tag}",
                }
            )
        if arch_tags:
            manifests.append(
                {
                    "name": f"{base}-{layer}",
                    "distro": distro,
                    "version": version,
                    "layer": layer,
                    "tag": f"{base}-{layer}",
                    "image": f"{IMAGE}:{base}-{layer}",
                    "sources": " ".join(f"{IMAGE}:{t}" for t in arch_tags.values()),
                    "arches": " ".join(sorted(arch_tags)),
                }
            )

    for distro in sorted(set(bases) - seen_distros):
        print(f"warning: bases.yml defines {distro!r} but no Dockerfile.{distro}.* exists", file=sys.stderr)
    if errors:
        sys.exit("matrix errors:\n  " + "\n  ".join(errors))
    if not builds:
        sys.exit("matrix is empty after filtering")

    if args.github:
        out = os.environ.get("GITHUB_OUTPUT")
        if not out:
            sys.exit("--github requires $GITHUB_OUTPUT")
        with open(out, "a") as fh:
            fh.write(f"builds={json.dumps(builds, separators=(',', ':'))}\n")
            fh.write(f"manifests={json.dumps(manifests, separators=(',', ':'))}\n")
        print(f"{len(builds)} build jobs, {len(manifests)} manifest jobs")
    else:
        print(json.dumps({"builds": builds, "manifests": manifests}, indent=2))


if __name__ == "__main__":
    main()
