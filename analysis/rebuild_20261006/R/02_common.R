suppressWarnings(
  suppressPackageStartupMessages({
    library(arrow)
    library(yaml)
    library(jsonlite)
    library(dplyr)
    library(tidyr)
    library(tibble)
    library(readr)
    library(purrr)
    library(stringr)
    library(ggplot2)
    library(patchwork)
    library(pROC)
    library(PRROC)
    library(xgboost)
    library(Matrix)
    library(knitr)
    library(scales)
  })
)

`%||%` <- function(x, y) {
  if (is.null(x)) y else x
}

parse_cli_args <- function(defaults = list(), args = commandArgs(trailingOnly = TRUE)) {
  parsed <- defaults
  idx <- 1
  while (idx <= length(args)) {
    key <- args[[idx]]
    if (!startsWith(key, "--")) {
      idx <- idx + 1
      next
    }
    name <- gsub("-", "_", substring(key, 3), fixed = TRUE)
    if (length(defaults) && !name %in% names(defaults)) stop("Unknown argument: ", key)
    if (idx == length(args) || startsWith(args[[idx + 1]], "--")) {
      parsed[[name]] <- TRUE
      idx <- idx + 1
    } else {
      parsed[[name]] <- args[[idx + 1]]
      idx <- idx + 2
    }
  }
  parsed
}

ensure_dir <- function(path) {
  dir.create(path, recursive = TRUE, showWarnings = FALSE)
  invisible(normalizePath(path, winslash = "/", mustWork = FALSE))
}

load_config <- function(path) {
  yaml::read_yaml(path)
}

load_frame <- function(path) {
  ext <- tolower(tools::file_ext(path))
  if (ext %in% c("parquet", "pq")) {
    frame <- arrow::read_parquet(path)
    return(as_tibble(frame))
  }
  if (ext == "csv") {
    return(readr::read_csv(path, show_col_types = FALSE))
  }
  stop(sprintf("Unsupported dataset format: %s", ext))
}

save_json <- function(payload, path) {
  ensure_dir(dirname(path))
  jsonlite::write_json(payload, path = path, pretty = TRUE, auto_unbox = TRUE, null = "null")
}

write_markdown_table <- function(title, table, path) {
  ensure_dir(dirname(path))
  markdown <- paste0("# ", title, "\n\n", knitr::kable(table, format = "pipe"), "\n")
  writeLines(markdown, con = path, useBytes = TRUE)
}

clip_probabilities <- function(probabilities) {
  pmin(pmax(as.numeric(probabilities), 1e-6), 1 - 1e-6)
}

safe_auc <- function(y_true, y_prob) {
  if (length(unique(y_true)) < 2) {
    return(NA_real_)
  }
  roc_obj <- pROC::roc(response = y_true, predictor = y_prob, levels = c(0, 1), direction = "<", quiet = TRUE)
  as.numeric(pROC::auc(roc_obj))
}

safe_auprc <- function(y_true, y_prob) {
  positive_scores <- y_prob[y_true == 1]
  negative_scores <- y_prob[y_true == 0]
  if (length(positive_scores) == 0 || length(negative_scores) == 0) {
    return(NA_real_)
  }
  PRROC::pr.curve(scores.class0 = positive_scores, scores.class1 = negative_scores, curve = FALSE)$auc.integral
}

calibration_intercept_slope <- function(y_true, y_prob) {
  y_true <- as.integer(y_true)
  y_prob <- clip_probabilities(y_prob)
  if (length(unique(y_true)) < 2) {
    return(c(intercept = NA_real_, slope = NA_real_))
  }
  logit_prob <- qlogis(y_prob)
  fit <- suppressWarnings(glm(y_true ~ logit_prob, family = binomial()))
  coefficients <- coef(fit)
  c(
    intercept = if (length(coefficients) >= 1) unname(coefficients[[1]]) else NA_real_,
    slope = if (length(coefficients) >= 2) unname(coefficients[[2]]) else NA_real_
  )
}

compute_binary_metrics <- function(y_true, y_prob) {
  y_true <- as.integer(y_true)
  y_prob <- clip_probabilities(y_prob)
  cal <- calibration_intercept_slope(y_true, y_prob)
  list(
    n = length(y_true),
    event_rate = mean(y_true),
    auroc = safe_auc(y_true, y_prob),
    auprc = safe_auprc(y_true, y_prob),
    brier = mean((y_true - y_prob) ^ 2),
    calibration_intercept = unname(cal[["intercept"]]),
    calibration_slope = unname(cal[["slope"]])
  )
}

