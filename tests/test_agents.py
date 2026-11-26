import pytest

from app.agents.classifier import handler as classifier
from app.agents.extractor import handler as extractor
from app.agents.finalizer import handler as finalizer
from app.common.agent import BadDocument
from app.common.providers import ProviderError
from tests.fakes import EVENT, FakeProvider, runtime


def test_classifier_rejects_junk_with_reason():
    run = runtime()
    provider = FakeProvider({"document_type": "not_financial", "reason": "A holiday photo."})
    assert classifier.process(EVENT, run, provider)["document_type"] == "not_financial"
    assert run.documents.updated()["status"] == "rejected"
    assert run.audit.items[0]["decision"] == "rejected"
    assert run.audit.items[0]["details"]["reason"] == "A holiday photo."


def test_classifier_refuses_unknown_type():
    with pytest.raises(ProviderError):
        classifier.process(EVENT, runtime(), FakeProvider({"document_type": "poem"}))


def test_extractor_stores_fields_and_normalizes_category():
    run = runtime()
    provider = FakeProvider({"vendor": "Tinlark Cafe", "total": 17.6, "category": "Snacks"})
    assert extractor.process(EVENT, run, provider) == {"category": "Other"}
    fields = run.documents.updated()["fields"]
    assert fields["vendor"] == "Tinlark Cafe"
    assert fields["line_items"] == []
    assert "invoice_number" in run.audit.items[0]["details"]["missing"]


def test_large_file_is_rejected():
    run = runtime(b"x" * (5 * 1024 * 1024 + 1))
    with pytest.raises(BadDocument):
        classifier.process(EVENT, run, FakeProvider())


def test_finalizer_marks_failure():
    run = runtime()
    event = EVENT | {"error": {"Error": "RateLimited", "Cause": "..."}}
    assert finalizer.process(event, run) == {"status": "failed"}
    assert run.documents.updated()["status"] == "failed"
