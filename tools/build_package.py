"""Build the package KiCad's Plugin and Content Manager installs, and the repository files that
point to it.

Writes, all meant to be committed:

- ``dist/kicad-simple-step-<version>.zip``: the package - ``metadata.json``, ``plugins/`` and
  ``resources/icon.png`` - for the newest version in ``metadata.json``. Also what "Install from
  File..." takes.
- ``packages.json``: ``metadata.json`` with download details added to every version that has a
  zip in ``dist/``.
- ``resources.zip``: the icon the manager shows before the package is installed.
- ``repository.json``: the file users add as a repository URL; it points at the other two, with
  their hashes.

The URLs point at the main branch on GitHub, so pushing is publishing. To release: add the new
version at the top of ``versions`` in ``metadata.json``, run this, commit and push. Older zips stay
in ``dist/`` so users can still pick them. Needs only Python's standard library.

The zips are built with fixed timestamps, so rebuilding unchanged sources gives the same bytes and
the same hashes.
"""

import copy
import datetime
import hashlib
import json
import os
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_URL = "https://raw.githubusercontent.com/xx0x/kicad-simple-step/main/"
FIXED_TIME = (2026, 1, 1, 0, 0, 0)


def package_files():
    """(path in the zip, path on disk) for everything the package carries."""
    yield "resources/icon.png", os.path.join(ROOT, "resources", "icon.png")
    plugins = os.path.join(ROOT, "plugins")
    for folder, dirs, files in os.walk(plugins):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            if name.endswith(".pyc") or name == ".DS_Store":
                continue
            path = os.path.join(folder, name)
            yield "plugins/" + os.path.relpath(path, plugins).replace(os.sep, "/"), path


def write_zip(path, entries):
    """``entries`` are (name, bytes); written in order with fixed timestamps."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries:
            info = zipfile.ZipInfo(name, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, data)


def read(path):
    with open(path, "rb") as f:
        return f.read()


def sha256(path):
    return hashlib.sha256(read(path)).hexdigest()


def dump(path, data):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
        f.write("\n")


def zip_path(metadata, version):
    return os.path.join(ROOT, "dist", "{}-{}.zip".format(
        metadata["identifier"].rsplit(".", 1)[-1], version["version"]))


def resource(path, now):
    return {
        "url": BASE_URL + os.path.relpath(path, ROOT).replace(os.sep, "/"),
        "sha256": sha256(path),
        "update_timestamp": int(now.timestamp()),
        "update_time_utc": now.strftime("%Y-%m-%d %H:%M:%S"),
    }


def main():
    metadata = json.loads(read(os.path.join(ROOT, "metadata.json")))
    newest = metadata["versions"][0]
    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)

    # Inside the package, metadata.json describes just the version it carries.
    inside = copy.deepcopy(metadata)
    inside["versions"] = [newest]
    files = list(package_files())
    package = zip_path(metadata, newest)
    write_zip(package, [("metadata.json", (json.dumps(inside, indent=4) + "\n").encode())]
              + [(name, read(path)) for name, path in files])
    install_size = len(json.dumps(inside, indent=4)) + 1 + sum(os.path.getsize(p) for _, p in files)
    print("Built " + os.path.relpath(package, ROOT))

    listed = copy.deepcopy(metadata)
    listed["versions"] = []
    for version in metadata["versions"]:
        path = zip_path(metadata, version)
        if not os.path.exists(path):
            print("  no zip for {} in dist/ - left out".format(version["version"]))
            continue
        entry = dict(version)
        entry["download_url"] = BASE_URL + os.path.relpath(path, ROOT).replace(os.sep, "/")
        entry["download_sha256"] = sha256(path)
        entry["download_size"] = os.path.getsize(path)
        if version is newest:
            entry["install_size"] = install_size
        else:
            with zipfile.ZipFile(path) as archive:
                entry["install_size"] = sum(i.file_size for i in archive.infolist())
        listed["versions"].append(entry)
    listed.pop("$schema", None)
    dump(os.path.join(ROOT, "packages.json"), {"packages": [listed]})

    resources = os.path.join(ROOT, "resources.zip")
    write_zip(resources, [(metadata["identifier"] + "/icon.png",
                           read(os.path.join(ROOT, "resources", "icon.png")))])

    now = datetime.datetime.fromtimestamp(int(time.time()), datetime.timezone.utc)
    dump(os.path.join(ROOT, "repository.json"), {
        "$schema": "https://go.kicad.org/pcm/schemas/v1#/definitions/Repository",
        "name": "kicad-simple-step by Vaclav Mach",
        "maintainer": metadata["maintainer"],
        "packages": resource(os.path.join(ROOT, "packages.json"), now),
        "resources": resource(resources, now),
    })
    print("Wrote packages.json, resources.zip and repository.json")


if __name__ == "__main__":
    main()
