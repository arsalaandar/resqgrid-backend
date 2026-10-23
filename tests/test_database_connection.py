def test_test_database_connection(test_engine):
    with test_engine.connect() as connection:
        result = connection.exec_driver_sql("SELECT current_database()")
        database_name = result.scalar_one()

    assert database_name == "resqgrid_test"