decision_curve <- function(y_true, y_prob, thresholds) {
  y_true <- as.integer(y_true)
  y_prob <- clip_probabilities(y_prob)
  prevalence <- mean(y_true)
  n <- length(y_true)
  records <- lapply(thresholds, function(threshold) {
    predicted_positive <- y_prob >= threshold
    tp <- sum(predicted_positive & y_true == 1)
    fp <- sum(predicted_positive & y_true == 0)
    weight <- threshold / (1 - threshold)
    tibble(
      threshold = threshold,
      net_benefit_model = (tp / n) - (fp / n) * weight,
      net_benefit_all = prevalence - (1 - prevalence) * weight,
      net_benefit_none = 0
    )
  })
  bind_rows(records)
}

temporal_split_ids <- function(frame, id_column, time_column, train_fraction, valid_fraction) {
  stay_level <- frame |>
    select(all_of(c(id_column, time_column))) |>
    distinct(.data[[id_column]], .keep_all = TRUE) |>
    arrange(.data[[time_column]])

  n <- nrow(stay_level)
  if (n < 10) {
    stop("Too few stays for temporal split. Need at least 10 unique stays.")
  }

  train_end <- max(1, floor(n * train_fraction))
  valid_end <- min(n - 1, train_end + max(1, floor(n * valid_fraction)))

  list(
    train = stay_level[[id_column]][seq_len(train_end)],
    valid = stay_level[[id_column]][seq.int(train_end + 1, valid_end)],
    test = stay_level[[id_column]][seq.int(valid_end + 1, n)]
  )
}

resolve_feature_columns <- function(frame, config, target) {
  categorical_columns <- intersect(config$features$categorical, colnames(frame))
  excluded <- unique(c(config$features$exclude, target, "split", "organ_support_7d",
                       "patientunitstayid", "uniquepid", "hospitalid",
                       "anchor_year", "anchor_year_group", "approx_calendar_year"))
  feature_columns <- setdiff(colnames(frame), excluded)
  numeric_columns <- setdiff(feature_columns, categorical_columns)
  list(
    feature_columns = feature_columns,
    categorical_columns = categorical_columns,
    numeric_columns = numeric_columns
  )
}

mode_value <- function(x) {
  x <- x[!is.na(x) & x != ""]
  if (length(x) == 0) {
    return("missing")
  }
  ux <- unique(x)
  ux[which.max(tabulate(match(x, ux)))]
}

fit_preprocessor <- function(frame, categorical_columns, numeric_columns) {
  numeric_medians <- setNames(
    vapply(numeric_columns, function(col) {
      values <- as.numeric(frame[[col]])
      median_value <- median(values, na.rm = TRUE)
      if (is.na(median_value)) 0 else median_value
    }, numeric(1)),
    numeric_columns
  )
  numeric_means <- setNames(
    vapply(numeric_columns, function(col) {
      values <- as.numeric(frame[[col]])
      values[is.na(values)] <- numeric_medians[[col]]
      mean_value <- mean(values)
      if (is.na(mean_value)) 0 else mean_value
    }, numeric(1)),
    numeric_columns
  )
  numeric_sds <- setNames(
    vapply(numeric_columns, function(col) {
      values <- as.numeric(frame[[col]])
      values[is.na(values)] <- numeric_medians[[col]]
      sd_value <- stats::sd(values)
      if (is.na(sd_value) || sd_value == 0) 1 else sd_value
    }, numeric(1)),
    numeric_columns
  )
  categorical_modes <- setNames(
    vapply(categorical_columns, function(col) mode_value(as.character(frame[[col]])), character(1)),
    categorical_columns
  )
  categorical_levels <- setNames(
    lapply(categorical_columns, function(col) {
      values <- as.character(frame[[col]])
      values[is.na(values) | values == ""] <- categorical_modes[[col]]
      sort(unique(values))
    }),
    categorical_columns
  )
  list(
    categorical_columns = categorical_columns,
    numeric_columns = numeric_columns,
    numeric_medians = numeric_medians,
    numeric_means = numeric_means,
    numeric_sds = numeric_sds,
    categorical_modes = categorical_modes,
    categorical_levels = categorical_levels
  )
}

