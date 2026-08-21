from flask_jwt_extended import get_jwt_identity
import logging
from contextvars import ContextVar

logger = logging.getLogger(__name__)

_authenticated_user_id_ctx: ContextVar[object] = ContextVar("authenticated_user_id", default=None)


def set_authenticated_user_id_for_context(user_id):
    """
    Set the authenticated user_id for the current execution context.
    Useful for background threads where Flask request context/JWT is unavailable.
    """
    try:
        _authenticated_user_id_ctx.set(user_id)
    except Exception:
        # Never break business flows
        pass


def get_authenticated_user_id():
    try:
        # Background threads: prefer explicitly-propagated context user_id.
        try:
            ctx_user_id = _authenticated_user_id_ctx.get()
            if ctx_user_id is not None:
                return ctx_user_id
        except Exception:
            pass

        # Cache per-request to avoid repeated JWT extraction (loops/bulk inserts).
        try:
            from flask import g, has_request_context

            if has_request_context() and hasattr(g, "_authenticated_user_id"):
                return getattr(g, "_authenticated_user_id")
        except Exception:
            g = None
            has_request_context = None

        # Ensure JWT is verified for this request context (some callers rely on middleware).
        try:
            from flask_jwt_extended import verify_jwt_in_request
            from flask import has_request_context

            if has_request_context():
                try:
                    verify_jwt_in_request(locations=["headers"])
                except Exception:
                    # Do not fail; fall back to returning None below.
                    pass
        except Exception:
            pass

        user_id = get_jwt_identity()

        if not user_id:
            logger.warning(
                "Authenticated user_id missing in JWT"
            )

        try:
            if has_request_context and has_request_context() and g is not None:
                setattr(g, "_authenticated_user_id", user_id)
        except Exception:
            pass

        return user_id

    except Exception as e:
        logger.warning(
            f"JWT extraction failed: {str(e)}"
        )
        return None
