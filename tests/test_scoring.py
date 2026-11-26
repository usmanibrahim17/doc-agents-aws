from evals import scoring

TRUTH = {
    "id": "doc01",
    "document_type": "invoice",
    "category": "Meals",
    "fields": {
        "vendor": "Tinlark Cafe",
        "invoice_number": "A1",
        "date": "2026-11-01",
        "currency": "USD",
        "line_items": [{"description": "Tea", "quantity": 1, "unit_price": 2, "amount": 2}],
        "subtotal": 2,
        "tax": 0,
        "total": 9,
    },
    "expected_issues": ["total_mismatch"],
    "resolvable": True,
    "resolved_values": {"total": 2},
}


def test_perfect_extraction_and_correct_auto_fix():
    document = {
        "document_type": "invoice",
        "category": "Meals",
        "first_fields": TRUTH["fields"],
        "fields": TRUTH["fields"] | {"total": 2},
        "first_issues": [{"code": "total_mismatch", "severity": "error"}],
        "status": "valid",
    }
    result = scoring.score([(TRUTH, document)])
    assert result["field_accuracy"] == result["line_item_accuracy"] == 1
    assert result["validation_precision"] == result["validation_recall"] == 1
    assert result["fixable_fixed_correctly"] == [1, 1]
    assert result["mistakes"] == []


def test_missed_fault_lowers_recall():
    document = {"document_type": "receipt", "status": "valid", "first_issues": []}
    result = scoring.score([(TRUTH, document)])
    assert result["classification_accuracy"] == 0
    assert result["validation_recall"] == 0
    assert result["field_accuracy"] == 0
