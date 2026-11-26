"""HTTP API for the demo site.

Public-demo isolation: every request carries an anonymous X-Session-Id, and every read, review
decision and export is limited to that session's documents. A document from another session is
indistinguishable from one that does not exist (404). Step Functions task tokens are read here
to resume a workflow and are never put in a response.
"""

import csv
import io
import json
import math
import re
import uuid
from datetime import UTC, datetime
from functools import lru_cache

from app.common import store
from app.common.agent import MAX_FILE_BYTES, Runtime
from app.common.config import CATEGORIES, env
from app.common.logs import log_json

SESSION_PATTERN = re.compile(r"^[A-Za-z0-9-]{16,64}$")
EXTENSIONS = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg"}
PUBLIC_FIELDS = (
    "doc_id",
    "filename",
    "status",
    "created_at",
    "updated_at",
    "document_type",
    "category",
    "fields",
    "first_fields",
    "first_issues",
    "issues",
    "tried",
    "suggestions",
    "explanation",
    "reason",
    "agents_run",
    "input_tokens",
    "output_tokens",
)
TEXT_FIELDS = ("vendor", "invoice_number", "date", "currency")
NUMBER_FIELDS = ("subtotal", "tax", "total")
URL_SECONDS = 300


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@lru_cache
def _client(name: str):
    import boto3

    if name == "s3":
        from botocore.config import Config

        config = Config(signature_version="s3v4", s3={"addressing_style": "virtual"})
        return boto3.client("s3", config=config)
    return boto3.client(name)


class Services:
    def __init__(self, runtime=None, s3=None, sfn=None):
        self.runtime = runtime or Runtime()
        self._s3, self._sfn = s3, sfn

    @property
    def s3(self):
        return self._s3 or _client("s3")

    @property
    def sfn(self):
        return self._sfn or _client("stepfunctions")


def _response(status: int, body, content_type: str = "application/json", **headers) -> dict:
    return {
        "statusCode": status,
        "headers": {"content-type": content_type, "cache-control": "no-store"} | headers,
        "body": body if isinstance(body, str) else json.dumps(body),
    }


def _public(document: dict) -> dict:
    return {k: document[k] for k in PUBLIC_FIELDS if k in document}


def _owned(services: Services, doc_id: str, session_id: str) -> dict:
    document = services.runtime.get_document(doc_id)
    if not document or document.get("session_id") != session_id:
        raise ApiError(404, "document not found")
    return document


def _session_documents(services: Services, session_id: str) -> list[dict]:
    request = {
        "IndexName": "by-session",
        "KeyConditionExpression": "session_id = :s",
        "ExpressionAttributeValues": {":s": session_id},
        "ScanIndexForward": False,
        "Limit": 100,
    }
    items = services.runtime.documents.query(**request)["Items"]
    return [store.from_dynamo(item) for item in items]


def _use_quota(services: Services, name: str, limit: int) -> None:
    """Atomic daily counter protecting the free-tier quota of a public endpoint."""
    today = datetime.now(UTC).date().isoformat()
    try:
        services.runtime.documents.update_item(
            Key={"doc_id": f"quota#{today}#{name}"},
            UpdateExpression="SET expires_at = :ttl ADD uploads :one",
            ConditionExpression="attribute_not_exists(uploads) OR uploads < :limit",
            ExpressionAttributeValues={":one": 1, ":limit": limit, ":ttl": store.expires_at()},
        )
    except Exception as exc:
        code = getattr(exc, "response", {}).get("Error", {}).get("Code")
        if code != "ConditionalCheckFailedException":
            raise
        message = "the demo's daily upload limit is reached; try again tomorrow"
        raise ApiError(429, message) from None


# --- Routes ---------------------------------------------------------------------------------


def create_upload(services, session_id, body, path):
    content_type = body.get("content_type")
    if content_type not in EXTENSIONS:
        raise ApiError(400, "only PDF, PNG and JPEG files are accepted")
    filename = re.sub(r"[^\w .()-]", "_", str(body.get("filename") or "document"))[:100]
    _use_quota(services, session_id, int(env("SESSION_DAILY_LIMIT", "60")))
    _use_quota(services, "all", int(env("DAILY_LIMIT", "300")))

    doc_id = uuid.uuid4().hex
    key = f"uploads/{session_id}/{doc_id}.{EXTENSIONS[content_type]}"
    now = datetime.now(UTC).isoformat()
    services.runtime.documents.put_item(
        Item={
            "doc_id": doc_id,
            "session_id": session_id,
            "s3_key": key,
            "mime_type": content_type,
            "filename": filename,
            "status": "uploading",
            "created_at": now,
            "expires_at": store.expires_at(),
        }
    )
    upload = services.s3.generate_presigned_post(
        env("UPLOADS_BUCKET"),
        key,
        Fields={"Content-Type": content_type},
        Conditions=[
            {"Content-Type": content_type},
            ["content-length-range", 1, MAX_FILE_BYTES],
        ],
        ExpiresIn=URL_SECONDS,
    )
    return _response(201, {"doc_id": doc_id, "upload": upload})


def list_documents(services, session_id, body, path):
    documents = _session_documents(services, session_id)
    return _response(200, {"documents": [_public(d) for d in documents]})


def _audit_entries(services, doc_id: str) -> list[dict]:
    items = services.runtime.audit.query(
        KeyConditionExpression="doc_id = :d", ExpressionAttributeValues={":d": doc_id}
    )["Items"]
    return [
        {k: store.from_dynamo(item.get(k)) for k in ("timestamp", "agent", "decision", "details")}
        for item in items
    ]


