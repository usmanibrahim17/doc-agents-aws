"""Per-agent metrics. Pure functions over (truth record, processed document) pairs."""

from app.common.rules import MONETARY_FIELDS, is_monetary_change, normalize_vendor

FIELDS = ("vendor", "invoice_number", "date", "currency", "subtotal", "tax", "total")
AUTO_FINISHED = "valid"


def same(name: str, expected, actual) -> bool:
    if expected is None or actual is None:
        return expected is None and actual in (None, "")
    if isinstance(expected, int | float):
        return isinstance(actual, int | float) and abs(expected - actual) < 0.005
    if name == "vendor":
        # Spelling matters (the misspelled ones test the Resolver); case and suffix do not.
        return normalize_vendor(expected) == normalize_vendor(actual)
    return str(expected).strip().lower() == str(actual).strip().lower()


def line_matches(expected: list[dict], actual: list[dict]) -> int:
    """Lines whose description, quantity, unit price and amount are all right."""
    remaining = list(actual)
    correct = 0
    for line in expected:
        for index, other in enumerate(remaining):
            if all(
                same(key, line[key], other.get(key))
                for key in ("description", "quantity", "unit_price", "amount")
            ):
                correct += 1
                del remaining[index]
                break
    return correct


def money_changed(document: dict) -> bool:
    """True if a document saved with no person involved differs in money from what was read."""
    if document.get("status") != AUTO_FINISHED:
        return False
    before, after = document.get("first_fields") or {}, document.get("fields") or {}
    return any(
        is_monetary_change(name, before.get(name), after.get(name))
        for name in (*MONETARY_FIELDS, "line_items")
    )


def correctly_suggested(truth: dict, document: dict) -> bool:
    """Waiting for a person, with exactly the right values suggested and nothing applied."""
    suggestions = document.get("suggestions") or {}
    expected = truth["resolved_values"]
    return (
        document.get("status") == "needs_review"
        and set(suggestions) == set(expected)
        and all(same(k, v, suggestions[k]["value"]) for k, v in expected.items())
        and all(same(k, truth["fields"][k], document["fields"].get(k)) for k in expected)
    )


def ratio(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def score(pairs: list[tuple[dict, dict]]) -> dict:
    classified = field_ok = field_all = lines_ok = lines_all = category_ok = 0
    tp = fp = fn = exact = 0
    flagged = auto_fixed = unfixable = unfixable_to_human = changed_money = 0
    auto = [0, 0]  # non-monetary fixes: [applied correctly, expected]
    money = [0, 0]  # monetary fixes: [handled correctly, expected]
    per_field = {name: [0, 0] for name in FIELDS}
    mistakes: list[str] = []
    financial = 0

    for truth, document in pairs:
        doc_id = truth["id"]
        if document.get("document_type") == truth["document_type"]:
            classified += 1
        else:
            mistakes.append(f"{doc_id}: classified as {document.get('document_type')}")
        if truth["fields"] is None:
            continue
        financial += 1

        extracted = document.get("first_fields") or {}
        for name in FIELDS:
            ok = bool(extracted) and same(name, truth["fields"][name], extracted.get(name))
            per_field[name][0] += ok
            per_field[name][1] += 1
            field_ok += ok
            field_all += 1
            if not ok:
                mistakes.append(f"{doc_id}: {name} read as {extracted.get(name)!r}")
        expected_lines = truth["fields"]["line_items"]
        actual_lines = extracted.get("line_items") or []
        lines_ok += line_matches(expected_lines, actual_lines)
        lines_all += max(len(expected_lines), len(actual_lines))
        category_ok += document.get("category") == truth["category"]
        if document.get("category") != truth["category"]:
            mistakes.append(f"{doc_id}: category {document.get('category')}")

        found = {i["code"] for i in document.get("first_issues") or [] if i["severity"] == "error"}
        expected = set(truth["expected_issues"])
        is_bad, was_flagged = bool(expected), bool(found)
        tp += is_bad and was_flagged
        fp += not is_bad and was_flagged
        fn += is_bad and not was_flagged
        exact += found == expected
        if found != expected:
            mistakes.append(f"{doc_id}: expected issues {sorted(expected)}, found {sorted(found)}")

        status = document.get("status")
        fields_now = document.get("fields") or {}
        if was_flagged:
            flagged += 1
            auto_fixed += status == AUTO_FINISHED
        changed_money += money_changed(document)
        if is_bad and truth["resolvable"]:
            expected_values = truth["resolved_values"]
            applied = status == AUTO_FINISHED and all(
                same(k, v, fields_now.get(k)) for k, v in expected_values.items()
            )
            if set(expected_values) & set(MONETARY_FIELDS):
                money[1] += 1
                # Applied is also right when the stack allows automatic monetary fixes.
                ok = applied or correctly_suggested(truth, document)
                money[0] += ok
            else:
                auto[1] += 1
                ok = applied
                auto[0] += ok
            if not ok:
                mistakes.append(f"{doc_id}: expected a fix, ended {status}")
        if is_bad and not truth["resolvable"]:
            unfixable += 1
            unfixable_to_human += status == "needs_review"
            if status != "needs_review":
                mistakes.append(f"{doc_id}: needed a person, ended {status}")

    return {
        "documents": len(pairs),
        "financial_documents": financial,
        "classification_accuracy": ratio(classified, len(pairs)),
        "field_accuracy": ratio(field_ok, field_all),
        "per_field_accuracy": {n: ratio(*v) for n, v in per_field.items()},
        "line_item_accuracy": ratio(lines_ok, lines_all),
        "category_accuracy": ratio(category_ok, financial),
        "validation_precision": ratio(tp, tp + fp),
        "validation_recall": ratio(tp, tp + fn),
        "validation_exact_codes": ratio(exact, financial),
        "validation_counts": {"true_positive": tp, "false_positive": fp, "false_negative": fn},
        "auto_fix_rate": ratio(auto_fixed, flagged),
        "auto_fix_counts": {"fixed": auto_fixed, "flagged": flagged},
        "non_monetary_fixed_correctly": auto,
        "monetary_fixes_correct": money,
        "amounts_changed_without_a_person": changed_money,
        "unfixable_sent_to_human": [unfixable_to_human, unfixable],
        "mistakes": mistakes,
    }
