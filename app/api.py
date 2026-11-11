"""LanNav 局域网网址导航 —— FastAPI 后端。"""

import asyncio
import re
import sqlite3
from collections.abc import Generator
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from markdown_it import MarkdownIt
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from .backup import backup_database
from .checker import LinkChecker
from .config import PROJECT_ROOT, Settings, load_settings
from .db import (
    build_tree,
    connect,
    export_data,
    find_document,
    find_group,
    find_link,
    group_ancestors,
    group_descendants,
    init_db,
    list_documents,
    next_sort,
    reorder_links,
    search_links,
    serialize_document,
    serialize_group,
    serialize_link,
    utc_now,
)

STATIC_DIR = PROJECT_ROOT / "app" / "static"
SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")


class GroupCreate(BaseModel):
    name: str = Field(max_length=80)
    parent_id: int | None = None
    sort_order: int | None = None


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    parent_id: int | None = None
    sort_order: int | None = None


class LinkCreate(BaseModel):
    group_id: int
    title: str = Field(max_length=200)
    url: str = Field(max_length=2000)
    description: str = Field(default="", max_length=1000)
    icon: str = Field(default="", max_length=2000)
    sort_order: int | None = None


class LinkUpdate(BaseModel):
    group_id: int | None = None
    title: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=2000)
    description: str | None = Field(default=None, max_length=1000)
    icon: str | None = Field(default=None, max_length=2000)
    sort_order: int | None = None


class LinkMove(BaseModel):
    group_id: int
    position: int | None = None
    before_id: int | None = None
    after_id: int | None = None


class CheckLinksRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=50)


class DocumentCreate(BaseModel):
    name: str = Field(default="README.md", max_length=120)
    content: str = Field(default="", max_length=200_000)
    sort_order: int | None = None


class DocumentUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    content: str | None = Field(default=None, max_length=200_000)


MARKDOWN = (
    MarkdownIt("commonmark", {"html": False, "linkify": True})
    .enable("table")
    .enable("strikethrough")
)


def render_markdown(source: str) -> str:
    return MARKDOWN.render(source or "")


def _load_check_targets(
    database: str | Path, ids: list[int]
) -> tuple[list[dict[str, Any]], list[int]]:
    conn = connect(database)
    try:
        placeholders = ", ".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT id, url FROM links WHERE id IN ({placeholders})", ids
        ).fetchall()
        found = {row["id"]: row["url"] for row in rows}
    finally:
        conn.close()
    missing = [link_id for link_id in ids if link_id not in found]
    targets = [{"id": link_id, "url": found[link_id]} for link_id in ids if link_id in found]
    return targets, missing


def _clean_name(value: str, field: str = "名称") -> str:
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail=f"{field}不能为空")
    return cleaned


def _clean_title(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="标题不能为空")
    return cleaned


def normalize_url(value: str, field: str = "网址") -> str:
    """允许 http/https；缺省协议时自动补 http://，支持 host:port。"""

    raw = value.strip()
    if not raw:
        raise HTTPException(status_code=400, detail=f"{field}不能为空")
    candidate = raw if SCHEME_RE.match(raw) else f"http://{raw}"
    if any(char in candidate for char in ("\n", "\r", "\t")) or " " in candidate:
        raise HTTPException(status_code=400, detail=f"{field}不能包含空格或换行")
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field}格式不正确：{exc}") from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise HTTPException(status_code=400, detail=f"{field}只支持 http 或 https")
    if not parsed.netloc or not parsed.hostname:
        raise HTTPException(status_code=400, detail=f"{field}缺少有效的主机名")
    if port is not None and not (1 <= port <= 65535):
        raise HTTPException(status_code=400, detail=f"{field}端口不合法")
    return candidate


def _clean_optional_icon(value: str | None) -> str:
    if value is None:
        return ""
    cleaned = value.strip()
    return normalize_url(cleaned, "图标地址") if cleaned else ""


