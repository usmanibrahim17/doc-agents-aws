"""JSON schemas the model must answer in."""

from app.common.config import CATEGORIES, DOCUMENT_TYPES

CLASSIFICATION = {
    "type": "object",
    "properties": {
        "document_type": {"type": "string", "enum": DOCUMENT_TYPES},
        "reason": {"type": "string", "description": "One short sentence."},
    },
    "required": ["document_type", "reason"],
}

ANOMALY = {
    "type": "object",
    "properties": {
        "anomalous": {"type": "boolean"},
        "severity": {"type": "string", "enum": ["low", "high"]},
        "explanation": {"type": "string", "description": "One short sentence."},
    },
    "required": ["anomalous", "severity", "explanation"],
}

# Every field is nullable: "not on the document" must be expressible, never invented.
_TEXT = {"type": ["string", "null"]}
_NUMBER = {"type": ["number", "null"]}

EXTRACTION = {
    "type": "object",
    "properties": {
        "vendor": _TEXT,
        "invoice_number": _TEXT,
        "date": {"type": ["string", "null"], "description": "ISO 8601, YYYY-MM-DD"},
        "currency": {"type": ["string", "null"], "description": "ISO 4217 code"},
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": _TEXT,
                    "quantity": _NUMBER,
                    "unit_price": _NUMBER,
                    "amount": _NUMBER,
                },
                "required": ["description", "quantity", "unit_price", "amount"],
            },
        },
        "subtotal": _NUMBER,
        "tax": _NUMBER,
        "total": _NUMBER,
        "category": {"type": "string", "enum": CATEGORIES},
    },
    "required": [
        "vendor",
        "invoice_number",
        "date",
        "currency",
        "line_items",
        "subtotal",
        "tax",
        "total",
        "category",
    ],
}
