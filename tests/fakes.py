"""Minimal stand-ins for the AWS objects and the AI provider."""

import io

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


def runtime(data: bytes = b"file") -> Runtime:
    return Runtime(documents=FakeTable(), audit=FakeTable(), bucket=FakeBucket(data))


EVENT = {
    "doc_id": "d1",
    "session_id": "s1",
    "s3_key": "uploads/s1/d1.png",
    "mime_type": "image/png",
}
