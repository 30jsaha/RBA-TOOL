import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

_engine = None


def _get_db_settings():
    user = os.getenv("DB_USER", "root")
    password = os.getenv("DB_PASSWORD", "")
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "3306")
    database = os.getenv("DB_NAME")

    if not database:
        raise ValueError("DB_NAME is required in .env")

    return {
        "user": user,
        "password": password,
        "host": host,
        "port": port,
        "database": database,
    }


def _build_mysql_url(settings):
    if settings["password"] == "":
        return (
            f"mysql+pymysql://{settings['user']}@"
            f"{settings['host']}:{settings['port']}/{settings['database']}"
        )

    return (
        f"mysql+pymysql://{settings['user']}:{settings['password']}@"
        f"{settings['host']}:{settings['port']}/{settings['database']}"
    )


def _create_mysql_engine(url):
    return create_engine(
        url,
        pool_size=10,
        max_overflow=20,
        pool_timeout=300,
        pool_recycle=1800,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": 300,
            "read_timeout": 300,
            "write_timeout": 300,
            "charset": "utf8mb4",
        },
    )


def get_mysql_engine(force_new=False):
    global _engine

    if not force_new and _engine is not None:
        return _engine

    settings = _get_db_settings()
    url = _build_mysql_url(settings)

    try:
        engine = _create_mysql_engine(url)
        print(
            f"Connected to MySQL: "
            f"{settings['host']}:{settings['port']}/{settings['database']}"
        )
        if force_new:
            return engine
        _engine = engine
        return _engine
    except Exception as e:
        raise ConnectionError(f"Could not connect to MySQL: {e}")


# Database table setup
# Run once to create all required tables

def setup_database(engine):
    """
    Creates all required tables if they do not already exist.
    Safe to run multiple times - uses CREATE TABLE IF NOT EXISTS.
    """
    ddl_statements = [

        # Upload history shared across CIT, GST, SWT
        """
        CREATE TABLE IF NOT EXISTS upload_history (
            id               INT AUTO_INCREMENT PRIMARY KEY,
            tax_type         VARCHAR(10)  NOT NULL,
            filename         VARCHAR(255) NOT NULL,
            file_size_kb     FLOAT,
            file_format      VARCHAR(10),
            row_count        INT,
            column_count     INT,
            uploaded_at      DATETIME     NOT NULL,
            status           VARCHAR(20)  NOT NULL,
            error_message    TEXT,
            pipeline_run     BOOLEAN      DEFAULT FALSE,
            notes            TEXT
        )
        """,

        # CIT fraud justification results
        """
        CREATE TABLE IF NOT EXISTS cit_fraud_justification (
            id               INT AUTO_INCREMENT PRIMARY KEY,
            created_at       DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """,

        # GST fraud justification results
        """
        CREATE TABLE IF NOT EXISTS gst_fraud_justification (
            id               INT AUTO_INCREMENT PRIMARY KEY,
            created_at       DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """,

        # SWT fraud justification results
        """
        CREATE TABLE IF NOT EXISTS swt_fraud_justification (
            id               INT AUTO_INCREMENT PRIMARY KEY,
            created_at       DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    ]

    with engine.connect() as conn:
        for stmt in ddl_statements:
            conn.execute(text(stmt))
        conn.commit()

    print("Database tables verified/created successfully.")


if __name__ == "__main__":
    engine = get_mysql_engine()
    setup_database(engine)
    engine.dispose()
    print("Database setup complete.")
