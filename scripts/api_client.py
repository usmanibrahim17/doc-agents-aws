"""Tiny client for the public API, used by the load test and the evals (standard library only)."""

import json
import mimetypes
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

FINISHED = {"valid", "approved", "rejected", "failed", "needs_review"}


class Client:
    def __init__(self, base_url: str, session_id: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.session_id = session_id or str(uuid.uuid4())

    def request(self, method: str, path: str, body: dict | None = None):
        """Returns parsed JSON (or text for CSV). Retries when the API throttles (429/503)."""
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(6):
            request = urllib.request.Request(
                self.base_url + path,
                data=data,
                method=method,
                headers={"x-session-id": self.session_id, "content-type": "application/json"},
            )
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    raw = response.read().decode()
                    if "json" in response.headers.get("content-type", ""):
                        return json.loads(raw)
                    return raw
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 503) or attempt == 5:
                    detail = exc.read().decode(errors="replace")[:200]
                    raise RuntimeError(f"{method} {path}: HTTP {exc.code} {detail}") from None
                time.sleep(2**attempt)

    def upload(self, path: Path) -> str:
        content_type = mimetypes.guess_type(path.name)[0]
        created = self.request(
            "POST", "/documents", {"filename": path.name, "content_type": content_type}
        )
        _post_file(created["upload"], path, content_type)
        return created["doc_id"]

    def documents(self) -> dict[str, dict]:
        return {d["doc_id"]: d for d in self.request("GET", "/documents")["documents"]}

    def wait(self, doc_ids: list[str], timeout: float = 900) -> dict[str, dict]:
        """Poll until every document is finished (or waiting for a person)."""
        deadline = time.monotonic() + timeout
        while True:
            documents = self.documents()
            pending = [d for d in doc_ids if documents.get(d, {}).get("status") not in FINISHED]
            if not pending:
                return {d: documents[d] for d in doc_ids}
            if time.monotonic() > deadline:
                raise TimeoutError(f"{len(pending)} document(s) still pending")
            time.sleep(4)


def _post_file(upload: dict, path: Path, content_type: str) -> None:
    """multipart/form-data POST to S3: the signed fields first, the file last."""
    boundary = uuid.uuid4().hex
    body = bytearray()
    for name, value in upload["fields"].items():
        body += (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'
        ).encode()
    body += (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="upload"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode()
    body += path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        upload["url"],
        data=bytes(body),
        method="POST",
        headers={"content-type": f"multipart/form-data; boundary={boundary}"},
    )
    urllib.request.urlopen(request, timeout=60).close()