transform_preprocessor <- function(preprocessor, frame) {
  for (column in c(preprocessor$categorical_columns, preprocessor$numeric_columns)) {
    if (!column %in% colnames(frame)) {
      frame[[column]] <- NA
    }
  }

  numeric_matrix <- matrix(numeric(0), nrow = nrow(frame), ncol = 0)
  if (length(preprocessor$numeric_columns) > 0) {
    numeric_matrix <- do.call(cbind, lapply(preprocessor$numeric_columns, function(col) {
      values <- as.numeric(frame[[col]])
      values[is.na(values)] <- preprocessor$numeric_medians[[col]]
      (values - preprocessor$numeric_means[[col]]) / preprocessor$numeric_sds[[col]]
    }))
    colnames(numeric_matrix) <- paste0("numeric__", preprocessor$numeric_columns)
  }

  categorical_matrix <- matrix(numeric(0), nrow = nrow(frame), ncol = 0)
  if (length(preprocessor$categorical_columns) > 0) {
    categorical_df <- lapply(preprocessor$categorical_columns, function(col) {
      values <- as.character(frame[[col]])
      values[is.na(values) | values == ""] <- preprocessor$categorical_modes[[col]]
      # Map unseen external categories to the training mode; never drop patient rows.
      values[!values %in% preprocessor$categorical_levels[[col]]] <- preprocessor$categorical_modes[[col]]
      factor(values, levels = preprocessor$categorical_levels[[col]])
    }) |>
      setNames(preprocessor$categorical_columns) |>
      as.data.frame(stringsAsFactors = FALSE)
    categorical_formula <- as.formula(paste("~", paste(preprocessor$categorical_columns, collapse = " + "), "- 1"))
    categorical_matrix <- model.matrix(categorical_formula, data = categorical_df)
    colnames(categorical_matrix) <- paste0("categorical__", make.names(colnames(categorical_matrix)))
  }

  combined <- cbind(numeric_matrix, categorical_matrix)
  storage.mode(combined) <- "numeric"
  list(
    matrix = combined,
    feature_names = colnames(combined)
  )
}

calibration_in_the_large <- function(y_true,y_prob) {
  # The intercept-only likelihood is monotone; root solving avoids IRLS divergence
  # when an extrapolating comparator produces probabilities near zero or one.
  logits <- qlogis(clip_probabilities(y_prob))
  observed <- mean(y_true)
  if (observed<=0 || observed>=1) return(NA_real_)
  uniroot(function(a)mean(plogis(a+logits))-observed,c(-100,100),tol=1e-10)$root
}

balanced_case_weights <- function(y_true) {
  y_true <- as.integer(y_true)
  n <- length(y_true)
  positive_n <- sum(y_true == 1)
  negative_n <- sum(y_true == 0)
  if (positive_n == 0 || negative_n == 0) {
    return(rep(1, n))
  }
  ifelse(y_true == 1, n / (2 * positive_n), n / (2 * negative_n))
}

fit_logistic_model <- function(x_matrix, y_true, maxit = 2000, class_weight = "balanced") {
  data <- as.data.frame(x_matrix)
  data$.target <- as.integer(y_true)
  weights <- if (identical(class_weight, "balanced")) balanced_case_weights(y_true) else rep(1, length(y_true))
  suppressWarnings(
    glm(.target ~ ., data = data, family = binomial(), weights = weights, control = glm.control(maxit = maxit))
  )
}

predict_logistic_model <- function(model, x_matrix) {
  clip_probabilities(as.numeric(suppressWarnings(stats::predict(model, newdata = as.data.frame(x_matrix), type = "response"))))
}

fit_xgb_model <- function(x_matrix, y_true, params, x_valid = NULL, y_valid = NULL, early_stopping_rounds = NULL, seed = 20261006) {
  if (anyDuplicated(names(params))) stop("Duplicate XGBoost parameters are not allowed.")
  set.seed(as.integer(seed))
  dtrain <- xgb.DMatrix(data = x_matrix, label = y_true)
  watchlist <- list(train = dtrain)
  if (!is.null(x_valid) && !is.null(y_valid)) {
    watchlist$valid <- xgb.DMatrix(data = x_valid, label = y_valid)
  }

  xgb_params <- list(
    objective = "binary:logistic",
    eval_metric = "logloss",
    eta = params$eta,
    max_depth = as.integer(params$max_depth),
    min_child_weight = params$min_child_weight %||% 1,
    subsample = params$subsample,
    colsample_bytree = params$colsample_bytree,
    lambda = params$lambda %||% 1.0,
    alpha = params$alpha %||% 0.0,
    gamma = params$gamma %||% 0.0,
    nthread = 1
  )

  xgb.train(
    params = xgb_params,
    data = dtrain,
    nrounds = as.integer(params$nrounds),
    watchlist = watchlist,
    early_stopping_rounds = early_stopping_rounds,
    verbose = 0
  )
}

