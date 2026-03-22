import mariadb


_pool: mariadb.ConnectionPool | None = None


def init_pool(host: str, port: int, user: str, password: str, database: str) -> None:
    global _pool
    _pool = mariadb.ConnectionPool(
        pool_name="mypool",
        pool_size=10,
        host=host,
        port=port,
        user=user,
        password=password,
        database=database,
    )


def get_pool() -> mariadb.ConnectionPool:
    if _pool is None:
        raise RuntimeError("Pool not initialized")
    return _pool