#!/usr/bin/env python3
"""Install VEP's APIs and HTS bindings without the BioPerl metapackage."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request


# VEP 116.3 and the matching release/116 APIs, pinned to immutable commits.
SOURCES = {
    "ensembl-vep": ("f479099e2a9cd86887a48cf5c293fd7a208ddfb9", "401c50c126e04254ec34993fe5a3c0ba122fa3631114135b1dd5d3ef889f5d42"),
    "ensembl": ("0d852313c420a1d5128b6774635125ebbac03350", "a49b7bed6aca87546ad0ee7ea83e0f30c88465c51b230cf482f2d40bc22bad82"),
    "ensembl-variation": ("db7394a02523a6e519cb0d89f84b2889bac12737", "a5742dd1d3b903b0521f5d5cd6fcb19fc23411a816d93b9928e86aa971d93050"),
    "ensembl-funcgen": ("90049ea7ee4d8ae3a6d298dca46d6c6ab20538c4", "aac8132f013bbd2d09b03f9af6131a2fb1c7db174dfd40397a56a05acae80d14"),
    "ensembl-compara": ("4038708d5a92d109d64413775113cd2eb6607668", "4906659def09471e484f51e9cdf8d5d52e7c573522c0433e5b14c74a8c8bd71d"),
    "ensembl-io": ("6afb5dc27a5ae6881d75959153fbe6e9a4a7e788", "45154809117aff507b91df86fe5fd74a4df0bcf3b588f0b0d0f6ea5278ee28cc"),
    "Bio-DB-HTS": ("5daa12aa3dd7651f664830d9e1e10cea1c469b2f", "341bf4ade43fab75cf77a2fbab87ccea0b85cca2b107f5d3fcceec87242a2284"),
}
COMMANDS = ("vep", "filter_vep", "haplo", "variant_recoder", "convert_cache.pl")
MARKER = ".pixi-vep-install.json"


def fetch(name, directory):
    commit, expected = SOURCES[name]
    archive = directory / f"{name}.tar.gz"
    url = f"https://codeload.github.com/Ensembl/{name}/tar.gz/{commit}"
    digest = hashlib.sha256()
    print(f"Downloading {name} at {commit}", flush=True)
    with urllib.request.urlopen(url, timeout=120) as response, archive.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            digest.update(chunk)
            output.write(chunk)
    if digest.hexdigest() != expected:
        raise RuntimeError(f"SHA-256 mismatch for {name}")
    with tarfile.open(archive) as source:
        source.extractall(directory, filter="data")
    archive.unlink()
    return directory / f"{name}-{commit}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Rebuild and replace the managed VEP installation")
    args = parser.parse_args()
    prefix = Path(os.environ["CONDA_PREFIX"]).resolve()
    if os.environ.get("PIXI_ENVIRONMENT_NAME") != "vep":
        raise RuntimeError("Run this installer with pixi run -e vep setup-vep")
    target = prefix / "opt/vep"
    identity = {"installer": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    for name in ("perl", "htslib", "libgcc"):
        records = list((prefix / "conda-meta").glob(f"{name}-*.json"))
        packages = [json.loads(p.read_text()) for p in records]
        identity[name] = [(p["version"], p["build"]) for p in packages if p["name"] == name]
    # Normalize tuples to match the JSON marker loaded on subsequent runs.
    identity = json.loads(json.dumps(identity))
    for command in COMMANDS:
        link = prefix / "bin" / command
        if os.path.lexists(link) and (not link.is_symlink() or link.resolve() != target / command):
            raise RuntimeError(f"Refusing to overwrite unmanaged command: {link}")
    if target.is_symlink() or (target.exists() and not (target / MARKER).is_file()):
        raise RuntimeError(f"Refusing to replace unmanaged installation: {target}")
    if not args.force and target.exists() and json.loads((target / MARKER).read_text()) == identity:
        print("Pinned VEP 116.3 installation is current")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".vep-", dir=target.parent) as temporary:
            stage = Path(temporary)
            vep = fetch("ensembl-vep", stage)
            version_dir = vep / ".version"
            version_dir.mkdir(exist_ok=True)
            for name, (commit, _) in SOURCES.items():
                if name == "Bio-DB-HTS":
                    continue
                if name != "ensembl-vep":
                    source = fetch(name, stage)
                    shutil.copytree(source / "modules", vep / "modules", dirs_exist_ok=True)
                version = "116.3" if name == "ensembl-vep" else "116"
                (version_dir / name).write_text(f"release {version}\nsub {commit[:7]}\n")
            hts = fetch("Bio-DB-HTS", stage)
            perl = str(prefix / "bin/perl")
            # Conda Perl derives its sysroot from CC; an inherited '_' can point
            # at the calling shell instead. Use this environment's compiler.
            compiler = str(prefix / "bin/x86_64-conda-linux-gnu-gcc")
            # Perl passes GCC-style -Wl flags; Conda's LD points at bare ld.
            build_env = dict(os.environ, CC=compiler, LD=compiler, PREFIX=str(prefix))
            subprocess.run([perl, "Build.PL", "--htslib", str(prefix)], cwd=hts, env=build_env, check=True)
            subprocess.run([perl, "Build"], cwd=hts, env=build_env, check=True)
            # VEP adds its own modules directory to @INC, including XS auto/ libraries.
            for directory in ("lib", "arch"):
                shutil.copytree(hts / "blib" / directory, vep / "modules", dirs_exist_ok=True)
            subprocess.run([perl, f"-I{vep / 'modules'}", "-MBio::DB::HTS", "-MBio::DB::HTS::Faidx", "-e", "print qq(HTS bindings loaded\\n)"], check=True)
            subprocess.run([perl, str(vep / "vep"), "--help"], check=True)
            (vep / MARKER).write_text(json.dumps(identity, indent=2) + "\n")
            backup = stage / "previous-vep"
            if target.exists():
                target.rename(backup)
            try:
                vep.rename(target)
            except BaseException:
                if backup.exists():
                    backup.rename(target)
                raise
    for command in COMMANDS:
        link = prefix / "bin" / command
        if not link.is_symlink():
            link.symlink_to(Path("../opt/vep") / command)
    print(f"VEP 116.3 installed in {target}; caches, FASTA and plugins are separate.")


if __name__ == "__main__":
    main()
