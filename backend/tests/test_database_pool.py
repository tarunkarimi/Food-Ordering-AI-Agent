from unittest.mock import patch

from src.db import database


def test_database_pool_configuration_matches_runtime_settings():
    with (
        patch.object(database.config, "DB_POOL_SIZE", 5),
        patch.object(database.config, "DB_MAX_OVERFLOW", 10),
        patch.object(database.config, "DB_POOL_TIMEOUT_SECONDS", 30.0),
        patch.object(database.config, "DB_POOL_RECYCLE_SECONDS", 1800),
    ):
        assert database.config.DB_POOL_SIZE == 5
        assert database.config.DB_MAX_OVERFLOW == 10
        assert database.config.DB_POOL_TIMEOUT_SECONDS == 30.0
        assert database.config.DB_POOL_RECYCLE_SECONDS == 1800


def test_database_engine_uses_queue_pool():
    pool = database.engine.pool

    assert pool.size() == database.config.DB_POOL_SIZE
    assert pool._max_overflow == database.config.DB_MAX_OVERFLOW
    assert pool._timeout == database.config.DB_POOL_TIMEOUT_SECONDS
