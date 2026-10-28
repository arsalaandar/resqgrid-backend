from enum import StrEnum


class Role(StrEnum):
    """Account roles. Stored in the database as their string values."""

    CITIZEN = "CITIZEN"
    OFFICIAL = "OFFICIAL"
    ADMIN = "ADMIN"
    SUPER_ADMIN = "SUPER_ADMIN"


# StrEnum members hash and compare equal to their plain string values, so
# ``"ADMIN" in STAFF_ROLES`` is True for values read from the database.
STAFF_ROLES = frozenset({Role.SUPER_ADMIN, Role.ADMIN, Role.OFFICIAL})
ADMIN_ROLES = frozenset({Role.SUPER_ADMIN, Role.ADMIN})
