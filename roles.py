# roles.py
"""Role definitions for the CafeSync RBAC system.

Centralizing these as constants prevents typos that silently grant or deny
access (e.g. comparing role to "Admin" vs "admin"). Importing from one place
also makes it easy to find every reference if we add or rename a role later.
"""
from typing import Final


class Role:
    ADMIN: Final[str] = "admin"
    BARISTA: Final[str] = "barista"
    CUSTOMER: Final[str] = "customer"


# Whitelist of valid role values, used for input validation in the
# user management endpoints.
ALL_ROLES = frozenset({Role.ADMIN, Role.BARISTA, Role.CUSTOMER})

# Convenience set: roles that get to see the operations dashboard.
# Customers are explicitly excluded — they have API access only.
STAFF_ROLES = frozenset({Role.ADMIN, Role.BARISTA})
