from __future__ import annotations

from fastapi.testclient import TestClient


def make_group(client: TestClient, name: str, parent_id: int | None = None, sort_order: int | None = None):
    payload = {"name": name, "parent_id": parent_id}
    if sort_order is not None:
        payload["sort_order"] = sort_order
    response = client.post("/api/groups", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def make_link(
    client: TestClient,
    group_id: int,
    title: str,
    url: str = "https://example.com",
    description: str = "",
    icon: str = "",
    sort_order: int | None = None,
):
    payload = {
        "group_id": group_id,
        "title": title,
        "url": url,
        "description": description,
        "icon": icon,
    }
    if sort_order is not None:
        payload["sort_order"] = sort_order
    response = client.post("/api/links", json=payload)
    assert response.status_code == 201, response.text
    return response.json()
