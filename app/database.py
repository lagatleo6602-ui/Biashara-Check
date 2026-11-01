import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "mysql+pymysql://root:@localhost:3306/sme_risk_db")

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def add_missing_columns() -> None:
    """create_all() makes new tables but never changes existing ones.
    This adds columns introduced after your tables were first created, so MySQL keeps up."""
    from sqlalchemy import inspect, text

    wanted = {
        "businesses": {
            "pro_until": "DATETIME NULL",
            "pro_source": "VARCHAR(10) NULL",
            "pro_plan": "VARCHAR(10) NULL",
            "auto_renew": "BOOLEAN NOT NULL DEFAULT 0",
            "renew_phone_enc": "VARCHAR(500) NULL",
            "renew_notice_for": "DATETIME NULL",
            "renew_tried_for": "DATETIME NULL",
            "renew_cancelled_at": "DATETIME NULL",
            "outlook_band": "VARCHAR(10) NULL",
            "outlook_for": "INTEGER NULL",
        },
        "payments": {
            "kind": "VARCHAR(10) NOT NULL DEFAULT 'new'",
            "auto_renew": "BOOLEAN NOT NULL DEFAULT 0",
        },
        "users": {
            "must_change_password": "BOOLEAN NOT NULL DEFAULT 0",
            "recovery_hash": "VARCHAR(200) NULL",
            "is_super_admin": "BOOLEAN NOT NULL DEFAULT 0",
            "tour_done_at": "DATETIME NULL",
            "notify_reports": "BOOLEAN NOT NULL DEFAULT 1",
            "notify_reminders": "BOOLEAN NOT NULL DEFAULT 1",
            "notify_alerts": "BOOLEAN NOT NULL DEFAULT 1",
            "language": "VARCHAR(5) NOT NULL DEFAULT 'en'",
            "outlook_months": "INTEGER NOT NULL DEFAULT 3",
        },
    }
    insp = inspect(engine)
    # businesses.sector was an ENUM of 3 types; widen it so new business types fit
    if engine.dialect.name == "mysql" and insp.has_table("businesses"):
        col = next((c for c in insp.get_columns("businesses") if c["name"] == "sector"), None)
        if col is not None and "ENUM" in str(col["type"]).upper():
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE businesses MODIFY sector VARCHAR(20) NOT NULL"))
    # one_time_codes.purpose was an ENUM in an earlier version; widen it so new code types fit
    if engine.dialect.name == "mysql" and insp.has_table("one_time_codes"):
        col = next((c for c in insp.get_columns("one_time_codes") if c["name"] == "purpose"), None)
        if col is not None and "ENUM" in str(col["type"]).upper():
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE one_time_codes MODIFY purpose VARCHAR(20) NOT NULL"))
    with engine.begin() as conn:
        for table, cols in wanted.items():
            if not insp.has_table(table):
                continue
            have = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in cols.items():
                if name not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
