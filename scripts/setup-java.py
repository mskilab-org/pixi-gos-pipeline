#!/usr/bin/env python3
"""Install the latest production jdk.java.net Linux x64 JDK in this Pixi prefix."""

import argparse
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import platform
import re
import sys
import tarfile
import tempfile
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


INDEX = "https://jdk.java.net/"
MARKER = ".gos-pipeline-java.json"
OWNER = "gos-pipeline/setup-java-v1"


def check_url(url):
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"jdk.java.net", "download.java.net"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
    ):
        raise RuntimeError(f"Unexpected Java download URL: {url}")
    return url


class HTTPSRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPENER = build_opener(HTTPSRedirects())


def fetch(url):
    request = Request(check_url(url), headers={"User-Agent": "gos-pipeline-java-setup"})
    return OPENER.open(request, timeout=120)


def text(url):
    with fetch(url) as response:
        return response.read().decode("utf-8")


class DownloadPage(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.headings = []
        self.links = []
        self.heading = None
        self.link = None
        self.feed(source)
        self.close()

    def handle_starttag(self, tag, attrs):
        if tag == "h1":
            self.heading = {"text": "", "links": []}
        if tag == "a":
            self.link = {"text": "", "href": dict(attrs).get("href", "")}

    def handle_data(self, data):
        if self.heading is not None:
            self.heading["text"] += data
        if self.link is not None:
            self.link["text"] += data

    def handle_endtag(self, tag):
        if tag == "a" and self.link is not None:
            self.links.append(self.link)
            if self.heading is not None:
                self.heading["links"].append(self.link)
            self.link = None
        if tag == "h1" and self.heading is not None:
            self.headings.append(self.heading)
            self.heading = None


def discover():
    index = DownloadPage(text(INDEX))
    candidates = []
    for heading in index.headings:
        if " ".join(heading["text"].split()).startswith("Ready for use:"):
            for link in heading["links"]:
                match = re.fullmatch(r"JDK (\d+)", link["text"].strip())
                if match:
                    candidates.append((int(match[1]), urljoin(INDEX, link["href"])))
    if not candidates:
        raise RuntimeError("Cannot discover the production JDK from jdk.java.net")
    major, page_url = max(candidates)
    page = DownloadPage(text(page_url))
    versions = []
    for heading in page.headings:
        match = re.fullmatch(
            r"(?:OpenJDK )?JDK (\d+(?:\.\d+)*) GA Release Builds",
            " ".join(heading["text"].split()),
        )
        if match:
            versions.append(match[1])
    if len(versions) != 1 or int(versions[0].split(".")[0]) != major:
        raise RuntimeError(f"Cannot identify a production GA version on {page_url}")
    version = versions[0]
    links = {urljoin(page_url, link["href"]) for link in page.links}
    archives = {
        url for url in links
        if urlsplit(url).path.endswith(f"/openjdk-{version}_linux-x64_bin.tar.gz")
        and "/GA/" in urlsplit(url).path
    }
    if len(archives) != 1:
        raise RuntimeError(f"Cannot identify one Linux x64 GA archive on {page_url}")
    archive_url = archives.pop()
    checksum_url = archive_url + ".sha256"
    if checksum_url not in links:
        raise RuntimeError("The production download page has no published SHA-256 link")
    checksum = text(checksum_url).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", checksum):
        raise RuntimeError("The published SHA-256 checksum is unusable")
    return {"owner": OWNER, "version": version, "url": archive_url, "sha256": checksum}


def sha256(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def inspect_jdk(root, expected_version):
    release_path = root / "release"
    if release_path.is_symlink() or not release_path.is_file():
        raise RuntimeError(f"Missing regular JDK release file: {release_path}")
    release = {}
    for line in release_path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r'([A-Z0-9_]+)="([^"\n]*)"', line)
        if not match or match[1] in release:
            raise RuntimeError(f"Malformed JDK release file: {release_path}")
        release[match[1]] = match[2]
    if (
        release.get("JAVA_VERSION") != expected_version
        or release.get("OS_NAME") != "Linux"
        or release.get("OS_ARCH") not in {"x86_64", "amd64"}
        or "-ea" in release.get("JAVA_RUNTIME_VERSION", "").lower()
    ):
        raise RuntimeError(f"JDK release identity does not match production Linux x64 {expected_version}")
    commands = {}
    for command in sorted((root / "bin").iterdir()):
        if not command.is_file() or not os.access(command, os.X_OK):
            raise RuntimeError(f"Invalid JDK command: {command}")
        commands[command.name] = sha256(command)
    if not {"java", "javac", "jar"} <= commands.keys():
        raise RuntimeError("JDK is missing java, javac, or jar")
    return {"release_sha256": sha256(release_path), "commands": commands}


def owned_install(root):
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError(f"Refusing to replace an unowned Java path: {root}")
    marker = root / MARKER
    if marker.is_symlink() or not marker.is_file():
        raise RuntimeError(f"Refusing to replace Java without an ownership marker: {root}")
    identity = json.loads(marker.read_text(encoding="utf-8"))
    if identity.get("owner") != OWNER or not isinstance(identity.get("commands"), dict):
        raise RuntimeError(f"Refusing to replace an unowned Java installation: {root}")
    for name in identity["commands"]:
        if not name or Path(name).name != name or name in {".", ".."}:
            raise RuntimeError("Invalid command in Java installation marker")
    return identity


def link_target(name):
    return f"../opt/java/bin/{name}"


def check_links(bin_dir, names):
    for name in names:
        link = bin_dir / name
        if os.path.lexists(link) and not (
            link.is_symlink() and os.readlink(link) == link_target(name)
        ):
            raise RuntimeError(f"Refusing to replace an unowned command: {link}")


def install_links(bin_dir, names):
    for name in sorted(names):
        link = bin_dir / name
        if not os.path.lexists(link):
            link.symlink_to(link_target(name))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Reinstall the managed JDK even when its version is current")
    args = parser.parse_args()
    prefix_value = os.environ.get("CONDA_PREFIX")
    if not prefix_value:
        raise RuntimeError("CONDA_PREFIX is required; run this task inside a Pixi environment")
    prefix = Path(prefix_value).resolve(strict=True)
    if not prefix.is_dir():
        raise RuntimeError("CONDA_PREFIX must name an existing environment directory")
    if sys.platform != "linux" or platform.machine() not in {"x86_64", "amd64"}:
        raise RuntimeError("This installer supports Linux x64 only")
    identity = discover()  # Always rediscover, even when Java is already installed.
    opt = prefix / "opt"
    bin_dir = prefix / "bin"
    for directory in (opt, bin_dir):
        if directory.is_symlink():
            raise RuntimeError(f"Refusing an environment directory symlink: {directory}")
        directory.mkdir(exist_ok=True)
    destination = opt / "java"
    previous = owned_install(destination) if os.path.lexists(destination) else None
    old_commands = set(previous["commands"]) if previous else set()
    if not args.force and previous and all(previous.get(key) == value for key, value in identity.items()):
        installed = inspect_jdk(destination, identity["version"])
        if any(previous.get(key) != value for key, value in installed.items()):
            raise RuntimeError("Installed Java identity changed; refusing to report it as verified")
        check_links(bin_dir, old_commands)
        install_links(bin_dir, old_commands)
        print(f"Latest production Java {identity['version']} is already verified in {destination}")
        return
    with tempfile.TemporaryDirectory(prefix=".java-setup-", dir=opt) as temporary:
        staging = Path(temporary)
        archive = staging / "jdk.tar.gz"
        print(f"Downloading production Java {identity['version']} from {identity['url']}", flush=True)
        digest = hashlib.sha256()
        with fetch(identity["url"]) as response, archive.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest() != identity["sha256"]:
            raise RuntimeError("Downloaded Java archive does not match the published SHA-256")
        unpacked = staging / "unpacked"
        unpacked.mkdir()
        with tarfile.open(archive, "r:gz") as source:
            source.extractall(unpacked, filter="data")
        roots = list(unpacked.iterdir())
        if len(roots) != 1 or roots[0].is_symlink() or not roots[0].is_dir():
            raise RuntimeError("Java archive must contain exactly one JDK directory")
        staged_jdk = roots[0]
        identity.update(inspect_jdk(staged_jdk, identity["version"]))
        new_commands = set(identity["commands"])
        check_links(bin_dir, old_commands | new_commands)
        (staged_jdk / MARKER).write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")
        backup = staging / "previous"
        if previous:
            destination.rename(backup)
        try:
            staged_jdk.rename(destination)
        except BaseException:
            if previous:
                backup.rename(destination)
            raise
        # All command collisions were checked before publishing the validated JDK.
        install_links(bin_dir, new_commands)
        for name in old_commands - new_commands:
            link = bin_dir / name
            if link.is_symlink() and os.readlink(link) == link_target(name):
                link.unlink()
        # TemporaryDirectory removes only our staged files and previously owned JDK.
    print(f"Installed latest production Java {identity['version']} in {destination}")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Java setup failed: {error}", file=sys.stderr)
        sys.exit(1)
