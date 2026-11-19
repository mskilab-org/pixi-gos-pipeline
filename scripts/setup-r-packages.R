#!/usr/bin/env Rscript
# Install source-managed packages into the active Pixi R library, not ~/R.
prefix <- Sys.getenv("CONDA_PREFIX")
if (!nzchar(prefix) || Sys.getenv("PIXI_ENVIRONMENT_NAME") != "default") {
    stop("Run this installer with pixi run -e default setup-r-packages")
}
library_path <- normalizePath(file.path(prefix, "lib", "R", "library"), mustWork = TRUE)
.libPaths(c(library_path, .libPaths()))
options(repos = c(CRAN = "https://cloud.r-project.org"))

# remotes needs BiocManager to resolve the upstream Bioconductor dependencies.
if (!requireNamespace("BiocManager", quietly = TRUE)) {
    install.packages("BiocManager", lib = library_path)
}
# Keep unversioned bioc:: remotes on the release compatible with this R.
bioc_version <- as.character(BiocManager::version())
Sys.setenv(R_BIOC_VERSION = bioc_version)
options(repos = BiocManager::repositories(version = bioc_version))

# gTrack imports bamUtils but omits its GitHub remote from DESCRIPTION.
# Install it first so gGnome's dependency traversal can install gTrack.
devtools::install_github(
    c("mskilab-org/bamUtils", "mskilab-org/gGnome", "mskilab-org/JaBbA", "mskilab-org/skilift"),
    lib = library_path,
    dependencies = NA,
    upgrade = "never",
    build_vignettes = FALSE
)

# Installation may update namespaces already loaded by devtools. Verify in a
# fresh process, and propagate failures even when installation only warned.
status <- system2(file.path(R.home("bin"), "Rscript"),
                  c("--vanilla", "scripts/check-r-packages.R"))
if (status != 0L) {
    stop("Installed R package verification failed")
}
