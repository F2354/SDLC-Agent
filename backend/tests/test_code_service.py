import uuid

from app.services.code_service import parse_code_files


def unique_name(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def test_parse_code_files():
    content = (
        "[FILE] app/main.py\n"
        "from fastapi import FastAPI\n\n"
        "app = FastAPI()\n"
        "[FILE] requirements.txt\n"
        "fastapi\nuvicorn\n"
    )
    entries = parse_code_files(content)
    assert len(entries) == 2
    assert entries[0][0] == "app/main.py"
    assert "FastAPI" in entries[0][1]
    assert entries[1][0] == "requirements.txt"


def test_code_tree_and_run_without_code(client):
    username = unique_name("code_owner")
    reg = client.post(
        "/api/auth/register",
        json={"username": username, "password": "secret123"},
    )
    headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
    project = client.post(
        "/api/projects",
        headers=headers,
        json={"name": "代码验证项目", "process_model_code": "waterfall"},
    )
    project_id = project.json()["id"]

    tree = client.get(f"/api/projects/{project_id}/code/tree", headers=headers)
    assert tree.status_code == 200
    assert tree.json()["exists"] is False

    run = client.post(f"/api/projects/{project_id}/code/run", headers=headers)
    assert run.status_code == 200
    assert run.json()["ok"] is False
