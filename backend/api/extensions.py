"""
Minimal DB helper used by dashboard_* route modules.

The project does not vendor `flask_sqlalchemy`, so we provide a tiny wrapper
that exposes `db.session.execute(...)` compatible with existing code.
"""

from sqlalchemy.orm import scoped_session, sessionmaker

from config.db_config import get_mysql_engine

try:
    from flask_caching import Cache
except Exception:
    class Cache:  # pragma: no cover - lightweight fallback
        def __init__(self, *args, **kwargs):
            self._store = {}

        def init_app(self, app):
            return None

        def get(self, key):
            return self._store.get(key)

        def set(self, key, value, timeout=None):
            self._store[key] = value
            return True


class _DB:
    def __init__(self):
        self._engine = None
        self._Session = None
        self.session = None

    @property
    def engine(self):
        """
        Compatibility shim for code that expects `db.engine` (Flask-SQLAlchemy style).
        """
        return self._engine

    def init_app(self, app):
        if self._engine is None:
            self._engine = get_mysql_engine()
            self._Session = scoped_session(sessionmaker(bind=self._engine))
            self.session = self._Session

        @app.before_request
        def _ensure_clean_session():
            try:
                if self._Session is not None:
                    # If transaction is in failed / inactive state, rollback cleanly
                    self._Session.rollback()
            except Exception:
                pass

        @app.teardown_appcontext
        def _shutdown_session(exception=None):
            try:
                if self._Session is not None:
                    self._Session.rollback()
                    self._Session.remove()
            except Exception:
                pass


db = _DB()
cache = Cache()
