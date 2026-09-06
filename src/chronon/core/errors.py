from __future__ import annotations

from typing import Any


class ChrononError(Exception):
    code = "chronon_error"
    exit_code = 1

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def as_dict(self) -> dict[str, Any]:
        return {"error": self.code, "message": self.message, **self.details}


class ValidationFailed(ChrononError):
    code = "validation_failed"
    exit_code = 1


class NotImplementedMode(ChrononError):
    code = "not_implemented"
    exit_code = 4


class RepositoryNotFound(ChrononError):
    code = "not_a_chronon_repository"
    exit_code = 3


class AlreadyInitialized(ChrononError):
    code = "already_initialized"
    exit_code = 4


class FileError(ChrononError):
    code = "file_error"
    exit_code = 3


class InvalidArgument(ChrononError):
    code = "invalid_argument"
    exit_code = 4


class ResourceNotTracked(ChrononError):
    code = "resource_not_tracked"
    exit_code = 3


class ResourceAlreadyTracked(ChrononError):
    code = "resource_already_tracked"
    exit_code = 4


class InvalidRevspec(ChrononError):
    code = "invalid_revspec"
    exit_code = 4


class NoStateAt(ChrononError):
    code = "no_state_at"
    exit_code = 8


class PathError(ChrononError):
    code = "path_not_found"
    exit_code = 4


class NothingToCommit(ChrononError):
    code = "nothing_to_commit"
    exit_code = 5


class ForeignChange(ChrononError):
    code = "foreign_change"
    exit_code = 6


class PreconditionRequired(ChrononError):
    code = "precondition_required"
    exit_code = 7


class RevisionConflict(ChrononError):
    code = "revision_conflict"
    exit_code = 7
