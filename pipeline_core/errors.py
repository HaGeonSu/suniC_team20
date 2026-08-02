"""Pipeline exception types."""

from __future__ import annotations

from typing import Any


class PipelineError(Exception):
    """An unrecoverable run-level error."""


class RuleValidationError(PipelineError):
    """A malformed or ambiguous rule repository."""


class RecordError(Exception):
    """A recoverable error affecting one source record."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        partial_record: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.partial_record = partial_record or {}

