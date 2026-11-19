# GOS pipeline: Linux Pixi environment on macOS

This project targets `linux-64`. On Apple Silicon Macs, use OrbStack's
`amd64` Linux machine to run the Linux-only dependencies through x86-64
translation. The `pixi-linux` script forwards arguments to Pixi inside that
machine and runs them in this repository's directory.

## Why a Linux machine, not Docker?

Use the OrbStack `amd64` Linux machine for this project. Pixi already manages
the two software environments; Docker is not required to install or run them.
A Docker image would add build, image, and volume management without removing
the x86-64 translation requirement. It is useful if you need to distribute a
prebuilt image or deploy to a container platform, not as a Rosetta workaround.

On Apple Silicon, **both an `amd64` machine and an `amd64` Docker container
normally use Rosetta**. The `linux-64` lockfile and Linux x64 Java installer
require x86-64; switching to an ARM machine alone will not make them native.
Using an `amd64` distro supplies the matching Linux loader and system libraries,
but does not guarantee compatibility with every translated program.

OrbStack documents near-zero additional CPU use for idle machines and releases
unused memory. The resource limits below are ceilings, not reserved RAM or CPU.
The pipeline dependencies and data still consume disk space with either setup;
containers are not inherently heavyweight, but add no necessary layer here.

See [OrbStack Linux machines](https://docs.orbstack.dev/machines/) and
[resource settings](https://docs.orbstack.dev/settings).

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
architecture is required by this project's locked dependencies. These are
resource limits, not preallocated capacity; adjust them for your workloads.

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

### 5. Bootstrap source-managed tools

`pixi install` alone does not install Java, SnpEff/SnpSift, VEP, or the GitHub
R packages gGnome, JaBbA, and Skilift. From macOS:

```bash
./pixi-linux run --locked -e default setup-pipeline
./pixi-linux run --locked -e vep setup-vep
```

The Java/SnpEff/VEP tasks install checksum-verified sources inside Linux.
Java tracks the latest production upstream release; SnpEff and VEP are pinned.
Species caches, reference FASTA files, and plugins must be supplied separately.
Repeat ordinary setup after recreating the environments, or to adopt newer Java.

`setup-pipeline` also runs `setup-r-packages`, which uses `devtools::install_github`
for `mskilab-org/gGnome`, `mskilab-org/JaBbA`, and `mskilab-org/skilift`, including
their required dependencies. It installs `bamUtils` first because upstream
`gTrack` imports it without declaring its GitHub location, and selects the
Bioconductor release compatible with the installed R. Git is included in the
Pixi dependencies for Bioconductor remotes. To refresh just these R packages:

```bash
./pixi-linux run --locked -e default setup-r-packages
./pixi-linux run --locked Rscript -e 'library(gGnome); library(JaBbA); library(Skilift)'
```

The repository name is `skilift`, but its R package name is **`Skilift`**.
Installation targets the default Pixi environment's `lib/R/library`, not a
macOS or user R library. Required CRAN/Bioconductor dependencies are resolved
noninteractively; optional suggested packages and vignettes are not requested.
Automatic dependency upgrades are disabled, though missing or insufficient
dependencies can still require installation. GitHub packages and these source
dependencies are **not locked by `pixi.lock`** and may change between setups.
Recreating the Pixi environment requires rerunning setup. A `GITHUB_PAT` can
be provided in the Linux environment if GitHub API rate limits are encountered.

Setup verifies package loading in a fresh R process, so dependency updates are
not confused with older namespaces retained by the installer. To check an
existing installation without downloading packages:

```bash
./pixi-linux run --locked Rscript --vanilla scripts/check-r-packages.R
```

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

Complete installation step 5 before using the source-managed tools.

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

### Rosetta compatibility

An `amd64` machine avoids mixing ARM system libraries with x86-64 packages,
but Rosetta remains part of execution on Apple Silicon. Verify representative
pipeline inputs, not just tool version output, before trusting an analysis.

If a failure is specific to Rosetta, OrbStack provides a slower non-Rosetta
fallback. This is a manual diagnostic option, not automatic per-tool failover:

```bash
# Inspect the current setting before changing it.
orbctl config get rosetta
# After stopping active workloads, disable Rosetta in OrbStack.
orbctl config set rosetta false
# Re-run the failing command through ./pixi-linux with the same input.
# Restore this only if Rosetta was enabled before the diagnostic.
orbctl config set rosetta true
```

This setting is global: it affects other OrbStack machines and containers too.
Follow any restart prompts from OrbStack. The fallback is not verified for this
pipeline and may be substantially slower. If both modes fail, use native x86-64
Linux for a translation-free run; Docker on the same Mac does not supply that.
See [OrbStack's Rosetta setting](https://docs.orbstack.dev/settings#use-rosetta-to-run-intel-code).

### Installation and files

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
