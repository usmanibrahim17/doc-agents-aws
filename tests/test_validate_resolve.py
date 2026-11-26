from datetime import date

from app.agents.finalizer import handler as finalizer
from app.agents.resolver import handler as resolver
from app.agents.reviewer import handler as reviewer
from app.agents.validator import handler as validator
from app.common import rules
from tests.fakes import EVENT, FakeProvider, runtime

CLEAN = {"anomalous": False, "severity": "low", "explanation": ""}


def fields(**changes):
    base = {
        "vendor": "Tinlark Cafe",
        "invoice_number": "TL-1",
        "date": "2026-11-01",
        "currency": "USD",
        "line_items": [{"description": "Latte", "quantity": 2, "unit_price": 5, "amount": 10}],
        "subtotal": 10,
        "tax": 1,
        "total": 11,
    }
    return base | changes


def document(doc_id="d1", created="2026-11-02T00:00:00", **changes):
    return {"doc_id": doc_id, "created_at": created, "fields": fields(**changes)}


def codes(issues):
    return {i["code"] for i in issues}


def test_rules():
    today = date(2026, 11, 27)
    assert rules.check_fields(fields(), today) == []
    assert codes(rules.check_fields(fields(total=99), today)) == {"total_mismatch"}
    assert codes(rules.check_fields(fields(tax=4.7, total=14.7), today)) == {"tax_rate"}
    assert codes(rules.check_fields(fields(date="2027-01-01"), today)) == {"bad_date"}
    assert codes(rules.check_fields(fields(invoice_number=None), today)) == {"missing_field"}
    credit = fields(
        line_items=[{"description": "Refund", "quantity": 1, "unit_price": -10, "amount": -10}],
        subtotal=-10,
        tax=-1,
        total=-11,
    )
    assert rules.check_fields(credit, today) == []


def test_vendor_matching():
    vendors = [{"vendor_key": "quillfeather paper", "name": "Quillfeather Paper Co."}]
    assert rules.find_vendor("QUILLFEATHER PAPER CO", vendors)
    assert rules.find_vendor("Quilfeather Paper", vendors) is None
    assert rules.fuzzy_vendor("Quilfeather Paper", vendors)[0] == vendors[0]
    assert rules.fuzzy_vendor("Zebra Mining", vendors) is None


def test_validator_passes_clean_document():
    run = runtime(b"f", document())
    assert validator.process(EVENT, run, FakeProvider(CLEAN))["status"] == "valid"


def test_validator_flags_only_the_later_duplicate():
    first = document("d0", "2026-11-01T00:00:00")
    first["dup_key"] = rules.duplicate_key("s1", first["fields"])
    run = runtime(b"f", first, document())
    provider = FakeProvider(CLEAN)
    assert validator.process(EVENT, run, provider)["status"] == "invalid"
    assert codes(run.documents.documents["d1"]["issues"]) == {"duplicate"}
    assert provider.calls == []  # no model call once the rules have already failed
    assert validator.process(EVENT | {"doc_id": "d0"}, run, provider)["status"] == "valid"


def test_wrong_total_is_fixed_after_rereading_confirms_it():
    run = runtime(b"f", document(total=19))
    assert validator.process(EVENT, run, FakeProvider())["status"] == "invalid"
    reread = {"subtotal": 10, "tax": 1, "total": 19}
    outcome = resolver.process(EVENT, run, FakeProvider(reread))
    assert outcome == {"attempts": 1, "changed": True}
    assert float(run.documents.documents["d1"]["fields"]["total"]) == 11
    assert validator.process(EVENT, run, FakeProvider(CLEAN))["status"] == "valid"
    assert "corrected" in codes(run.documents.documents["d1"]["issues"])


def test_misspelled_vendor_is_fixed_without_a_model_call():
    run = runtime(b"f", document(vendor="Tinlark Caffe"))
    validator.process(EVENT, run, FakeProvider())
    provider = FakeProvider()
    assert resolver.process(EVENT, run, provider)["changed"]
    assert provider.calls == []
    assert run.documents.documents["d1"]["fields"]["vendor"] == "Tinlark Cafe"


def test_unfixable_goes_to_review_then_human_corrects():
    run = runtime(b"f", document(invoice_number=None))
    validator.process(EVENT, run, FakeProvider())
    outcome = resolver.process(EVENT, run, FakeProvider({"invoice_number": None}))
    assert outcome["changed"] is False
    reviewer.process({"task_token": "SECRET-TOKEN", "input": EVENT}, run)
    item = run.reviews.items[0]
    assert item["task_token"] == "SECRET-TOKEN"
    assert "document number is missing" in item["explanation"]
    assert "Re-read invoice_number" in item["explanation"]
    assert "SECRET-TOKEN" not in str(run.audit.items)  # the token never reaches the audit log

    review = {"decision": "approved", "fields": {"invoice_number": "TL-9", "doc_id": "x"}}
    assert finalizer.process(EVENT | {"review": review}, run) == {"status": "approved"}
    saved = run.documents.documents["d1"]
    assert saved["fields"]["invoice_number"] == "TL-9"
    assert saved["doc_id"] == "d1"
    assert run.reviews.deleted == ["d1"]
