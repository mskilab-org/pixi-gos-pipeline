#!/usr/bin/env Rscript
# Check the installed library without namespaces retained by devtools.
prefix <- Sys.getenv("CONDA_PREFIX")
if (!nzchar(prefix) || Sys.getenv("PIXI_ENVIRONMENT_NAME") != "default") {
    stop("Run this check in the default Pixi environment")
}
library_path <- normalizePath(file.path(prefix, "lib", "R", "library"), mustWork = TRUE)
.libPaths(c(library_path, .libPaths()))
for (package in c("gGnome", "JaBbA", "Skilift")) {
    loadNamespace(package, lib.loc = library_path)
    message(package, " ", packageVersion(package, lib.loc = library_path), " installed in ", library_path)
}