def _group_or_404(conn: sqlite3.Connection, group_id: int) -> sqlite3.Row:
    row = find_group(conn, group_id)
    if row is None:
        raise HTTPException(status_code=404, detail="分组不存在")
    return row


def _link_or_404(conn: sqlite3.Connection, link_id: int) -> sqlite3.Row:
    row = find_link(conn, link_id)
    if row is None:
        raise HTTPException(status_code=404, detail="链接不存在")
    return row


def _document_or_404(conn: sqlite3.Connection, document_id: int) -> sqlite3.Row:
    row = find_document(conn, document_id)
    if row is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return row


def _clean_document_name(value: str | None) -> str:
    name = (value or "").strip() or "README.md"
    if len(name) > 120:
        raise HTTPException(status_code=400, detail="文档名过长（最多 120 字）")
    if "/" in name or "\\" in name or "\x00" in name or name in {".", ".."}:
        raise HTTPException(status_code=400, detail="文档名不能包含路径分隔符")
    if any(ord(char) < 32 for char in name):
        raise HTTPException(status_code=400, detail="文档名包含非法字符")
    if not name.lower().endswith(".md"):
        name = f"{name}.md"
    if len(name) > 120:
        raise HTTPException(status_code=400, detail="文档名过长（最多 120 字）")
    return name


def _document_response(row: sqlite3.Row) -> dict[str, Any]:
    item = serialize_document(row, with_content=True)
    item["html"] = render_markdown(row["content"])
    return item


def _assert_valid_parent(
    conn: sqlite3.Connection, group_id: int | None, parent_id: int | None
) -> None:
    if parent_id is None:
        return
    if group_id is not None and parent_id == group_id:
        raise HTTPException(status_code=400, detail="不能把分组移动到自身下")
    if find_group(conn, parent_id) is None:
        raise HTTPException(status_code=404, detail="目标父分组不存在")
    if group_id is None:
        return
    for ancestor in group_ancestors(conn, parent_id):
        if ancestor["id"] == group_id:
            raise HTTPException(status_code=400, detail="不能把分组移动到自己的子孙分组下")


