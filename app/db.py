"""SQLite 存取：建表、连接、树结构、搜索与备份。"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS groups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_id   INTEGER REFERENCES groups(id) ON DELETE CASCADE,
    name        TEXT NOT NULL CHECK (length(trim(name)) > 0),
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS links (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id    INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    title       TEXT NOT NULL CHECK (length(trim(title)) > 0),
    url         TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    icon        TEXT NOT NULL DEFAULT '',
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id    INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    name        TEXT NOT NULL COLLATE NOCASE CHECK (length(trim(name)) > 0),
    content     TEXT NOT NULL DEFAULT '',
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE(group_id, name)
);

CREATE INDEX IF NOT EXISTS idx_groups_parent ON groups(parent_id, sort_order, id);
CREATE INDEX IF NOT EXISTS idx_links_group ON links(group_id, sort_order, id);
CREATE INDEX IF NOT EXISTS idx_documents_group ON documents(group_id, sort_order, id);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def connect(database: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(database), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db(database: str | Path) -> None:
    path = Path(database)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def serialize_group(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "parent_id": row["parent_id"],
        "name": row["name"],
        "sort_order": row["sort_order"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def serialize_link(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "group_id": row["group_id"],
        "title": row["title"],
        "url": row["url"],
        "description": row["description"],
        "icon": row["icon"],
        "sort_order": row["sort_order"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def serialize_document(row: sqlite3.Row, *, with_content: bool = False) -> dict[str, Any]:
    item = {
        "id": row["id"],
        "group_id": row["group_id"],
        "name": row["name"],
        "sort_order": row["sort_order"],
        "size": len(row["content"] or ""),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if with_content:
        item["content"] = row["content"]
    return item


def find_document(conn: sqlite3.Connection, document_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()


def list_documents(conn: sqlite3.Connection, group_id: int) -> list[sqlite3.Row]:
    # README.md 优先，其余按排序值、名称排列
    return conn.execute(
        """
        SELECT * FROM documents
        WHERE group_id = ?
        ORDER BY CASE WHEN lower(name) = 'readme.md' THEN 0 ELSE 1 END,
                 sort_order ASC, lower(name) ASC, id ASC
        """,
        (group_id,),
    ).fetchall()


def build_tree(conn: sqlite3.Connection) -> dict[str, Any]:
    group_rows = conn.execute(
        "SELECT * FROM groups ORDER BY sort_order ASC, id ASC"
    ).fetchall()
    link_rows = conn.execute(
        "SELECT * FROM links ORDER BY sort_order ASC, id ASC"
    ).fetchall()
    document_counts = {
        row["group_id"]: row["n"]
        for row in conn.execute(
            "SELECT group_id, COUNT(*) AS n FROM documents GROUP BY group_id"
        )
    }

    nodes: dict[int, dict[str, Any]] = {}
    for row in group_rows:
        node = serialize_group(row)
        node.update(
            {
                "links": [],
                "children": [],
                "direct_link_count": 0,
                "total_link_count": 0,
                "direct_document_count": document_counts.get(row["id"], 0),
                "total_document_count": 0,
            }
        )
        nodes[node["id"]] = node

    for row in link_rows:
        node = nodes.get(row["group_id"])
        if node is not None:
            node["links"].append(serialize_link(row))

    roots: list[dict[str, Any]] = []
    for row in group_rows:
        node = nodes[row["id"]]
        parent = nodes.get(row["parent_id"]) if row["parent_id"] is not None else None
        if parent is None:
            roots.append(node)
        else:
            parent["children"].append(node)

    def count(node: dict[str, Any]) -> int:
        direct_links = len(node["links"])
        node["direct_link_count"] = direct_links
        child_links = 0
        child_documents = 0
        for child in node["children"]:
            count(child)
            child_links += child["total_link_count"]
            child_documents += child["total_document_count"]
        node["total_link_count"] = direct_links + child_links
        node["total_document_count"] = node["direct_document_count"] + child_documents
        return node["total_link_count"]

    for root in roots:
        count(root)

    return {
        "groups": roots,
        "total_groups": len(group_rows),
        "total_links": len(link_rows),
        "total_documents": sum(document_counts.values()),
    }


def find_group(conn: sqlite3.Connection, group_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()


def find_link(conn: sqlite3.Connection, link_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM links WHERE id = ?", (link_id,)).fetchone()


def group_ancestors(conn: sqlite3.Connection, group_id: int) -> list[sqlite3.Row]:
    """返回从当前分组到根分组的祖先行（含当前分组）。"""

    rows: list[sqlite3.Row] = []
    seen: set[int] = set()
    current: int | None = group_id
    while current is not None and current not in seen:
        seen.add(current)
        row = find_group(conn, current)
        if row is None:
            break
        rows.append(row)
        current = row["parent_id"]
    return rows


def group_path(conn: sqlite3.Connection, group_id: int) -> str:
    rows = group_ancestors(conn, group_id)
    return " / ".join(row["name"] for row in reversed(rows))


def group_descendants(conn: sqlite3.Connection, group_id: int) -> list[int]:
    rows = conn.execute(
        """
        WITH RECURSIVE sub(id) AS (
            SELECT id FROM groups WHERE id = ?
            UNION ALL
            SELECT g.id FROM groups g JOIN sub s ON g.parent_id = s.id
        )
        SELECT id FROM sub
        """,
        (group_id,),
    ).fetchall()
    return [row["id"] for row in rows]


def next_sort(
    conn: sqlite3.Connection, table: str, column: str, value: int | None
) -> int:
    if table not in {"groups", "links", "documents"} or column not in {
        "parent_id",
        "group_id",
    }:
        raise ValueError("非法的排序查询")
    if value is None:
        row = conn.execute(
            f"SELECT COALESCE(MAX(sort_order), -10) + 10 AS next_order "
            f"FROM {table} WHERE {column} IS NULL"
        ).fetchone()
    else:
        row = conn.execute(
            f"SELECT COALESCE(MAX(sort_order), -10) + 10 AS next_order "
            f"FROM {table} WHERE {column} = ?",
            (value,),
        ).fetchone()
    return int(row["next_order"])


def reorder_links(conn: sqlite3.Connection, ids: list[int]) -> None:
    now = utc_now()
    for index, link_id in enumerate(ids):
        conn.execute(
            "UPDATE links SET sort_order = ?, updated_at = ? WHERE id = ?",
            (index * 10, now, link_id),
        )


def search_links(conn: sqlite3.Connection, query: str, limit: int = 200) -> list[dict[str, Any]]:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    rows = conn.execute(
        """
        SELECT l.*, g.name AS group_name
        FROM links l
        JOIN groups g ON g.id = l.group_id
        WHERE l.title LIKE ? ESCAPE '\\' COLLATE NOCASE
           OR l.url LIKE ? ESCAPE '\\' COLLATE NOCASE
           OR l.description LIKE ? ESCAPE '\\' COLLATE NOCASE
        ORDER BY l.sort_order ASC, l.id ASC
        LIMIT ?
        """,
        (pattern, pattern, pattern, limit),
    ).fetchall()
    results: list[dict[str, Any]] = []
    for row in rows:
        item = serialize_link(row)
        item["group_name"] = row["group_name"]
        item["group_path"] = group_path(conn, row["group_id"])
        results.append(item)
    return results


def export_data(conn: sqlite3.Connection, version: str) -> dict[str, Any]:
    groups = [
        serialize_group(row)
        for row in conn.execute("SELECT * FROM groups ORDER BY sort_order ASC, id ASC")
    ]
    links = [
        serialize_link(row)
        for row in conn.execute("SELECT * FROM links ORDER BY sort_order ASC, id ASC")
    ]
    documents = [
        serialize_document(row, with_content=True)
        for row in conn.execute(
            "SELECT * FROM documents ORDER BY group_id ASC, sort_order ASC, id ASC"
        )
    ]
    return {
        "format": "lan-nav-export",
        "version": 1,
        "app_version": version,
        "exported_at": utc_now(),
        "groups": groups,
        "links": links,
        "documents": documents,
    }