def get_document(services, session_id, body, path):
    document = _owned(services, path["id"], session_id)
    file_url = services.s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": env("UPLOADS_BUCKET"), "Key": document["s3_key"]},
        ExpiresIn=URL_SECONDS,
    )
    return _response(
        200,
        {
            "document": _public(document),
            "audit": _audit_entries(services, document["doc_id"]),
            "file_url": file_url,
        },
    )


def get_audit(services, session_id, body, path):
    document = _owned(services, path["id"], session_id)
    return _response(200, {"audit": _audit_entries(services, document["doc_id"])})


def list_reviews(services, session_id, body, path):
    documents = _session_documents(services, session_id)
    return _response(
        200, {"reviews": [_public(d) for d in documents if d["status"] == "needs_review"]}
    )


def _clean_text(value) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    return str(value).strip()[:200]


def _clean_number(name: str, value) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ApiError(400, f"{name} must be a number") from None
    if not math.isfinite(number) or abs(number) > 1e12:
        raise ApiError(400, f"{name} is out of range")
    return number


def clean_corrections(fields) -> dict:
    """Only known fields, with the right types. Anything else is dropped."""
    if not isinstance(fields, dict):
        raise ApiError(400, "fields must be an object")
    cleaned: dict = {}
    for name in TEXT_FIELDS:
        if name in fields:
            cleaned[name] = _clean_text(fields[name])
    for name in NUMBER_FIELDS:
        if name in fields:
            cleaned[name] = _clean_number(name, fields[name])
    if "line_items" in fields:
        lines = fields["line_items"]
        if not isinstance(lines, list) or len(lines) > 100:
            raise ApiError(400, "line_items must be a list of at most 100 lines")
        if not all(isinstance(line, dict) for line in lines):
            raise ApiError(400, "each line item must be an object")
        cleaned["line_items"] = [
            {"description": _clean_text(line.get("description"))}
            | {k: _clean_number(k, line.get(k)) for k in ("quantity", "unit_price", "amount")}
            for line in lines
        ]
    if fields.get("category") in CATEGORIES:
        cleaned["category"] = fields["category"]
    return cleaned


def decide_review(services, session_id, body, path):
    document = _owned(services, path["id"], session_id)
    decision = body.get("decision")
    if decision not in ("approved", "rejected"):
        raise ApiError(400, 'decision must be "approved" or "rejected"')
    corrections = clean_corrections(body.get("fields") or {})
    review = services.runtime.reviews.get_item(
        Key={"doc_id": document["doc_id"]}, ConsistentRead=True
    ).get("Item")
    if not review or review.get("session_id") != session_id:
        raise ApiError(409, "this document is not waiting for review")
    try:
        services.sfn.send_task_success(
            taskToken=review["task_token"],
            output=json.dumps({"decision": decision, "fields": corrections}),
        )
    except Exception as exc:
        code = getattr(exc, "response", {}).get("Error", {}).get("Code")
        if code not in ("TaskDoesNotExist", "TaskTimedOut", "InvalidToken"):
            raise
        raise ApiError(409, "this review has already been closed") from None
    services.runtime.delete_review(document["doc_id"])
    return _response(202, {"doc_id": document["doc_id"], "decision": decision})


def _cell(value):
    """Stop spreadsheet formula injection: text from a document must stay text."""
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return "" if value is None else value


def export_csv(services, session_id, body, path):
    columns = ["doc_id", "filename", "status", "document_type", "category"]
    values = ["vendor", "invoice_number", "date", "currency", "subtotal", "tax", "total"]
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(columns + values)
    for document in _session_documents(services, session_id):
        if document["status"] not in ("valid", "approved"):
            continue
        fields = document.get("fields", {})
        writer.writerow(
            [_cell(document.get(c)) for c in columns] + [_cell(fields.get(v)) for v in values]
        )
    return _response(
        200,
        out.getvalue(),
        "text/csv; charset=utf-8",
        **{"content-disposition": 'attachment; filename="documents.csv"'},
    )


ROUTES = {
    "POST /documents": create_upload,
    "GET /documents": list_documents,
    "GET /documents/{id}": get_document,
    "GET /documents/{id}/audit": get_audit,
    "GET /reviews": list_reviews,
    "POST /reviews/{id}": decide_review,
    "GET /export.csv": export_csv,
}


def process(event: dict, services: Services) -> dict:
    route = ROUTES.get(event.get("routeKey"))
    if route is None:
        return _response(404, {"error": "not found"})
    session_id = (event.get("headers") or {}).get("x-session-id", "")
    if not SESSION_PATTERN.match(session_id):
        return _response(400, {"error": "missing or invalid X-Session-Id header"})
    try:
        body = {}
        if event.get("body"):
            if len(event["body"]) > 50_000:
                raise ApiError(413, "request body too large")
            try:
                body = json.loads(event["body"])
            except ValueError:
                raise ApiError(400, "body must be JSON") from None
            if not isinstance(body, dict):
                raise ApiError(400, "body must be a JSON object")
        return route(services, session_id, body, event.get("pathParameters") or {})
    except ApiError as exc:
        return _response(exc.status, {"error": str(exc)})
    except Exception as exc:  # never leak internals to the browser
        log_json("api_error", route=event.get("routeKey"), error=repr(exc))
        return _response(500, {"error": "internal error"})


def handler(event, context):
    return process(event, Services())
