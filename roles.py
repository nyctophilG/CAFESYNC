# roles.py
"""Role definitions for the CafeSync RBAC system.

Four roles, each with distinct dashboard treatment and permissions:

  ADMIN   — full access to everything (dashboard, telemetry, user mgmt, orders).
  BARISTA — serves orders only. Sees an order queue, can mark items complete.
            No telemetry, no user mgmt, no order placement.
  USER    — places orders via /menu. No dashboard access.
  VIEWER  — read-only dashboard viewer. Sees telemetry + orders queue but
            cannot interact (buttons hidden, no user mgmt).
"""
from typing import Final


class Role:
    ADMIN: Final[str] = "admin"
    BARISTA: Final[str] = "barista"
    USER: Final[str] = "user"
    VIEWER: Final[str] = "viewer"


# All valid role values, used for input validation in user management.
ALL_ROLES = frozenset({Role.ADMIN, Role.BARISTA, Role.USER, Role.VIEWER})

# Roles that can see the operations dashboard (admin = full, viewer = read-only).
# Barista has its own dedicated page, not the main dashboard.
DASHBOARD_ROLES = frozenset({Role.ADMIN, Role.VIEWER})

# Roles that can interact with orders in the queue (mark complete).
# Anyone here gets the "Serve" buttons.
ORDER_FULFILLMENT_ROLES = frozenset({Role.ADMIN, Role.BARISTA})

# Roles allowed to fulfill (interactive control). Used in templates and
# router dependencies to gate "Serve" actions.
STAFF_ROLES = frozenset({Role.ADMIN, Role.BARISTA, Role.VIEWER})


def post_login_path(role: str) -> str:
    """Where to send a user immediately after sign-in.

    Centralized so the same logic isn't repeated across login, signup,
    2FA challenge, and passkey flows.
    """
    if role == Role.ADMIN:
        return "/dashboard"
    if role == Role.VIEWER:
        return "/dashboard"
    if role == Role.BARISTA:
        return "/dashboard"  # served by render_dashboard, picks barista template
    # role == USER (default for new signups) or anything unknown
    return "/menu"
