"""What every agent Lambda needs: the uploaded file, and one call to record what it decided."""

from functools import lru_cache

from app.common import store
from app.common.config import env
from app.common.logs import log_json
from app.common.providers import MIME_TYPES, FilePart, JsonResult

MAX_FILE_BYTES = 5 * 1024 * 1024


class BadDocument(ValueError):
    """The upload itself is unusable (too large, unsupported type). Not worth retrying."""


@lru_cache
def _resource(name: str):
    import boto3

    return boto3.resource(name)


class Runtime:
    """AWS access for the agents. Tests pass fakes instead."""

    def __init__(self, documents=None, audit=None, bucket=None, reviews=None, vendors=None):
        self.documents = documents or _resource("dynamodb").Table(env("DOCUMENTS_TABLE"))
        self.audit = audit or _resource("dynamodb").Table(env("AUDIT_TABLE"))
        self._bucket, self._reviews, self._vendors = bucket, reviews, vendors

    @property
    def reviews(self):
        if self._reviews is None:
            self._reviews = _resource("dynamodb").Table(env("REVIEWS_TABLE"))
        return self._reviews

    def delete_review(self, doc_id: str) -> None:
        self.reviews.delete_item(Key={"doc_id": doc_id})

    def vendors(self) -> list[dict]:
        """The known-vendors table is small reference data, so a scan is fine."""
        if self._vendors is None:
            self._vendors = _resource("dynamodb").Table(env("VENDORS_TABLE"))
        return self._vendors.scan()["Items"]

    def get_document(self, doc_id: str) -> dict | None:
        item = self.documents.get_item(Key={"doc_id": doc_id}, ConsistentRead=True).get("Item")
        return store.from_dynamo(item) if item else None

    def documents_with_dup_key(self, key: str) -> list[str]:
        response = self.documents.query(
            IndexName="by-dup-key",
            KeyConditionExpression="dup_key = :key",
            ExpressionAttributeValues={":key": key},
        )
        return [item["doc_id"] for item in response["Items"]]

    @property
    def bucket(self):
        if self._bucket is None:
            self._bucket = _resource("s3").Bucket(env("UPLOADS_BUCKET"))
        return self._bucket

    def load_file(self, event: dict) -> FilePart:
        mime_type = event["mime_type"]
        if mime_type not in MIME_TYPES:
            raise BadDocument(f"unsupported file type {mime_type}")
        response = self.bucket.Object(event["s3_key"]).get()
        if response["ContentLength"] > MAX_FILE_BYTES:
            raise BadDocument("file is larger than 5 MB")
        return FilePart(response["Body"].read(), mime_type)

    def record(
        self,
        event: dict,
        agent: str,
        decision: str,
        updates: dict | None = None,
        result: JsonResult | None = None,
        **details,
    ) -> None:
        """Update the document item, then append the decision to the audit log."""
        names, values = {}, {":agent": [agent], ":none": []}
        sets = ["#agents = list_append(if_not_exists(#agents, :none), :agent)"]
        names["#agents"] = "agents_run"
        for index, (key, value) in enumerate((updates or {}).items()):
            names[f"#f{index}"] = key
            values[f":v{index}"] = store.to_dynamo(value)
            sets.append(f"#f{index} = :v{index}")
        expression = "SET " + ", ".join(sets)
        if result is not None:
            expression += " ADD input_tokens :in, output_tokens :out"
            values[":in"], values[":out"] = result.input_tokens, result.output_tokens
            details |= {
                "model": result.model,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            }
        self.documents.update_item(
            Key={"doc_id": event["doc_id"]},
            UpdateExpression=expression,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )
        store.write_audit(
            self.audit, event["doc_id"], event["session_id"], agent, decision, **details
        )
        log_json(
            "agent_decision",
            doc_id=event["doc_id"],
            agent=agent,
            decision=decision,
            input_tokens=result.input_tokens if result else 0,
            output_tokens=result.output_tokens if result else 0,
        )
