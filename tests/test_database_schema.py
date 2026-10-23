from sqlalchemy import inspect


def test_required_tables_exist(test_engine):
    inspector = inspect(test_engine)
    actual_tables = set(inspector.get_table_names())

    required_tables = {
        "users",
        "otp_challenges",
        "incidents",
        "incident_photos",
        "alembic_version",
    }

    missing_tables = required_tables - actual_tables

    assert not missing_tables, (
        f"Required database tables are missing: {sorted(missing_tables)}"
    )
