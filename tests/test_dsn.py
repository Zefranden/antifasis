import pytest

from antifasis.db import ErrorBaseDatos, preparar_dsn


def test_supabase_sin_sslmode():
    assert (
        preparar_dsn("postgresql://postgres:clave@db.abc.supabase.co:5432/postgres")
        == "postgresql://postgres:clave@db.abc.supabase.co:5432/postgres?sslmode=require"
    )


def test_supabase_pooler_con_parametros():
    url = "postgresql://postgres.abc:clave@aws-0-eu.pooler.supabase.com:6543/postgres?pgbouncer=true"
    assert preparar_dsn(url) == (
        "postgresql://postgres.abc:clave@aws-0-eu.pooler.supabase.com:6543/postgres"
        "?sslmode=require"
    )


def test_dsn_existente_no_se_modifica():
    url = "postgresql://antifasis:antifasis@localhost:5432/antifasis?sslmode=disable"
    assert preparar_dsn(url) == url


def test_dsn_local_no_se_modifica():
    url = "postgresql://antifasis:antifasis@localhost:5432/antifasis"
    assert preparar_dsn(url) == url


def test_supabase_elimina_pgbouncer():
    url = "postgresql://postgres.abc:clave@aws-0-eu.pooler.supabase.com:6543/postgres?pgbouncer=true&sslmode=require"
    assert preparar_dsn(url) == (
        "postgresql://postgres.abc:clave@aws-0-eu.pooler.supabase.com:6543/postgres?sslmode=require"
    )


def test_dsn_vacia():
    with pytest.raises(ErrorBaseDatos):
        preparar_dsn("   ")
