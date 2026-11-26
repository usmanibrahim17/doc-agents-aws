import json

from app.api import handler as api
from app.starter import handler as starter
from tests.fakes import runtime

MINE, OTHER = "a" * 32, "b" * 32
DOC = {
    "doc_id": "d1",
    "session_id": MINE,
    "s3_key": f"uploads/{MINE}/d1.png",
    "mime_type": "image/png",
    "status": "needs_review",
    "created_at": "2026-11-01",
    "dup_key": "secret-hash",
    "fields": {"vendor": "=HYPERLINK(1)", "total": 5},
}


class Reviews:
    def __init__(self, item=None, count=0):
        self.item, self.count, self.deleted = item, count, []

    def get_item(self, Key, ConsistentRead):
        return {"Item": self.item} if self.item else {}

    def delete_item(self, Key):
        self.deleted.append(Key["doc_id"])

    def scan(self, Select):
        return {"Count": self.count}


class Sfn:
    class exceptions:
        class ExecutionAlreadyExists(Exception):
            pass

    def __init__(self, running=0):
        self.running, self.started, self.sent = running, [], []

    def get_paginator(self, name):
        running = self.running

        class Pages:
            def paginate(self, **kwargs):
                return [{"executions": [{}] * running}]

        return Pages()

    def start_execution(self, **kwargs):
        self.started.append(kwargs)

    def send_task_success(self, **kwargs):
        self.sent.append(kwargs)


class S3:
    def generate_presigned_url(self, *args, **kwargs):
        return "https://signed"


def call(services, route, session=MINE, body=None, doc_id="d1"):
    event = {
        "routeKey": route,
        "headers": {"x-session-id": session},
        "pathParameters": {"id": doc_id},
        "body": json.dumps(body) if body else None,
    }
    return api.process(event, services)


def services(monkeypatch, review=None):
    monkeypatch.setenv("UPLOADS_BUCKET", "b")
    run = runtime(b"f", DOC)
    run._reviews = Reviews(review)
    run.audit.query = lambda **kwargs: {"Items": []}
    run.documents.query = lambda **kwargs: {
        "Items": [
            d
            for d in run.documents.documents.values()
            if d["session_id"] == kwargs["ExpressionAttributeValues"][":s"]
        ]
    }
    return api.Services(runtime=run, s3=S3(), sfn=Sfn())


def test_other_sessions_see_nothing(monkeypatch):
    review = {"doc_id": "d1", "session_id": MINE, "task_token": "TOKEN"}
    svc = services(monkeypatch, review)
    for route in ("GET /documents/{id}", "GET /documents/{id}/audit"):
        assert call(svc, route, OTHER)["statusCode"] == 404
    decision = {"decision": "approved"}
    assert call(svc, "POST /reviews/{id}", OTHER, decision)["statusCode"] == 404
    assert svc.sfn.sent == []
    assert json.loads(call(svc, "GET /documents", OTHER)["body"]) == {"documents": []}
    assert "d1" not in call(svc, "GET /export.csv", OTHER)["body"]


def test_session_header_is_required(monkeypatch):
    assert call(services(monkeypatch), "GET /documents", "short")["statusCode"] == 400


def test_responses_never_contain_server_secrets(monkeypatch):
    svc = services(monkeypatch, {"doc_id": "d1", "session_id": MINE, "task_token": "TOKEN"})
    for route in ("GET /documents", "GET /documents/{id}", "GET /reviews"):
        body = call(svc, route)["body"]
        assert "TOKEN" not in body and "secret-hash" not in body


def test_approval_resumes_with_cleaned_fields(monkeypatch):
    svc = services(monkeypatch, {"doc_id": "d1", "session_id": MINE, "task_token": "TOKEN"})
    body = {"decision": "approved", "fields": {"total": "12.5", "session_id": OTHER}}
    assert call(svc, "POST /reviews/{id}", body=body)["statusCode"] == 202
    assert json.loads(svc.sfn.sent[0]["output"])["fields"] == {"total": 12.5}
    assert svc.runtime.reviews.deleted == ["d1"]
    bad = {"decision": "approved", "fields": {"total": "NaN"}}
    assert call(svc, "POST /reviews/{id}", body=bad)["statusCode"] == 400


def test_csv_neutralizes_formulas(monkeypatch):
    svc = services(monkeypatch)
    svc.runtime.documents.documents["d1"]["status"] = "valid"
    assert "'=HYPERLINK(1)" in call(svc, "GET /export.csv")["body"]


def test_starter_waits_when_slots_are_full():
    run = runtime(b"f", DOC | {"status": "uploading"})
    run._reviews = Reviews(count=2)
    sfn = Sfn(running=5)  # 5 running, 2 of them waiting for a person -> 3 active
    assert starter.start(DOC["s3_key"], run, sfn, "arn") is False
    assert sfn.started == []
    assert run.documents.documents["d1"]["status"] == "queued"

    sfn.running = 4
    assert starter.start(DOC["s3_key"], run, sfn, "arn") is True
    assert sfn.started[0]["name"] == "d1"


def test_starter_ignores_unknown_or_foreign_keys():
    run = runtime(b"f", DOC | {"status": "uploading"})
    sfn = Sfn()
    assert starter.start(f"uploads/{OTHER}/d1.png", run, sfn, "arn") is True
    assert starter.start("uploads/x.png", run, sfn, "arn") is True
    assert sfn.started == []


def test_retry_delay_grows_and_is_capped():
    assert 12 <= starter.retry_delay_seconds(1) <= 18
    assert starter.retry_delay_seconds(10) <= starter.RETRY_MAX_SECONDS
