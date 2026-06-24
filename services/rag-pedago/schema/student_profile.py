"""Re-export from nexus-contracts (source of truth)."""

from nexus_contracts.student_profile import *  # noqa: F401,F403
from nexus_contracts.student_profile import (
    StatusDetail,
    StudentProfile,
)

__all__ = [
    "StatusDetail",
    "StudentProfile",
]
