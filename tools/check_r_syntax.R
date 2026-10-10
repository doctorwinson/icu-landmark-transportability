# Parse scripts without evaluating them or opening a database connection.
arg <- grep("^--file=", commandArgs(FALSE), value = TRUE)
root <- dirname(dirname(normalizePath(sub("^--file=", "", arg[1]), winslash = "/")))
files <- list.files(file.path(root, "analysis"), pattern = "\\.R$", recursive = TRUE, full.names = TRUE)
for (path in files) parse(file = path, encoding = "UTF-8")

# Include the 15% endpoint despite seq() floating-point representation.
thresholds <- seq(.01, .5, .01)
chosen <- round(thresholds, 8) >= .05 & round(thresholds, 8) <= .15
stopifnot(sum(chosen) == 11, any(abs(thresholds[chosen] - .15) < 1e-12))
message("PASS: ", length(files), " R scripts parsed; DCA endpoint test passed. No models executed.")
