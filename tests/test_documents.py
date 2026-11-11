from __future__ import annotations

from fastapi.testclient import TestClient

from .helpers import make_group


def make_document(
    client: TestClient,
    group_id: int,
    name: str = "README.md",
    content: str = "",
):
    response = client.post(
        f"/api/groups/{group_id}/documents",
        json={"name": name, "content": content},
    )
    return response


def test_document_crud_and_markdown_rendering(client: TestClient):
    group = make_group(client, "项目文档")

    created = make_document(client, group["id"], "notes", "# 备忘\n\n- 第一项\n- 第二项")
    assert created.status_code == 201, created.text
    document = created.json()
    assert document["name"] == "notes.md"
    assert document["group_id"] == group["id"]
    assert "<h1>备忘</h1>" in document["html"]
    assert "<li>第一项</li>" in document["html"]

    listed = client.get(f"/api/groups/{group['id']}/documents")
    assert listed.status_code == 200
    assert [item["name"] for item in listed.json()["documents"]] == ["notes.md"]

    readme = make_document(client, group["id"], "README.md", "# 说明")
    assert readme.status_code == 201
    listed = client.get(f"/api/groups/{group['id']}/documents").json()
    assert [item["name"] for item in listed["documents"]] == ["README.md", "notes.md"]

    tree = client.get("/api/tree").json()
    node = tree["groups"][0]
    assert node["direct_document_count"] == 2
    assert node["total_document_count"] == 2
    assert tree["total_documents"] == 2

    updated = client.patch(
        f"/api/documents/{document['id']}",
        json={"name": "memo.md", "content": "## 更新\n\n| A | B |\n| - | - |\n| 1 | 2 |"},
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["name"] == "memo.md"
    assert "<h2>更新</h2>" in body["html"]
    assert "<table>" in body["html"]

    fetched = client.get(f"/api/documents/{document['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["content"].startswith("## 更新")

    deleted = client.delete(f"/api/documents/{document['id']}")
    assert deleted.status_code == 200
    assert client.get(f"/api/documents/{document['id']}").status_code == 404


def test_document_name_validation_and_duplicates(client: TestClient):
    group = make_group(client, "文档校验")

    first = make_document(client, group["id"], "README.md", "正文")
    assert first.status_code == 201
    duplicate = make_document(client, group["id"], "readme.md", "重复")
    assert duplicate.status_code == 409

    invalid = make_document(client, group["id"], "sub/dir.md", "x")
    assert invalid.status_code == 400
    assert "路径" in invalid.json()["detail"]

    other_group = make_group(client, "默认文档名")
    default_name = make_document(client, other_group["id"], "", "无标题")
    assert default_name.status_code == 201
    assert default_name.json()["name"] == "README.md"


def test_markdown_disables_raw_html(client: TestClient):
    group = make_group(client, "安全")
    document = make_document(
        client, group["id"], "README.md", "<script>alert(1)</script>"
    ).json()
    assert "<script>" not in document["html"]
    assert "&lt;script&gt;" in document["html"]


def test_group_delete_counts_and_cascades_documents(client: TestClient):
    group = make_group(client, "会议记录")
    document = make_document(client, group["id"], "README.md", "# 周会").json()

    blocked = client.delete(f"/api/groups/{group['id']}")
    assert blocked.status_code == 409
    assert "文档" in blocked.json()["detail"]

    deleted = client.delete(f"/api/groups/{group['id']}", params={"cascade": "true"})
    assert deleted.status_code == 200
    assert deleted.json()["deleted_documents"] == 1
    assert client.get(f"/api/documents/{document['id']}").status_code == 404
    assert client.get(f"/api/groups/{group['id']}/documents").status_code == 404


def test_export_import_keeps_documents(client: TestClient):
    group = make_group(client, "导出文档")
    make_document(client, group["id"], "README.md", "# 保留内容")

    exported = client.get("/api/export").json()
    assert len(exported["documents"]) == 1
    assert exported["documents"][0]["content"] == "# 保留内容"

    make_group(client, "导入前分组")
    imported = client.post("/api/import", json=exported)
    assert imported.status_code == 200, imported.text
    assert imported.json()["documents"] == 1

    again = client.get("/api/export").json()
    assert len(again["documents"]) == 1
    assert again["documents"][0]["name"] == "README.md"
    assert again["documents"][0]["content"] == "# 保留内容"
