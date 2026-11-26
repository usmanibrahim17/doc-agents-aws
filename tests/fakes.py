"""Minimal stand-ins for the AWS objects and the AI provider."""

import io
import json
from pathlib import Path

from app.common.agent import Runtime
from app.common.providers import JsonResult


class FakeTable:
    def __init__(self):
        self.items, self.updates = [], []

    def put_item(self, Item):
        self.items.append(Item)

    def update_item(self, **request):
        self.updates.append(request)

    def updated(self) -> dict:
        """All attributes SET by update_item calls, by real name."""
        out = {}
        for request in self.updates:
            names = request["ExpressionAttributeNames"]
            values = request["ExpressionAttributeValues"]
            for alias, name in names.items():
                value_key = alias.replace("#f", ":v")
                if value_key in values:
                    out[name] = values[value_key]
        return out


class FakeDocuments(FakeTable):
    """Documents table with reads. Updates are applied, so a later read sees them."""

    def __init__(self, *documents: dict):
        super().__init__()
        self.documents = {d["doc_id"]: dict(d) for d in documents}

    def get_item(self, Key, ConsistentRead=False):
        item = self.documents.get(Key["doc_id"])
        return {"Item": dict(item)} if item else {}

    def update_item(self, **request):
        super().update_item(**request)
        item = self.documents.setdefault(request["Key"]["doc_id"], {})
        for alias, name in request["ExpressionAttributeNames"].items():
            value_key = alias.replace("#f", ":v")
            if value_key in request["ExpressionAttributeValues"]:
                item[name] = request["ExpressionAttributeValues"][value_key]

    def query(self, IndexName, KeyConditionExpression, ExpressionAttributeValues):
        key = ExpressionAttributeValues[":key"]
        return {"Items": [d for d in self.documents.values() if d.get("dup_key") == key]}


class FakeVendors:
    def scan(self):
        path = Path(__file__).resolve().parent.parent / "data" / "vendors.json"
        return {
            "Items": [
                {"vendor_key": v["key"], "name": v["name"], "category": v["category"]}
                for v in json.loads(path.read_text())
            ]
        }


class FakeReviews(FakeTable):
    def __init__(self):
        super().__init__()
        self.deleted = []

    def delete_item(self, Key):
        self.deleted.append(Key["doc_id"])


class FakeBucket:
    def __init__(self, data: bytes = b"file"):
        self.data = data

    def Object(self, key):
        data = self.data

        class _Object:
            def get(self):
                return {"ContentLength": len(data), "Body": io.BytesIO(data)}

        return _Object()


class FakeProvider:
    def __init__(self, *replies: dict):
        self.replies, self.calls = list(replies), []

    def generate_json(self, system, prompt, schema, file=None, max_tokens=4096):
        self.calls.append({"prompt": prompt, "schema": schema, "file": file})
        return JsonResult(self.replies.pop(0), 100, 20, "fake")


def runtime(data: bytes = b"file", *documents: dict) -> Runtime:
    return Runtime(
        documents=FakeDocuments(*documents),
        audit=FakeTable(),
        bucket=FakeBucket(data),
        reviews=FakeReviews(),
        vendors=FakeVendors(),
    )


EVENT = {
    "doc_id": "d1",
    "session_id": "s1",
    "s3_key": "uploads/s1/d1.png",
    "mime_type": "image/png",
}
