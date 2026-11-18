#!/usr/bin/env python3
"""Install pinned upstream SnpEff 5.4c using the environment's existing Java.

The archive and SHA-256 are the upstream inputs for Bioconda's 5.4.0c
package. No Conda package or Java runtime is downloaded by this installer.
"""

import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import urllib.request
import zipfile


URL = "https://snpeff-public.s3.amazonaws.com/versions/snpEff_v5_4c_core.zip"
SHA256 = "3b06a1e1f939e7ebd5433387f088c1d3d1e0a7d472d63f39161b1fe9f00adf33"
JARS = {"snpEff": "snpEff.jar", "snpSift": "SnpSift.jar"}

# Keep the former Conda launcher's JVM options, memory defaults, dry-run and
# execution-directory support, but never select Java from JAVA_HOME or PATH.
LAUNCHER = '''#!/usr/bin/env python3
import os
from pathlib import Path
import shutil
import sys

home = Path(__file__).resolve().parent
java = home.parent.parent / "bin" / "java"
jar_name = {jar_name!r}
mem_opts = []
prop_opts = []
pass_args = []
exec_dir = None
is_dryrun = False
for arg in sys.argv[1:]:
    if arg.startswith(("-D", "-XX")):
        prop_opts.append(arg)
    elif arg.startswith("-Xm"):
        mem_opts.append(arg)
    elif arg.startswith("--exec_dir="):
        exec_dir = Path(arg.split("=", 1)[1].strip('"').strip("'"))
        if not exec_dir.exists():
            shutil.copytree(home, exec_dir)
    elif arg.startswith("--dry-run"):
        is_dryrun = True
    else:
        pass_args.append(arg)
if not mem_opts and "_JAVA_OPTIONS" not in os.environ:
    mem_opts = ["-Xms512m", "-Xmx1g"]
jar_mode = "-cp" if pass_args and pass_args[0].startswith("eu") else "-jar"
args = [str(java), *mem_opts, *prop_opts, jar_mode,
        str((exec_dir if exec_dir is not None else home) / jar_name), *pass_args]
# Preserve Bioconda's opt-out of SnpEff usage reporting.
if jar_name == "snpEff.jar":
    args.append("-noLog")
if is_dryrun:
    print(args)
else:
    os.execv(java, args)
'''


def install_archive(opt, destination):
    with tempfile.TemporaryDirectory(prefix=".snpeff-", dir=opt) as temporary:
        staging = Path(temporary)
        archive = staging / "snpeff.zip"
        digest = hashlib.sha256()
        with urllib.request.urlopen(URL, timeout=120) as response:
            if not response.url.startswith("https://"):
                raise RuntimeError("SnpEff download redirected away from HTTPS")
            with archive.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    digest.update(chunk)
                    output.write(chunk)
        if digest.hexdigest() != SHA256:
            raise RuntimeError("SnpEff archive SHA-256 mismatch")

        with zipfile.ZipFile(archive) as contents:
            for entry in contents.infolist():
                name = PurePosixPath(entry.filename)
                mode = entry.external_attr >> 16
                if (name.is_absolute() or ".." in name.parts
                        or not name.parts or name.parts[0] != "snpEff"
                        or stat.S_ISLNK(mode)):
                    raise RuntimeError(f"Unsafe SnpEff archive member: {entry.filename}")
                target = staging.joinpath(*name.parts)
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with contents.open(entry) as source, target.open("wb") as output:
                        shutil.copyfileobj(source, output)
                    target.chmod(mode & 0o777)

        extracted = staging / "snpEff"
        for name in (*JARS.values(), "snpEff.config"):
            if not (extracted / name).is_file():
                raise RuntimeError(f"Missing SnpEff distribution file: {name}")
        (extracted / ".archive-sha256").write_text(SHA256 + "\n", encoding="utf-8")
        backup = staging / "previous-snpeff"
        if destination.exists():
            destination.rename(backup)
        try:
            extracted.rename(destination)
        except BaseException:
            if backup.exists():
                backup.rename(destination)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Replace the managed SnpEff installation, including local data and configuration")
    args = parser.parse_args()
    prefix_value = os.environ.get("CONDA_PREFIX")
    if not prefix_value:
        raise RuntimeError("CONDA_PREFIX is required; run inside the Pixi environment")
    prefix = Path(prefix_value).resolve()
    java = prefix / "bin" / "java"
    if not java.is_file() or not os.access(java, os.X_OK):
        raise RuntimeError(f"Run setup-java first; executable Java is missing: {java}")
    opt = prefix / "opt"
    opt.mkdir(exist_ok=True)
    destination = opt / "snpeff"
    marker = destination / ".archive-sha256"
    if destination.exists() or destination.is_symlink():
        if (destination.is_symlink() or not marker.is_file()
                or marker.read_text(encoding="utf-8").strip() != SHA256):
            raise RuntimeError(f"Refusing to replace an unmanaged SnpEff installation: {destination}")
        if not args.force:
            for name in (*JARS.values(), "snpEff.config"):
                if not (destination / name).is_file():
                    raise RuntimeError(f"Incomplete SnpEff installation: {destination / name}")
    for command in JARS:
        link = prefix / "bin" / command
        if os.path.lexists(link) and not (
            link.is_symlink() and link.resolve() == destination / command
        ):
            raise RuntimeError(f"Refusing to replace another package's command: {link}")
    if args.force or not destination.exists():
        install_archive(opt, destination)

    for command, jar_name in JARS.items():
        launcher = destination / command
        launcher.write_text(LAUNCHER.format(jar_name=jar_name), encoding="utf-8")
        launcher.chmod(0o755)
        link = prefix / "bin" / command
        if link.is_symlink():
            continue
        link.symlink_to(Path("..") / "opt" / "snpeff" / command)
    print(f"SnpEff 5.4c installed in {destination} (Java: {java})")


if __name__ == "__main__":
    main()
