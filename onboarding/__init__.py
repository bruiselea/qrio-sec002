"""Local owner enrollment and recovery for an owned Q-SL1 (MIT)."""


class EnrollmentError(RuntimeError):
    """A fixed protocol diagnostic, containing no device or key information."""


class PrerequisiteError(ValueError):
    """A fixed input diagnostic safe to display without exception redaction."""