predict_xgb_model <- function(model, x_matrix) {
  clip_probabilities(as.numeric(predict(model, xgb.DMatrix(data = x_matrix))))
}

bootstrap_metric_summary <- function(y_true, y_score, iterations = 2000, seed = 20260331, include_brier = TRUE) {
  set.seed(seed)
  y_true <- as.integer(y_true)
  y_score <- as.numeric(y_score)
  n <- length(y_true)

  point <- list(
    auroc = safe_auc(y_true, y_score),
    auprc = safe_auprc(y_true, y_score)
  )
  if (include_brier) {
    point$brier <- mean((y_true - clip_probabilities(y_score)) ^ 2)
  }

  store <- lapply(names(point), function(x) numeric(0)) |>
    setNames(names(point))

  completed <- 0
  while (completed < iterations) {
    idx <- sample.int(n = n, size = n, replace = TRUE)
    sample_y <- y_true[idx]
    if (length(unique(sample_y)) < 2) {
      next
    }
    sample_score <- y_score[idx]
    store$auroc <- c(store$auroc, safe_auc(sample_y, sample_score))
    store$auprc <- c(store$auprc, safe_auprc(sample_y, sample_score))
    if (include_brier) {
      store$brier <- c(store$brier, mean((sample_y - clip_probabilities(sample_score)) ^ 2))
    }
    completed <- completed + 1
  }

  lapply(names(point), function(metric_name) {
    samples <- store[[metric_name]]
    list(
      estimate = unname(point[[metric_name]]),
      ci_lower = unname(stats::quantile(samples, probs = 0.025, na.rm = TRUE)),
      ci_upper = unname(stats::quantile(samples, probs = 0.975, na.rm = TRUE))
    )
  }) |>
    setNames(names(point))
}

format_ci <- function(metric) {
  sprintf("%.4f (%.4f, %.4f)", metric$estimate, metric$ci_lower, metric$ci_upper)
}

extract_point_estimate <- function(x) {
  if (is.numeric(x)) {
    return(as.numeric(x[[1]]))
  }
  x <- as.character(x[[1]])
  if (is.na(x) || !nzchar(x)) {
    return(NA_real_)
  }
  as.numeric(sub("^\\s*([0-9.\\-]+).*$", "\\1", x))
}

format_p_value <- function(x, include_prefix = TRUE) {
  p <- suppressWarnings(as.numeric(x[[1]]))
  if (is.na(p)) {
    return(as.character(x[[1]]))
  }
  formatted <- if (p < 0.001) {
    "<0.001"
  } else {
    sprintf("%.6f", p)
  }
  if (include_prefix) {
    paste0("P", if (formatted == "<0.001") formatted else paste0("=", formatted))
  } else {
    formatted
  }
}

wilson_interval <- function(events, total, z = 1.96) {
  if (total == 0) {
    return(c(NA_real_, NA_real_))
  }
  p_hat <- events / total
  denominator <- 1 + z^2 / total
  center <- (p_hat + z^2 / (2 * total)) / denominator
  half_width <- z * sqrt((p_hat * (1 - p_hat) + z^2 / (4 * total)) / total) / denominator
  c(center - half_width, center + half_width)
}

calibration_group_table <- function(y_true, y_prob, groups = 10) {
  frame <- tibble(
    target = as.integer(y_true),
    probability = clip_probabilities(y_prob)
  ) |>
    mutate(group = dplyr::ntile(probability, groups))

  frame |>
    group_by(group) |>
    summarise(
      n = n(),
      events = sum(target),
      predicted_mean = mean(probability),
      observed_event_rate = mean(target),
      observed_ci_lower = wilson_interval(sum(target), n())[1],
      observed_ci_upper = wilson_interval(sum(target), n())[2],
      predicted_range_min = min(probability),
      predicted_range_max = max(probability),
      .groups = "drop"
    )
}

