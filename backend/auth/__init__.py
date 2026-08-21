"""
Authentication integration (ported from old-backend).

Exposes `init_auth(app)` which:
- configures Flask-JWT-Extended
- registers login/refresh/me routes
- installs centralized protection for all `/api/*` endpoints (except allowlisted)
"""

from .auth_init import init_auth  # noqa: F401

