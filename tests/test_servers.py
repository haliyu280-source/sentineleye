from sqlalchemy import func, select

from conftest import ADMIN, agent_headers
from sentineleye.db import SessionLocal
from sentineleye.models import AgentToken, Metric
from sentineleye.security import TOKEN_PATTERN, hash_secret


def test_register_returns_token_once_and_stores_only_a_hash(client):
    response = client.post(
        "/api/servers",
        json={"name": "db-01", "environment": "production", "thresholds": {"cpu": 90}},
        headers=ADMIN,
    )
    assert response.status_code == 201
    body = response.json()
    token = body["agent_token"]["token"]
    assert TOKEN_PATTERN.match(token)
    assert body["server"]["status"] == "unknown"
    assert body["server"]["thresholds"] == {"cpu": 90.0, "memory": 85.0, "disk": 80.0}

    with SessionLocal() as db:
        stored = db.scalar(select(AgentToken))
        secret = token.split("_", 2)[2]
        assert stored.secret_hash == hash_secret(secret)
        assert secret not in stored.secret_hash

    server_id = body["server"]["id"]
    for path in ("/api/servers", f"/api/servers/{server_id}", f"/api/servers/{server_id}/tokens"):
        assert secret not in client.get(path, headers=ADMIN).text


def test_duplicate_names_are_rejected(client, register):
    register("web-01")
    response = client.post("/api/servers", json={"name": "web-01"}, headers=ADMIN)
    assert response.status_code == 409


def test_registration_input_is_validated(client):
    for bad in ({"name": ""}, {"name": "x" * 101}, {"name": "<script>"}, {"name": "ok", "thresholds": {"cpu": 150}},
                {"name": "ok", "unexpected": True}):
        assert client.post("/api/servers", json=bad, headers=ADMIN).status_code == 422


def test_list_get_and_update(client, register):
    server_id, _ = register("web-01")
    register("web-02")

    names = [s["name"] for s in client.get("/api/servers", headers=ADMIN).json()]
    assert names == ["web-01", "web-02"]

    response = client.patch(
        f"/api/servers/{server_id}",
        json={"description": "Front-end node", "thresholds": {"memory": 70}},
        headers=ADMIN,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["description"] == "Front-end node"
    assert body["thresholds"]["memory"] == 70.0
    assert body["threshold_overrides"]["memory"] == 70.0

    # null threshold falls back to the global default
    body = client.patch(f"/api/servers/{server_id}", json={"thresholds": {"memory": None}}, headers=ADMIN).json()
    assert body["thresholds"]["memory"] == 85.0

    assert client.get("/api/servers/999", headers=ADMIN).status_code == 404


def test_disabled_server_cannot_report(client, register, submit):
    server_id, token = register()
    client.patch(f"/api/servers/{server_id}", json={"enabled": False}, headers=ADMIN)
    assert submit(server_id, token).status_code == 403
    assert client.get(f"/api/servers/{server_id}", headers=ADMIN).json()["status"] == "disabled"


def test_delete_removes_server_with_history(client, register, submit):
    server_id, token = register()
    assert submit(server_id, token).status_code == 202
    assert client.delete(f"/api/servers/{server_id}", headers=ADMIN).status_code == 204
    assert client.get(f"/api/servers/{server_id}", headers=ADMIN).status_code == 404
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Metric)) == 0
        assert db.scalar(select(func.count()).select_from(AgentToken)) == 0
    assert submit(server_id, token).status_code == 401


def test_revoke_reissue_and_additional_tokens(client, register, submit):
    server_id, token = register()
    token_id = token.split("_")[1]

    assert submit(server_id, token).status_code == 202
    revoked = client.post(f"/api/servers/{server_id}/tokens/{token_id}/revoke", headers=ADMIN)
    assert revoked.status_code == 200 and revoked.json()["revoked_at"]
    assert submit(server_id, token).status_code == 401

    extra = client.post(f"/api/servers/{server_id}/tokens", headers=ADMIN).json()["token"]
    assert submit(server_id, extra).status_code == 202

    replacement = client.post(f"/api/servers/{server_id}/tokens/reissue", headers=ADMIN).json()["token"]
    assert submit(server_id, extra).status_code == 401  # reissue revokes every older token
    assert submit(server_id, replacement).status_code == 202

    tokens = client.get(f"/api/servers/{server_id}/tokens", headers=ADMIN).json()
    assert len(tokens) == 3
    assert sum(1 for t in tokens if t["revoked_at"] is None) == 1
    assert client.post(f"/api/servers/{server_id}/tokens/ffffffffffffffff/revoke", headers=ADMIN).status_code == 404


def test_expired_tokens_are_rejected(client, register, submit):
    from datetime import timedelta

    from sentineleye.timeutil import utcnow

    server_id, token = register()
    with SessionLocal() as db:
        record = db.scalar(select(AgentToken))
        record.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    assert submit(server_id, token).status_code == 401


def test_token_header_variants_are_rejected(client, register, sample):
    server_id, token = register()
    payload = sample(server_id)
    for headers in ({}, {"Authorization": token}, {"Authorization": "Bearer se_bad"}, agent_headers(token + "x")):
        assert client.post("/api/agent/metrics", json=payload, headers=headers).status_code == 401
