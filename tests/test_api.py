from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from .helpers import make_group, make_link


def test_health_and_static_page(client: TestClient):
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["database"] == "ok"

    page = client.get("/")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    assert "邻页" in page.text
    assert page.headers["cache-control"] == "no-cache"

    script = client.get("/static/app.js")
    assert script.status_code == 200
    assert "javascript" in script.headers["content-type"]
    assert script.headers["cache-control"] == "no-cache"


def test_three_level_groups_and_tree_counts(client: TestClient):
    root = make_group(client, "工作台", sort_order=20)
    child = make_group(client, "内部系统", parent_id=root["id"], sort_order=20)
    grandchild = make_group(client, "机房监控", parent_id=child["id"], sort_order=10)
    another_root = make_group(client, "生活", sort_order=10)

    make_link(client, root["id"], "Wiki", "http://192.168.1.2:8080/wiki")
    make_link(client, child["id"], "NAS", "http://nas.local", description="家庭存储")
    make_link(client, grandchild["id"], "摄像头", "http://192.168.1.8:9000")
    make_link(client, another_root["id"], "相册", "http://photos.local")

    tree = client.get("/api/tree").json()
    assert tree["total_groups"] == 4
    assert tree["total_links"] == 4
    # 排序值小的「生活」排前面
    assert [group["name"] for group in tree["groups"]] == ["生活", "工作台"]

    work = tree["groups"][1]
    assert work["name"] == "工作台"
    assert work["direct_link_count"] == 1
    assert work["total_link_count"] == 3
    internal = work["children"][0]
    assert internal["name"] == "内部系统"
    assert internal["total_link_count"] == 2
    assert internal["children"][0]["name"] == "机房监控"
    assert internal["children"][0]["links"][0]["title"] == "摄像头"


def test_move_group_rejects_cycles(client: TestClient):
    a = make_group(client, "A")
    b = make_group(client, "B", parent_id=a["id"])
    c = make_group(client, "C", parent_id=b["id"])

    self_move = client.patch(f"/api/groups/{a['id']}", json={"parent_id": a["id"]})
    assert self_move.status_code == 400
    assert "自身" in self_move.json()["detail"]

    cycle = client.patch(f"/api/groups/{a['id']}", json={"parent_id": c["id"]})
    assert cycle.status_code == 400
    assert "子孙" in cycle.json()["detail"]

    missing = client.patch(f"/api/groups/{a['id']}", json={"parent_id": 99999})
    assert missing.status_code == 404
    assert "父分组" in missing.json()["detail"]

    moved = client.patch(f"/api/groups/{c['id']}", json={"parent_id": None})
    assert moved.status_code == 200
    assert moved.json()["parent_id"] is None
    tree = client.get("/api/tree").json()
    assert {group["name"] for group in tree["groups"]} == {"A", "C"}


def test_group_rename_and_sort(client: TestClient):
    first = make_group(client, "第一", sort_order=20)
    second = make_group(client, "第二", sort_order=10)

    renamed = client.patch(f"/api/groups/{first['id']}", json={"name": "  已改名  "})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "已改名"

    tree = client.get("/api/tree").json()
    assert [group["name"] for group in tree["groups"]] == ["第二", "已改名"]
    assert [group["sort_order"] for group in tree["groups"]] == [10, 20]

    resorted = client.patch(f"/api/groups/{second['id']}", json={"sort_order": 30})
    assert resorted.status_code == 200
    tree = client.get("/api/tree").json()
    assert [group["name"] for group in tree["groups"]] == ["已改名", "第二"]


def test_delete_group_requires_confirmation_and_cascades(client: TestClient):
    root = make_group(client, "根")
    child = make_group(client, "子", parent_id=root["id"])
    make_link(client, root["id"], "根链接")
    make_link(client, child["id"], "子链接")

    denied = client.delete(f"/api/groups/{root['id']}")
    assert denied.status_code == 409
    assert "1 个子分组" in denied.json()["detail"]
    assert "2 条链接" in denied.json()["detail"]
    assert client.get("/api/tree").json()["total_groups"] == 2

    deleted = client.delete(f"/api/groups/{root['id']}?cascade=true")
    assert deleted.status_code == 200
    assert deleted.json() == {
        "ok": True,
        "deleted_groups": 2,
        "deleted_links": 2,
        "deleted_documents": 0,
    }
    tree = client.get("/api/tree").json()
    assert tree["groups"] == []
    assert tree["total_links"] == 0

    missing = client.delete(f"/api/groups/{root['id']}")
    assert missing.status_code == 404


