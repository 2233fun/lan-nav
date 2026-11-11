"""数据库备份与恢复（供 API 和命令行共用）。"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

TABLES = {"groups", "links"}


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")


def backup_database(database: str | Path, backup_dir: str | Path | None = None) -> Path:
    source_path = Path(database)
    if not source_path.is_file():
        raise FileNotFoundError(f"数据库不存在：{source_path}")
    target_dir = Path(backup_dir) if backup_dir else source_path.parent / "backups"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"lan-nav-{_timestamp()}.db"
    suffix = 1
    while target.exists():
        target = target_dir / f"lan-nav-{_timestamp()}-{suffix}.db"
        suffix += 1

    source = sqlite3.connect(str(source_path), timeout=10)
    destination = sqlite3.connect(str(target))
    try:
        source.backup(destination)
        destination.commit()
    finally:
        destination.close()
        source.close()
    return target


def validate_database(path: str | Path) -> None:
    """检查待恢复文件是否为带 groups/links 表的 SQLite 数据库。"""

    database = Path(path)
    if not database.is_file():
        raise ValueError(f"备份文件不存在：{database}")
    try:
        conn = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise ValueError(f"无法打开备份文件：{exc}") from exc
    try:
        check = conn.execute("PRAGMA integrity_check").fetchone()
        if not check or check[0] != "ok":
            raise ValueError("备份文件完整性检查失败")
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ('groups', 'links')"
        ).fetchall()
        if {row[0] for row in rows} != TABLES:
            raise ValueError("备份文件缺少 groups 或 links 表，不是有效的 lan-nav 数据库")
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"备份文件不是有效的 SQLite 数据库：{exc}") from exc
    finally:
        conn.close()


def restore_database(
    database: str | Path,
    source: str | Path,
    backup_dir: str | Path | None = None,
) -> tuple[Path | None, Path]:
    """先备份当前数据库，再用 source 覆盖。调用前应停止服务。"""

    target = Path(database)
    source_path = Path(source).resolve()
    validate_database(source_path)
    backup_path = None
    if target.is_file():
        backup_path = backup_database(target, backup_dir)

    target.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    target_conn = sqlite3.connect(str(target))
    try:
        source_conn.backup(target_conn)
        target_conn.commit()
        target_conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.Error as exc:
        raise ValueError(f"恢复数据库失败：{exc}") from exc
    finally:
        target_conn.close()
        source_conn.close()

    # 覆盖主库后，旧的 WAL/SHM 文件不能继续使用。
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(target) + suffix)
        try:
            sidecar.unlink()
        except FileNotFoundError:
            pass
    return backup_path, target


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="lan-nav 数据库备份/恢复")
    parser.add_argument("action", choices=["backup", "restore"])
    parser.add_argument("database")
    parser.add_argument("file", nargs="?")
    parser.add_argument("--backup-dir")
    args = parser.parse_args(argv)

    try:
        if args.action == "backup":
            path = backup_database(args.database, args.backup_dir)
            print(path)
        else:
            if not args.file:
                parser.error("restore 需要备份文件路径")
            previous, _ = restore_database(args.database, args.file, args.backup_dir)
            if previous:
                print(f"已恢复，恢复前备份：{previous}")
            else:
                print("已恢复（原数据库不存在，未生成恢复前备份）")
    except (OSError, ValueError, sqlite3.Error) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