delong_roc_test <- function(y_true, pred_one, pred_two) {
  roc_one <- pROC::roc(response = y_true, predictor = pred_one, levels = c(0, 1), direction = "<", quiet = TRUE)
  roc_two <- pROC::roc(response = y_true, predictor = pred_two, levels = c(0, 1), direction = "<", quiet = TRUE)
  test <- pROC::roc.test(roc_one, roc_two, method = "delong", paired = TRUE)
  list(
    auc_model_1 = as.numeric(pROC::auc(roc_one)),
    auc_model_2 = as.numeric(pROC::auc(roc_two)),
    auc_difference = as.numeric(pROC::auc(roc_one) - pROC::auc(roc_two)),
    z_statistic = unname(as.numeric(test$statistic)),
    p_value = unname(as.numeric(test$p.value))
  )
}

build_roc_curve_df <- function(y_true, y_prob) {
  roc_obj <- pROC::roc(response = y_true, predictor = y_prob, levels = c(0, 1), direction = "<", quiet = TRUE)
  tibble(
    fpr = 1 - roc_obj$specificities,
    tpr = roc_obj$sensitivities
  )
}

build_pr_curve_df <- function(y_true, y_prob) {
  positive_scores <- y_prob[y_true == 1]
  negative_scores <- y_prob[y_true == 0]
  curve <- PRROC::pr.curve(scores.class0 = positive_scores, scores.class1 = negative_scores, curve = TRUE)$curve
  tibble(
    recall = curve[, 1],
    precision = curve[, 2]
  )
}

publication_theme <- function(base_size = 10.5, base_family = "Times New Roman") {
  theme_minimal(base_size = base_size, base_family = base_family) +
    theme(
      panel.grid.minor = element_blank(),
      panel.grid.major = element_line(color = "#E4E7EB", linewidth = 0.35),
      axis.title = element_text(face = "bold"),
      axis.text = element_text(color = "#2D3748"),
      plot.title = element_text(face = "bold", size = base_size + 0.8),
      plot.subtitle = element_text(size = base_size - 0.2, color = "#4A5568"),
      plot.caption = element_text(size = base_size - 1, color = "#4A5568"),
      plot.tag = element_text(face = "bold", size = base_size + 1.2),
      legend.title = element_text(face = "bold"),
      legend.position = "bottom",
      legend.box = "horizontal",
      plot.margin = margin(6, 8, 6, 6)
    )
}

metric_box_label <- function(...) {
  paste(..., sep = "\n")
}