def test_link_crud_url_validation_and_order(client: TestClient):
    group = make_group(client, "工具")
    other = make_group(client, "其他")

    missing_group = client.post(
        "/api/links",
        json={"group_id": 9999, "title": "X", "url": "https://example.com"},
    )
    assert missing_group.status_code == 404

    blank_title = client.post(
        "/api/links",
        json={"group_id": group["id"], "title": "   ", "url": "https://example.com"},
    )
    assert blank_title.status_code == 400
    assert "标题" in blank_title.json()["detail"]

    ftp = client.post(
        "/api/links",
        json={"group_id": group["id"], "title": "FTP", "url": "ftp://example.com"},
    )
    assert ftp.status_code == 400
    assert "http" in ftp.json()["detail"]

    local = make_link(
        client,
        group["id"],
        "  路由器  ",
        "192.168.1.1:8080/admin",
        description="  主路由管理  ",
        sort_order=30,
    )
    assert local["title"] == "路由器"
    assert local["url"] == "http://192.168.1.1:8080/admin"
    assert local["description"] == "主路由管理"

    second = make_link(client, group["id"], "第二个", sort_order=10)
    third = make_link(client, group["id"], "第三个", sort_order=20)
    links = client.get("/api/tree").json()["groups"][0]["links"]
    assert [link["title"] for link in links] == ["第二个", "第三个", "路由器"]

    updated = client.patch(
        f"/api/links/{second['id']}",
        json={
            "title": "已编辑",
            "url": "https://example.org/path",
            "description": "说明",
            "icon": "https://example.org/icon.png",
            "group_id": other["id"],
        },
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["title"] == "已编辑"
    assert body["group_id"] == other["id"]
    assert body["icon"] == "https://example.org/icon.png"

    moved = client.post(
        f"/api/links/{third['id']}/move",
        json={"group_id": group["id"], "before_id": local["id"]},
    )
    assert moved.status_code == 200
    assert moved.json()["position"] == 0
    links = client.get("/api/tree").json()["groups"][0]["links"]
    assert [link["title"] for link in links] == ["第三个", "路由器"]

    deleted = client.delete(f"/api/links/{local['id']}")
    assert deleted.status_code == 200
    assert client.get("/api/tree").json()["total_links"] == 2
    assert client.delete(f"/api/links/{local['id']}").status_code == 404


def test_search_title_url_description_and_order(client: TestClient):
    group = make_group(client, "家庭")
    make_link(client, group["id"], "NAS 管理", "http://192.168.1.10:5000", "家庭照片", sort_order=20)
    make_link(client, group["id"], "路由器", "http://router.local", "网络设置", sort_order=10)
    make_link(client, group["id"], "相册", "http://photos.local", "旅行记录", sort_order=30)

    assert client.get("/api/search?q=").json()["count"] == 0
    by_title = client.get("/api/search?q=nas").json()
    assert by_title["count"] == 1
    assert by_title["results"][0]["title"] == "NAS 管理"
    assert by_title["results"][0]["group_path"] == "家庭"

    by_url = client.get("/api/search?q=5000").json()
    assert by_url["count"] == 1

    by_desc = client.get("/api/search?q=网络").json()
    assert by_desc["count"] == 1

    no_result = client.get("/api/search?q=不存在").json()
    assert no_result["count"] == 0

    # 通配符按字面处理
    assert client.get("/api/search?q=%25").json()["count"] == 0

    tree = client.get("/api/tree").json()
    links = tree["groups"][0]["links"]
    assert [link["title"] for link in links] == ["路由器", "NAS 管理", "相册"]


def test_export_import_roundtrip_and_backup(client: TestClient, settings):
    root = make_group(client, "根")
    child = make_group(client, "子", parent_id=root["id"])
    make_link(client, child["id"], "入口", "https://example.com", "描述", "https://example.com/favicon.ico")

    exported = client.get("/api/export")
    assert exported.status_code == 200
    data = exported.json()
    assert data["format"] == "lan-nav-export"
    assert len(data["groups"]) == 2
    assert len(data["links"]) == 1

    make_group(client, "导入前的额外分组")
    imported = client.post("/api/import", json=data)
    assert imported.status_code == 200, imported.text
    result = imported.json()
    assert result["groups"] == 2
    assert result["links"] == 1
    assert Path(result["backup"]).is_file()
    assert Path(result["backup"]).parent == settings.database.parent / "backups"

    tree = client.get("/api/tree").json()
    assert tree["total_groups"] == 2
    assert tree["total_links"] == 1
    assert tree["groups"][0]["name"] == "根"
    assert tree["groups"][0]["children"][0]["name"] == "子"
    assert tree["groups"][0]["children"][0]["links"][0]["url"] == "https://example.com"

    again = client.get("/api/export").json()
    assert [group["name"] for group in again["groups"]] == ["根", "子"]
    assert again["links"][0]["title"] == "入口"


def test_import_validation_does_not_destroy_data(client: TestClient):
    root = make_group(client, "保留")
    make_link(client, root["id"], "保留链接")

    bad_groups = {
        "groups": [
            {"id": 1, "parent_id": 2, "name": "A", "sort_order": 0},
            {"id": 2, "parent_id": 1, "name": "B", "sort_order": 0},
        ],
        "links": [],
    }
    response = client.post("/api/import", json=bad_groups)
    assert response.status_code == 400
    assert "循环" in response.json()["detail"]

    bad_link = {
        "groups": [{"id": 1, "parent_id": None, "name": "A", "sort_order": 0}],
        "links": [{"group_id": 1, "title": "坏链接", "url": "ftp://example.com"}],
    }
    response = client.post("/api/import", json=bad_link)
    assert response.status_code == 400
    assert "网址" in response.json()["detail"]

    tree = client.get("/api/tree").json()
    assert tree["groups"][0]["name"] == "保留"
    assert tree["total_links"] == 1


def test_validation_and_not_found_messages_are_chinese(client: TestClient):
    invalid = client.post("/api/groups", json={})
    assert invalid.status_code == 422
    assert "请求参数不合法" in invalid.json()["detail"]

    missing = client.get("/api/not-here")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "请求的资源不存在"

    group = make_group(client, "校验组")
    bad_url = client.post(
        "/api/links",
        json={"group_id": group["id"], "title": "x", "url": "http://"},
    )
    assert bad_url.status_code == 400
    assert "网址" in bad_url.json()["detail"]


def test_export_is_valid_utf8_json(client: TestClient):
    group = make_group(client, "中文分组")
    make_link(client, group["id"], "中文标题", "http://例子.local")
    payload = client.get("/api/export").content.decode("utf-8")
    data = json.loads(payload)
    assert data["groups"][0]["name"] == "中文分组"
