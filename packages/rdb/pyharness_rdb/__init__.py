"""``ctx.rdb``: relational database workbench — SQLite / PostgreSQL / GaussDB / MySQL (MariaDB).

| member | contract |
|---|---|
| ``store`` | :class:`ProfileStore`: connection profiles (passwords in the credential store), the agent-access setting |
| ``pool`` | :class:`Pool`: one live connection per profile, idle ones closed |
| ``sync()`` | register the ``db_*`` tools and prompt section while agent access is on |

| config | meaning |
|---|---|
| ``path`` | profiles file (default ``<profile data>/toolkit/rdb.json``) |
| ``approval`` | approval gate for ``db_execute`` (default none; needs ``confirm=true`` and a writable connection) |

Tools (shapes as dsh-rdb): ``db_connections``, ``db_schema``, ``db_query`` (one read-only statement), ``db_explain``,
``db_execute`` (writes in one transaction, only on connections marked "allow agent writes"). Routes under ``/api/rdb``
serve the Database page: profiles, settings, test, schemas, tables, columns, ddl, rows (paged, filtered, sorted),
query, execute, changes (grid edits as SQL, previewed then applied) and ``export.csv``.
"""

from .service import GUIDANCE, Config, RdbService

__all__ = ["GUIDANCE", "Config", "RdbService"]
