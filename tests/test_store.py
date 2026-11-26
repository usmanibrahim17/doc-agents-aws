from decimal import Decimal

from app.common import store


class FakeTable:
    def __init__(self):
        self.items = []

    def put_item(self, Item):
        self.items.append(Item)


def test_float_round_trip():
    item = store.to_dynamo({"total": 10.1, "lines": [{"amount": 2.0}]})
    assert item["total"] == Decimal("10.1")
    assert store.from_dynamo(item) == {"total": 10.1, "lines": [{"amount": 2}]}


def test_audit_entry_expires_in_seven_days():
    table = FakeTable()
    store.write_audit(table, "d1", "s1", "classifier", "accepted", confidence=0.5)
    store.write_audit(table, "d1", "s1", "extractor", "extracted")
    first, second = table.items
    assert first["sk"] != second["sk"]
    assert first["details"]["confidence"] == Decimal("0.5")
    assert abs(first["expires_at"] - store.expires_at()) <= 2
