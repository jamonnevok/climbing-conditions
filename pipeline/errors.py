"""Failure categories. Each maps to a distinct process exit code and log prefix so
GitHub Actions logs show *where* a failure happened (see README, Troubleshooting)."""


class PipelineError(Exception):
    exit_code = 1
    tag = "PIPELINE"


class ForecastDownloadError(PipelineError):
    exit_code = 10
    tag = "ECMWF"


class ObservationDownloadError(PipelineError):
    exit_code = 11
    tag = "IRM"


class FallbackError(PipelineError):
    exit_code = 12
    tag = "FALLBACK"


class ParseError(PipelineError):
    exit_code = 20
    tag = "PARSE"


class ScoringError(PipelineError):
    exit_code = 30
    tag = "SCORING"


class ValidationError(PipelineError):
    exit_code = 40
    tag = "VALIDATION"


class NoDataError(PipelineError):
    """No usable forecast from any provider and no cached one: refuse to publish."""
    exit_code = 50
    tag = "NO-DATA"