def _validate_import(
    payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    raw_groups = payload.get("groups")
    raw_links = payload.get("links")
    raw_documents = payload.get("documents", [])
    if not isinstance(raw_groups, list) or not isinstance(raw_links, list):
        raise HTTPException(status_code=400, detail="导入文件必须包含 groups 和 links 数组")
    if not isinstance(raw_documents, list):
        raise HTTPException(status_code=400, detail="导入文件中的 documents 必须是数组")
    if len(raw_groups) > 5000 or len(raw_links) > 20000 or len(raw_documents) > 20000:
        raise HTTPException(
            status_code=400,
            detail="导入数据过大（最多 5000 个分组、20000 条链接、20000 篇文档）",
        )

    groups: list[dict[str, Any]] = []
    group_ids: set[int] = set()
    parent_map: dict[int, int | None] = {}
    for index, raw in enumerate(raw_groups, start=1):
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail=f"第 {index} 个分组格式不正确")
        old_id = raw.get("id")
        if not isinstance(old_id, int) or isinstance(old_id, bool):
            raise HTTPException(status_code=400, detail=f"第 {index} 个分组缺少有效的 id")
        if old_id in group_ids:
            raise HTTPException(status_code=400, detail=f"分组 id {old_id} 重复")
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            raise HTTPException(status_code=400, detail=f"第 {index} 个分组名称不能为空")
        if len(name.strip()) > 80:
            raise HTTPException(status_code=400, detail=f"第 {index} 个分组名称过长（最多 80 字）")
        parent_id = raw.get("parent_id")
        if parent_id is not None and (
            not isinstance(parent_id, int) or isinstance(parent_id, bool)
        ):
            raise HTTPException(status_code=400, detail=f"第 {index} 个分组的 parent_id 不合法")
        sort_order = raw.get("sort_order", 0)
        if not isinstance(sort_order, int) or isinstance(sort_order, bool):
            raise HTTPException(status_code=400, detail=f"第 {index} 个分组的排序值不合法")
        group_ids.add(old_id)
        parent_map[old_id] = parent_id
        groups.append(
            {
                "old_id": old_id,
                "name": name.strip(),
                "parent_id": parent_id,
                "sort_order": sort_order,
            }
        )

    for group in groups:
        parent_id = group["parent_id"]
        if parent_id is not None and parent_id not in group_ids:
            raise HTTPException(
                status_code=400,
                detail=f"分组「{group['name']}」的父分组不存在（id={parent_id}）",
            )
        seen = {group["old_id"]}
        cursor = parent_id
        while cursor is not None:
            if cursor in seen:
                raise HTTPException(status_code=400, detail="导入数据中存在循环分组关系")
            seen.add(cursor)
            cursor = parent_map.get(cursor)

    links: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_links, start=1):
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail=f"第 {index} 条链接格式不正确")
        group_id = raw.get("group_id")
        if not isinstance(group_id, int) or isinstance(group_id, bool) or group_id not in group_ids:
            raise HTTPException(status_code=400, detail=f"第 {index} 条链接的分组不存在")
        title = raw.get("title")
        if not isinstance(title, str) or not title.strip():
            raise HTTPException(status_code=400, detail=f"第 {index} 条链接标题不能为空")
        if len(title.strip()) > 200:
            raise HTTPException(status_code=400, detail=f"第 {index} 条链接标题过长")
        url = raw.get("url")
        if not isinstance(url, str):
            raise HTTPException(status_code=400, detail=f"第 {index} 条链接网址不合法")
        try:
            normalized_url = normalize_url(url)
        except HTTPException as exc:
            raise HTTPException(
                status_code=400, detail=f"第 {index} 条链接网址不合法：{exc.detail}"
            ) from exc
        description = raw.get("description", "")
        icon = raw.get("icon", "")
        if not isinstance(description, str) or len(description) > 1000:
            raise HTTPException(status_code=400, detail=f"第 {index} 条链接描述不合法")
        if not isinstance(icon, str) or len(icon) > 2000:
            raise HTTPException(status_code=400, detail=f"第 {index} 条链接图标地址不合法")
        try:
            normalized_icon = _clean_optional_icon(icon)
        except HTTPException as exc:
            raise HTTPException(
                status_code=400, detail=f"第 {index} 条链接图标不合法：{exc.detail}"
            ) from exc
        sort_order = raw.get("sort_order", 0)
        if not isinstance(sort_order, int) or isinstance(sort_order, bool):
            raise HTTPException(status_code=400, detail=f"第 {index} 条链接排序值不合法")
        links.append(
            {
                "group_id": group_id,
                "title": title.strip(),
                "url": normalized_url,
                "description": description,
                "icon": normalized_icon,
                "sort_order": sort_order,
            }
        )

    documents: list[dict[str, Any]] = []
    seen_documents: set[tuple[int, str]] = set()
    for index, raw in enumerate(raw_documents, start=1):
        if not isinstance(raw, dict):
            raise HTTPException(status_code=400, detail=f"第 {index} 篇文档格式不正确")
        group_id = raw.get("group_id")
        if not isinstance(group_id, int) or isinstance(group_id, bool) or group_id not in group_ids:
            raise HTTPException(status_code=400, detail=f"第 {index} 篇文档的分组不存在")
        name = raw.get("name", "README.md")
        if not isinstance(name, str):
            raise HTTPException(status_code=400, detail=f"第 {index} 篇文档名称不合法")
        try:
            normalized_name = _clean_document_name(name)
        except HTTPException as exc:
            raise HTTPException(
                status_code=400, detail=f"第 {index} 篇文档名称不合法：{exc.detail}"
            ) from exc
        content = raw.get("content", "")
        if not isinstance(content, str) or len(content) > 200_000:
            raise HTTPException(status_code=400, detail=f"第 {index} 篇文档内容不合法")
        sort_order = raw.get("sort_order", 0)
        if not isinstance(sort_order, int) or isinstance(sort_order, bool):
            raise HTTPException(status_code=400, detail=f"第 {index} 篇文档排序值不合法")
        key = (group_id, normalized_name.casefold())
        if key in seen_documents:
            raise HTTPException(
                status_code=400, detail=f"第 {index} 篇文档与同组文档重名：{normalized_name}"
            )
        seen_documents.add(key)
        documents.append(
            {
                "group_id": group_id,
                "name": normalized_name,
                "content": content,
                "sort_order": sort_order,
            }
        )
    return groups, links, documents


