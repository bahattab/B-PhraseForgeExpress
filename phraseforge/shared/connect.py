"""Connect to the shared phrase database from the shared.* settings.

  shared.enabled     "1" = sync the Shared folder with the server
  shared.engine      sqlserver | postgresql
  shared.server      host name (SQL Server also accepts host\\instance)
  shared.port        optional (SQL Server 1433, PostgreSQL 5432)
  shared.database    database name
  shared.auth        windows | password
                       windows:  SQL Server integrated security (Trusted_Connection);
                                 PostgreSQL SSPI/GSSAPI with the Windows user name
                       password: a database login, checked by the server
  shared.user / shared.password   for auth = password (the password is stored sealed
                                  with Windows DPAPI, like the AI keys)
  shared.encrypt     "1" = encrypted connection (default)
  shared.trust_cert  "1" = accept a self-signed server certificate (SQL Server)
  shared.interval    seconds between automatic syncs (default 60)
  shared.root_name   name of the local folder that holds the shared phrases
"""
from __future__ import annotations

import getpass
import os
from typing import Callable

from phraseforge.shared.server import SharedError, SharedServer

ENGINES = {"sqlserver": "Microsoft SQL Server", "postgresql": "PostgreSQL"}
SQLSERVER_DRIVERS = ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server")


def _odbc_value(v: str) -> str:
    """An ODBC connection-string value; braces protect ; = { } and spaces."""
    v = str(v)
    if any(c in v for c in ";={} ") or v != v.strip():
        return "{" + v.replace("}", "}}") + "}"
    return v


def pick_driver(installed: list[str]) -> str:
    for d in SQLSERVER_DRIVERS:
        if d in installed:
            return d
    raise SharedError("No SQL Server ODBC driver is installed. Install \"ODBC Driver 18 for SQL Server\" "
                      "from Microsoft.")


def sqlserver_connection_string(server: str, database: str, auth: str, user: str = "", password: str = "",
                                port: str = "", encrypt: bool = True, trust_cert: bool = False,
                                driver: str = "ODBC Driver 18 for SQL Server") -> str:
    host = server + (f",{port}" if port else "")
    parts = [f"DRIVER={{{driver}}}", "SERVER=" + _odbc_value(host), "DATABASE=" + _odbc_value(database)]
    if auth == "windows":
        parts.append("Trusted_Connection=yes")
    else:
        parts += ["UID=" + _odbc_value(user), "PWD=" + _odbc_value(password)]
    if driver != "SQL Server":                    # the old built-in driver knows neither keyword
        parts.append("Encrypt=" + ("yes" if encrypt else "no"))
        parts.append("TrustServerCertificate=" + ("yes" if trust_cert else "no"))
    parts.append("APP=PhraseForge")
    return ";".join(parts)


def windows_user() -> str:
    return os.environ.get("USERNAME") or getpass.getuser()


def postgresql_params(server: str, database: str, auth: str, user: str = "", password: str = "",
                      port: str = "", encrypt: bool = True) -> dict:
    params = {"host": server, "dbname": database, "connect_timeout": 10, "application_name": "PhraseForge",
              "sslmode": "require" if encrypt else "prefer"}
    if port:
        params["port"] = int(port)
    if auth == "windows":
        params["user"] = windows_user()      # libpq answers an SSPI/GSSAPI request from the server itself
    else:
        params["user"], params["password"] = user, password
    return params


def connect(setting: Callable[[str, str], str], connectors: dict | None = None) -> SharedServer:
    """Open the shared database the settings describe. connectors (for tests) maps an
    engine to a function returning a DB-API connection."""
    engine = setting("shared.engine", "sqlserver")
    server, database = setting("shared.server", ""), setting("shared.database", "")
    auth = setting("shared.auth", "windows")
    user, password, port = setting("shared.user", ""), setting("shared.password", ""), setting("shared.port", "")
    encrypt = setting("shared.encrypt", "1") == "1"
    if engine not in ENGINES:
        raise SharedError(f"unknown database type {engine!r}")
    if not server or not database:
        raise SharedError("Enter the server and the database name.")
    if auth == "password" and not user:
        raise SharedError("Enter the database user name.")
    try:
        if connectors and engine in connectors:
            conn = connectors[engine]()
        elif engine == "sqlserver":
            try:
                import pyodbc  # type: ignore
            except ImportError as e:
                raise SharedError("pyodbc is not installed") from e
            cs = sqlserver_connection_string(server, database, auth, user, password, port, encrypt,
                                             setting("shared.trust_cert", "0") == "1", pick_driver(pyodbc.drivers()))
            conn = pyodbc.connect(cs, autocommit=False, timeout=10)
        else:
            try:
                import psycopg  # type: ignore
            except ImportError as e:
                raise SharedError("psycopg is not installed") from e
            conn = psycopg.connect(**postgresql_params(server, database, auth, user, password, port, encrypt))
    except SharedError:
        raise
    except Exception as e:
        raise SharedError(f"Could not connect to {ENGINES[engine]} on {server}: {e}") from e
    return SharedServer(conn, engine)