maybe_make_plots <- function(y_true, y_prob, output_dir, prefix) {
  ensure_dir(output_dir)
  y_true <- as.integer(y_true)
  y_prob <- clip_probabilities(y_prob)
  if (length(unique(y_true)) < 2) {
    return(invisible(NULL))
  }

  roc_df <- build_roc_curve_df(y_true, y_prob)
  pr_df <- build_pr_curve_df(y_true, y_prob)
  calibration_df <- calibration_group_table(y_true, y_prob, groups = 10)
  dca_df <- decision_curve(y_true, y_prob, thresholds = seq(0.05, 0.50, by = 0.05))
  metrics <- compute_binary_metrics(y_true, y_prob)
  prevalence <- mean(y_true)

  roc_plot <- ggplot(roc_df, aes(x = fpr, y = tpr)) +
    geom_abline(linetype = "dashed", linewidth = 0.55, color = "#A0AEC0") +
    geom_line(linewidth = 1.05, color = "#1F4E79") +
    annotate(
      "label",
      x = 0.70,
      y = 0.14,
      label = metric_box_label(sprintf("AUROC %.3f", metrics$auroc)),
      hjust = 0,
      vjust = 0,
      size = 3.2,
      color = "#1A202C",
      fill = "#FFFFFF"
    ) +
    coord_cartesian(xlim = c(0, 1), ylim = c(0, 1), expand = FALSE) +
    scale_x_continuous(labels = label_percent(accuracy = 1)) +
    scale_y_continuous(labels = label_percent(accuracy = 1)) +
    labs(
      title = "Receiver operating characteristic",
      x = "False-positive rate",
      y = "True-positive rate"
    ) +
    publication_theme()

  pr_plot <- ggplot(pr_df, aes(x = recall, y = precision)) +
    geom_hline(yintercept = prevalence, linetype = "dashed", linewidth = 0.55, color = "#A0AEC0") +
    geom_line(linewidth = 1.05, color = "#D97706") +
    annotate(
      "label",
      x = 0.96,
      y = min(0.42, max(prevalence + 0.22, 0.30)),
      label = metric_box_label(
        sprintf("AUPRC %.3f", metrics$auprc),
        sprintf("Event rate %.1f%%", 100 * prevalence)
      ),
      hjust = 1,
      vjust = 1,
      size = 3.2,
      color = "#1A202C",
      fill = "#FFFFFF"
    ) +
    coord_cartesian(xlim = c(0, 1), ylim = c(0, 1), expand = FALSE) +
    scale_x_continuous(labels = label_percent(accuracy = 1)) +
    scale_y_continuous(labels = label_percent(accuracy = 1)) +
    labs(
      title = "Precision-recall profile",
      subtitle = "Dashed line indicates the event rate",
      x = "Recall",
      y = "Precision"
    ) +
    publication_theme()

  calibration_plot <- ggplot(calibration_df, aes(x = predicted_mean, y = observed_event_rate)) +
    geom_abline(linetype = "dashed", linewidth = 0.55, color = "#A0AEC0") +
    geom_errorbar(
      aes(ymin = observed_ci_lower, ymax = observed_ci_upper),
      width = 0.012,
      linewidth = 0.4,
      color = "#4A5568"
    ) +
    geom_line(linewidth = 0.65, color = "#4A5568") +
    geom_point(aes(size = n), color = "#1D4ED8", fill = "#93C5FD", shape = 21, stroke = 0.4) +
    annotate(
      "label",
      x = 0.67,
      y = 0.13,
      label = metric_box_label(
        sprintf("Intercept %.2f", metrics$calibration_intercept),
        sprintf("Slope %.2f", metrics$calibration_slope)
      ),
      hjust = 0,
      vjust = 0,
      size = 3.2,
      color = "#1A202C",
      fill = "#FFFFFF"
    ) +
    scale_size_continuous(range = c(2.1, 4.4), guide = "none") +
    coord_cartesian(xlim = c(-0.03, 1), ylim = c(-0.05, 1), clip = "off") +
    scale_x_continuous(
      labels = label_percent(accuracy = 1),
      breaks = c(0, 0.25, 0.50, 0.75, 1.00),
      expand = expansion(mult = c(0.02, 0.02))
    ) +
    scale_y_continuous(
      labels = label_percent(accuracy = 1),
      breaks = c(0, 0.25, 0.50, 0.75, 1.00),
      expand = expansion(mult = c(0.02, 0.02))
    ) +
    labs(
      title = "Calibration by deciles",
      subtitle = "Observed rates with Wilson 95% confidence intervals",
      x = "Predicted risk",
      y = "Observed event rate"
    ) +
    publication_theme()

  dca_long <- dca_df |>
    pivot_longer(cols = c(net_benefit_model, net_benefit_all, net_benefit_none), names_to = "strategy", values_to = "net_benefit") |>
    mutate(
      strategy = factor(
        strategy,
        levels = c("net_benefit_model", "net_benefit_all", "net_benefit_none"),
        labels = c("Tuned XGBoost", "Treat all", "Treat none")
      )
    )

  dca_plot <- ggplot(dca_long, aes(x = threshold, y = net_benefit, color = strategy)) +
    geom_line(linewidth = 0.95) +
    scale_color_manual(values = c("Tuned XGBoost" = "#0F766E", "Treat all" = "#C2410C", "Treat none" = "#6B7280")) +
    scale_x_continuous(labels = label_percent(accuracy = 1)) +
    labs(
      title = "Decision-curve analysis",
      subtitle = "Clinical net benefit across threshold probabilities",
      x = "Threshold probability",
      y = "Net benefit",
      color = NULL
    ) +
    publication_theme() +
    theme(legend.position = "bottom")

  combined <- ((roc_plot + pr_plot) / (calibration_plot + dca_plot)) +
    patchwork::plot_layout(widths = c(1, 1), heights = c(1, 1)) +
    patchwork::plot_annotation(tag_levels = "A")
  ggplot2::ggsave(
    filename = file.path(output_dir, sprintf("%s_diagnostics.png", prefix)),
    plot = combined,
    width = 11.6,
    height = 8.8,
    dpi = 320,
    bg = "white"
  )
}

read_tuned_summary <- function(path) {
  jsonlite::fromJSON(path, simplifyVector = TRUE)
}