def create_app(
    settings: Settings | None = None,
    *,
    db_path: str | Path | None = None,
    checker: LinkChecker | None = None,
) -> FastAPI:
    if settings is None:
        settings = load_settings()
    if db_path is not None:
        settings = Settings(
            host=settings.host,
            port=settings.port,
            database=Path(db_path),
            config_path=settings.config_path,
            version=settings.version,
        )

    init_db(settings.database)
    app = FastAPI(
        title="LanNav 局域网导航 API",
        version=settings.version,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    app.state.link_checker = checker or LinkChecker()

    def get_db(request: Request) -> Generator[sqlite3.Connection, None, None]:
        conn = connect(request.app.state.settings.database)
        try:
            yield conn
        finally:
            conn.close()

    DBDep = Annotated[sqlite3.Connection, Depends(get_db)]

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        elif request.url.path == "/" or request.url.path.startswith("/static/"):
            # 前端资源总是先向服务端校验（ETag/Last-Modified），
            # 避免 Safari 等浏览器长期使用缓存里的旧 JS/CSS。
            response.headers.setdefault("Cache-Control", "no-cache")
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException):
        detail = exc.detail
        if detail == "Not Found":
            detail = "请求的资源不存在"
        return JSONResponse({"detail": detail}, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        location = ".".join(str(part) for part in first.get("loc", []) if part != "body")
        message = f"请求参数不合法（{location}）" if location else "请求参数不合法"
        return JSONResponse(
            status_code=422,
            content={"detail": message, "errors": jsonable_encoder(exc.errors())},
        )

    @app.get("/api/health")
    def health(conn: DBDep) -> dict[str, Any]:
        counts = conn.execute(
            "SELECT (SELECT COUNT(*) FROM groups) AS groups, (SELECT COUNT(*) FROM links) AS links"
        ).fetchone()
        return {
            "status": "ok",
            "version": settings.version,
            "database": "ok",
            "groups": counts["groups"],
            "links": counts["links"],
        }

    @app.get("/api/tree")
    def tree(conn: DBDep) -> dict[str, Any]:
        data = build_tree(conn)
        data.update({"version": settings.version, "generated_at": utc_now()})
        return data

    @app.post("/api/check-links")
    async def check_links(
        body: CheckLinksRequest,
        request: Request,
    ) -> dict[str, Any]:
        ids = list(dict.fromkeys(body.ids))
        targets, missing = await asyncio.to_thread(_load_check_targets, settings.database, ids)
        if missing:
            missing_text = "、".join(str(link_id) for link_id in missing[:20])
            raise HTTPException(status_code=404, detail=f"链接不存在：{missing_text}")
        results = await request.app.state.link_checker.check(targets)
        return {
            "results": results,
            "count": len(results),
            "cached": sum(1 for result in results if result.get("cached")),
        }

    @app.get("/api/search")
    def search(
        conn: DBDep,
        q: Annotated[str, Query(max_length=200)] = "",
        limit: Annotated[int, Query(ge=1, le=500)] = 200,
    ) -> dict[str, Any]:
        query = q.strip()
        if not query:
            return {"query": "", "count": 0, "results": []}
        results = search_links(conn, query, limit)
        return {"query": query, "count": len(results), "results": results}

    @app.post("/api/groups", status_code=201)
    def create_group(body: GroupCreate, conn: DBDep) -> dict[str, Any]:
        name = _clean_name(body.name, "分组名称")
        _assert_valid_parent(conn, None, body.parent_id)
        sort_order = (
            body.sort_order
            if body.sort_order is not None
            else next_sort(conn, "groups", "parent_id", body.parent_id)
        )
        now = utc_now()
        with conn:
            cursor = conn.execute(
                "INSERT INTO groups (parent_id, name, sort_order, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (body.parent_id, name, sort_order, now, now),
            )
        row = _group_or_404(conn, int(cursor.lastrowid))
        item = serialize_group(row)
        item.update({"links": [], "children": [], "direct_link_count": 0, "total_link_count": 0})
        return item

    @app.patch("/api/groups/{group_id}")
    def update_group(group_id: int, body: GroupUpdate, conn: DBDep) -> dict[str, Any]:
        row = _group_or_404(conn, group_id)
        fields = body.model_fields_set
        new_name = row["name"]
        new_parent = row["parent_id"]
        new_sort = row["sort_order"]
        parent_changed = False

        if "name" in fields:
            if body.name is None:
                raise HTTPException(status_code=400, detail="分组名称不能为空")
            new_name = _clean_name(body.name, "分组名称")
        if "parent_id" in fields:
            _assert_valid_parent(conn, group_id, body.parent_id)
            parent_changed = body.parent_id != row["parent_id"]
            new_parent = body.parent_id
        if "sort_order" in fields:
            if body.sort_order is None:
                raise HTTPException(status_code=400, detail="排序值不能为空")
            new_sort = body.sort_order
        elif parent_changed:
            new_sort = next_sort(conn, "groups", "parent_id", new_parent)

        with conn:
            conn.execute(
                "UPDATE groups SET name = ?, parent_id = ?, sort_order = ?, updated_at = ? "
                "WHERE id = ?",
                (new_name, new_parent, new_sort, utc_now(), group_id),
            )
        return serialize_group(_group_or_404(conn, group_id))

    @app.delete("/api/groups/{group_id}")
    def delete_group(
        group_id: int,
        conn: DBDep,
        cascade: Annotated[bool, Query()] = False,
    ) -> dict[str, Any]:
        _group_or_404(conn, group_id)
        descendant_ids = group_descendants(conn, group_id)
        placeholders = ",".join("?" for _ in descendant_ids)
        link_count = conn.execute(
            f"SELECT COUNT(*) AS n FROM links WHERE group_id IN ({placeholders})",
            descendant_ids,
        ).fetchone()["n"]
        document_count = conn.execute(
            f"SELECT COUNT(*) AS n FROM documents WHERE group_id IN ({placeholders})",
            descendant_ids,
        ).fetchone()["n"]
        child_count = len(descendant_ids) - 1
        if not cascade and (child_count or link_count or document_count):
            parts = []
            if child_count:
                parts.append(f"{child_count} 个子分组")
            if link_count:
                parts.append(f"{link_count} 条链接")
            if document_count:
                parts.append(f"{document_count} 篇文档")
            raise HTTPException(
                status_code=409,
                detail=f"分组内还有{'和'.join(parts)}，确认后请使用级联删除（cascade=true）",
            )
        with conn:
            conn.execute("DELETE FROM groups WHERE id = ?", (group_id,))
        return {
            "ok": True,
            "deleted_groups": len(descendant_ids),
            "deleted_links": link_count,
            "deleted_documents": document_count,
        }

    @app.post("/api/links", status_code=201)
    def create_link(body: LinkCreate, conn: DBDep) -> dict[str, Any]:
        _group_or_404(conn, body.group_id)
        title = _clean_title(body.title)
        url = normalize_url(body.url)
        icon = _clean_optional_icon(body.icon)
        description = body.description.strip()
        sort_order = (
            body.sort_order
            if body.sort_order is not None
            else next_sort(conn, "links", "group_id", body.group_id)
        )
        now = utc_now()
        with conn:
            cursor = conn.execute(
                "INSERT INTO links "
                "(group_id, title, url, description, icon, sort_order, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (body.group_id, title, url, description, icon, sort_order, now, now),
            )
        return serialize_link(_link_or_404(conn, int(cursor.lastrowid)))

    @app.patch("/api/links/{link_id}")
    def update_link(link_id: int, body: LinkUpdate, conn: DBDep) -> dict[str, Any]:
        row = _link_or_404(conn, link_id)
        fields = body.model_fields_set
        group_id = row["group_id"]
        title = row["title"]
        url = row["url"]
        description = row["description"]
        icon = row["icon"]
        sort_order = row["sort_order"]
        group_changed = False

        if "group_id" in fields:
            if body.group_id is None:
                raise HTTPException(status_code=400, detail="链接必须属于一个分组")
            _group_or_404(conn, body.group_id)
            group_changed = body.group_id != row["group_id"]
            group_id = body.group_id
        if "title" in fields:
            if body.title is None:
                raise HTTPException(status_code=400, detail="标题不能为空")
            title = _clean_title(body.title)
        if "url" in fields:
            if body.url is None:
                raise HTTPException(status_code=400, detail="网址不能为空")
            url = normalize_url(body.url)
        if "description" in fields:
            description = (body.description or "").strip()
        if "icon" in fields:
            icon = _clean_optional_icon(body.icon)
        if "sort_order" in fields:
            if body.sort_order is None:
                raise HTTPException(status_code=400, detail="排序值不能为空")
            sort_order = body.sort_order
        elif group_changed:
            sort_order = next_sort(conn, "links", "group_id", group_id)

        with conn:
            conn.execute(
                "UPDATE links SET group_id = ?, title = ?, url = ?, description = ?, "
                "icon = ?, sort_order = ?, updated_at = ? WHERE id = ?",
                (group_id, title, url, description, icon, sort_order, utc_now(), link_id),
            )
        return serialize_link(_link_or_404(conn, link_id))

    @app.post("/api/links/{link_id}/move")
    def move_link(link_id: int, body: LinkMove, conn: DBDep) -> dict[str, Any]:
        _link_or_404(conn, link_id)
        _group_or_404(conn, body.group_id)
        rows = conn.execute(
            "SELECT id FROM links WHERE group_id = ? AND id <> ? "
            "ORDER BY sort_order ASC, id ASC",
            (body.group_id, link_id),
        ).fetchall()
        ids = [row["id"] for row in rows]

        target_index = len(ids)
        if body.before_id is not None:
            if body.before_id not in ids:
                raise HTTPException(status_code=400, detail="before_id 不在目标分组中")
            target_index = ids.index(body.before_id)
        elif body.after_id is not None:
            if body.after_id not in ids:
                raise HTTPException(status_code=400, detail="after_id 不在目标分组中")
            target_index = ids.index(body.after_id) + 1
        elif body.position is not None:
            target_index = max(0, min(body.position, len(ids)))

        ids.insert(target_index, link_id)
        with conn:
            conn.execute(
                "UPDATE links SET group_id = ?, updated_at = ? WHERE id = ?",
                (body.group_id, utc_now(), link_id),
            )
            reorder_links(conn, ids)
        item = serialize_link(_link_or_404(conn, link_id))
        item["position"] = target_index
        return item

    @app.delete("/api/links/{link_id}")
    def delete_link(link_id: int, conn: DBDep) -> dict[str, Any]:
        _link_or_404(conn, link_id)
        with conn:
            conn.execute("DELETE FROM links WHERE id = ?", (link_id,))
        return {"ok": True}

    @app.get("/api/groups/{group_id}/documents")
    def get_group_documents(group_id: int, conn: DBDep) -> dict[str, Any]:
        _group_or_404(conn, group_id)
        rows = list_documents(conn, group_id)
        return {
            "group_id": group_id,
            "documents": [serialize_document(row) for row in rows],
        }

    @app.post("/api/groups/{group_id}/documents", status_code=201)
    def create_document(
        group_id: int, body: DocumentCreate, conn: DBDep
    ) -> dict[str, Any]:
        _group_or_404(conn, group_id)
        name = _clean_document_name(body.name)
        sort_order = (
            body.sort_order
            if body.sort_order is not None
            else next_sort(conn, "documents", "group_id", group_id)
        )
        now = utc_now()
        try:
            with conn:
                cursor = conn.execute(
                    "INSERT INTO documents "
                    "(group_id, name, content, sort_order, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (group_id, name, body.content, sort_order, now, now),
                )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="同名文档已存在") from exc
        row = find_document(conn, int(cursor.lastrowid))
        assert row is not None
        return _document_response(row)

    @app.get("/api/documents/{document_id}")
    def get_document(document_id: int, conn: DBDep) -> dict[str, Any]:
        row = _document_or_404(conn, document_id)
        return _document_response(row)

    @app.patch("/api/documents/{document_id}")
    def update_document(
        document_id: int, body: DocumentUpdate, conn: DBDep
    ) -> dict[str, Any]:
        row = _document_or_404(conn, document_id)
        name = row["name"]
        content = row["content"]
        if body.name is not None:
            name = _clean_document_name(body.name)
        if body.content is not None:
            content = body.content
        now = utc_now()
        try:
            with conn:
                conn.execute(
                    "UPDATE documents SET name = ?, content = ?, updated_at = ? WHERE id = ?",
                    (name, content, now, document_id),
                )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="同名文档已存在") from exc
        row = find_document(conn, document_id)
        assert row is not None
        return _document_response(row)

    @app.delete("/api/documents/{document_id}")
    def delete_document(document_id: int, conn: DBDep) -> dict[str, Any]:
        _document_or_404(conn, document_id)
        with conn:
            conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        return {"ok": True}

    @app.get("/api/export")
    def export_all(conn: DBDep) -> dict[str, Any]:
        return export_data(conn, settings.version)

    @app.post("/api/import")
    def import_all(
        payload: Annotated[dict[str, Any], Body()],
        conn: DBDep,
    ) -> dict[str, Any]:
        groups, links, documents = _validate_import(payload)
        backup_path = backup_database(settings.database)
        mapping: dict[int, int] = {}
        now = utc_now()
        with conn:
            conn.execute("DELETE FROM documents")
            conn.execute("DELETE FROM links")
            conn.execute("DELETE FROM groups")
            for group in groups:
                cursor = conn.execute(
                    "INSERT INTO groups (parent_id, name, sort_order, created_at, updated_at) "
                    "VALUES (NULL, ?, ?, ?, ?)",
                    (group["name"], group["sort_order"], now, now),
                )
                mapping[group["old_id"]] = int(cursor.lastrowid)
            for group in groups:
                if group["parent_id"] is not None:
                    conn.execute(
                        "UPDATE groups SET parent_id = ? WHERE id = ?",
                        (mapping[group["parent_id"]], mapping[group["old_id"]]),
                    )
            for link in links:
                conn.execute(
                    "INSERT INTO links "
                    "(group_id, title, url, description, icon, sort_order, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        mapping[link["group_id"]],
                        link["title"],
                        link["url"],
                        link["description"],
                        link["icon"],
                        link["sort_order"],
                        now,
                        now,
                    ),
                )
            for document in documents:
                conn.execute(
                    "INSERT INTO documents "
                    "(group_id, name, content, sort_order, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        mapping[document["group_id"]],
                        document["name"],
                        document["content"],
                        document["sort_order"],
                        now,
                        now,
                    ),
                )
        return {
            "ok": True,
            "groups": len(groups),
            "links": len(links),
            "documents": len(documents),
            "backup": str(backup_path),
        }

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
