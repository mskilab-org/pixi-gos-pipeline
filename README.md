# GOS pipeline: Linux Pixi environment on macOS

This project targets `linux-64`. On Apple Silicon Macs, use OrbStack's
`amd64` Linux machine to run the Linux-only dependencies through x86-64
translation. The `pixi-linux` script forwards arguments to Pixi inside that
machine and runs them in this repository's directory.

## Installation

Requires macOS 14 or later and [Homebrew](https://brew.sh/).

### 1. Install and start OrbStack

```bash
brew install --cask orbstack
open -a OrbStack
```

Finish any setup prompts in the OrbStack app before continuing. This setup
uses a Linux machine, not Docker containers.

### 2. Create the Linux machine

```bash
orbctl create --arch amd64 --cpus 4 --memory 8G --disk 80G ubuntu:24.04 gos-pipeline
```

The name **`gos-pipeline`** is required by `pixi-linux`. The `amd64`
architecture is required by this project's locked dependencies. The resource
limits above are the configuration used for the verified installation; adjust
them for your workloads if needed.

Skip this step if the machine already exists. Inspect it with:

```bash
orbctl info gos-pipeline
```

### 3. Install Pixi inside Linux

```bash
orbctl run --machine gos-pipeline bash -lc '
  set -euo pipefail
  curl -fsSL https://pixi.sh/install.sh -o /tmp/pixi-install.sh
  PIXI_VERSION=0.84.2 PIXI_NO_PATH_UPDATE=1 PIXI_NO_TELEMETRY=1 sh /tmp/pixi-install.sh
  rm /tmp/pixi-install.sh
  "$HOME/.pixi/bin/pixi" config set --global detached-environments true
  "$HOME/.pixi/bin/pixi" --version
'
```

The launcher expects Pixi at `$HOME/.pixi/bin/pixi` inside Linux. Detached
environments keep installed packages and caches on the Linux filesystem,
rather than the shared macOS repository directory.

### 4. Install the project environments

From this repository on macOS:

```bash
./pixi-linux install --locked --all
```

This installs both `default` (the pipeline dependencies) and `vep` (the
separate VEP environment). `--locked` checks that `pixi.toml` and `pixi.lock`
agree and does not update the lockfile.

The repository's `.pixi/config.toml` permits package post-link scripts, which
are needed by some dependencies. Only install packages from sources you trust.

## Usage

Use `./pixi-linux` wherever you would normally use `pixi`:

```bash
# Open an activated shell in the default environment.
./pixi-linux shell

# Run individual commands from macOS.
./pixi-linux run --locked samtools --version
./pixi-linux run --locked bcftools --version
./pixi-linux run --locked python analysis.py
./pixi-linux run --locked Rscript analysis.R

# Use the separate VEP environment.
./pixi-linux run --locked -e vep vep --help
./pixi-linux shell -e vep

# Install again after intentional manifest/lockfile changes.
./pixi-linux install --locked --all
```

`analysis.py` and `analysis.R` above represent your own scripts. Commands run
in the repository root, even if you invoke the launcher from another directory.
Repository files are shared with macOS, so outputs written there appear on the
Mac immediately. Installed environments remain inside the Linux machine.

Inside an activated shell, run tools directly, then use `exit` to return to
macOS. VEP software installation does not install species caches or reference
genomes; supply those separately for annotation workloads.

### Source-managed tools: setup and repair

Inside Linux, bootstrap the tools after installing the Pixi environments:

```bash
pixi run --locked -e default setup-pipeline
pixi run --locked -e vep setup-vep
```

Separate force tasks reinstall even when the installed version is current:

```bash
# Repair only Java, for example after deleting lib/jrt-fs.jar.
pixi run --locked -e default setup-java-force
pixi run --locked -e vep setup-java-force

# Replace Java plus SnpEff/SnpSift in the default environment.
pixi run --locked -e default setup-snpeff-force
# Equivalent umbrella task for the default environment.
pixi run --locked -e default setup-pipeline-force

# Replace Java plus VEP and rebuild its HTS bindings.
pixi run --locked -e vep setup-vep-force
```

From macOS, substitute `./pixi-linux` for `pixi`. These tasks replace only
the selected environment's managed `opt/java`, `opt/snpeff`, and/or `opt/vep`
directories, not its Conda packages or the entire Pixi environment. Java is
rediscovered from the latest production release; SnpEff and VEP stay pinned.
Downloads remain checksum-verified, and replacements are staged before the
old installation is moved aside. Unmanaged installations and conflicting
commands are still refused, including in force mode.

**Back up custom files first:** replaced directories lose all local changes,
including SnpEff databases under `opt/snpeff/data`, edited `snpEff.config`,
and plugins placed inside `opt/vep`. Caches, references, and databases stored
outside the replaced directories are untouched. Do not run force setup while
those tools are running. Ordinary setup tasks retain their existing reuse
behavior; they do not comprehensively detect or repair missing runtime files.

## Machine lifecycle

```bash
# Stop the machine to release its running resources.
orbctl stop gos-pipeline

# Start it explicitly before your next session.
orbctl start gos-pipeline

# Open a plain Linux shell without activating Pixi.
orbctl run --machine gos-pipeline
```

Stopping the machine preserves installed dependencies and data. Deleting it
removes its Linux filesystem, including installed environments and any data
stored only there.

## Troubleshooting

- **`orbctl: command not found`:** install OrbStack and complete its app setup.
- **Machine not found:** create the machine with the exact name `gos-pipeline`.
- **Pixi binary missing:** repeat the Linux Pixi installation step, not a macOS
  Pixi installation.
- **Lockfile mismatch:** reconcile the manifest and lockfile intentionally;
  do not bypass `--locked` merely to get an installation through.
- **Files outside this repository:** OrbStack shares macOS files, but Linux
  paths can differ. Inspect them inside the machine; `/mnt/mac` exposes the
  Mac filesystem. Prefer repository-relative paths for pipeline inputs/outputs.

x86-64 translation can be slower than native x86-64 Linux. Tool startup and
representative Python/R imports were verified with this setup, not a complete
pipeline run on biological data.
