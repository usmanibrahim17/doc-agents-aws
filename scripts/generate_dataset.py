"""Generate the synthetic evaluation set from ground-truth data.

    python scripts/generate_dataset.py

Every document is rendered FROM its ground-truth record, so the truth is exact by construction.
All companies and people are fictional. Output is deterministic (fixed seed):

    evals/data/documents/<id>.pdf|jpg    evals/data/truth/<id>.json    web/samples/
"""

import json
import random
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from fpdf import FPDF
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
DOCUMENTS = ROOT / "evals" / "data" / "documents"
TRUTH = ROOT / "evals" / "data" / "truth"
SAMPLES = ROOT / "web" / "samples"
CUSTOMER = ["Hollowpine Studio (fictional)", "14 Imaginary Lane", "Nowhere Falls"]
TITLES = {"invoice": "INVOICE", "receipt": "RECEIPT", "credit_note": "CREDIT NOTE"}

VENDORS = {v["key"]: v for v in json.loads((ROOT / "data" / "vendors.json").read_text())}
CATALOG = {
    "Office supplies": [
        ("A4 copier paper, box", 24.5),
        ("Gel pens, pack of 12", 9.8),
        ("Lever arch files", 3.4),
        ("Desk organiser", 14.0),
        ("Toner", 61.0),
    ],
    "Software": [
        ("Team licence, monthly", 49.0),
        ("Extra storage 1 TB", 12.0),
        ("Priority support", 150.0),
        ("API usage bundle", 80.0),
    ],
    "Utilities": [
        ("Electricity usage", 212.4),
        ("Water supply charge", 48.75),
        ("Standing charge", 19.9),
        ("Meter service", 12.5),
    ],
    "Professional services": [
        ("Consulting hours", 135.0),
        ("Workshop facilitation", 900.0),
        ("Report preparation", 420.0),
        ("Contract review", 275.0),
    ],
    "Travel": [
        ("Rail ticket, return", 86.0),
        ("Hotel night", 129.0),
        ("Airport transfer", 42.0),
        ("Booking fee", 6.5),
    ],
    "Meals": [
        ("Filter coffee", 3.2),
        ("Soup of the day", 6.8),
        ("Sandwich platter", 28.0),
        ("Sparkling water", 2.5),
        ("Team lunch buffet", 18.5),
    ],
    "Other": [("Pallet delivery", 74.0), ("Packing materials", 22.0), ("Customs handling", 35.0)],
}
PREFIX = {"invoice": "INV", "receipt": "R", "credit_note": "CN"}


# --- Ground truth -----------------------------------------------------------------------------


def make_record(rng, index, doc_type, vendor_key, tax_rate):
    vendor = VENDORS[vendor_key]
    items = rng.sample(CATALOG[vendor["category"]], rng.randint(2, 3))
    sign = -1 if doc_type == "credit_note" else 1
    lines = []
    for description, price in items:
        quantity = rng.randint(1, 6)
        unit = round(sign * price, 2)
        lines.append(
            {
                "description": description,
                "quantity": quantity,
                "unit_price": unit,
                "amount": round(quantity * unit, 2),
            }
        )
    subtotal = round(sum(line["amount"] for line in lines), 2)
    tax = round(subtotal * tax_rate, 2)
    issued = date(2026, 9, 1) + timedelta(days=rng.randint(0, 75))
    return {
        "document_type": doc_type,
        "category": vendor["category"],
        "fields": {
            "vendor": vendor["name"],
            "invoice_number": f"{PREFIX[doc_type]}-{2600 + index * 7:05d}",
            "date": issued.isoformat(),
            "currency": rng.choice(["USD", "EUR", "GBP"]),
            "line_items": lines,
            "subtotal": subtotal,
            "tax": tax,
            "total": round(subtotal + tax, 2),
        },
        "tax_rate": tax_rate,
        "faults": [],
        "expected_issues": [],
        "resolvable": None,
        "resolved_values": {},
        "duplicate_of": None,
    }


def fault(record, name, code, resolvable, **resolved):
    record["faults"].append(name)
    record["expected_issues"].append(code)
    record["resolvable"] = resolvable
    record["resolved_values"] = resolved


def build_records(rng):
    keys = list(VENDORS)
    # 28 documents here; two duplicates are appended below, for 30 financial documents.
    types = ["invoice"] * 16 + ["receipt"] * 8 + ["credit_note"] * 4
    rng.shuffle(types)
    records = []
    for index, doc_type in enumerate(types):
        rate = rng.choice([0.0, 0.05, 0.075, 0.1, 0.2])
        records.append(make_record(rng, index, doc_type, keys[index % len(keys)], rate))

    plain = [i for i, r in enumerate(records) if r["document_type"] != "credit_note"]
    rng.shuffle(plain)
    take = iter(plain)

    for offset in (12.0, -9.5, 100.0):  # printed total is wrong
        record = records[next(take)]
        correct = record["fields"]["total"]
        record["fields"]["total"] = round(correct + offset, 2)
        fault(record, "wrong_total", "total_mismatch", True, total=correct)
    for name in ("invoice_number", "invoice_number", "date"):
        record = records[next(take)]
        record["fields"][name] = None
        fault(record, f"missing_{name}", "missing_field", False)
    for _ in range(3):
        record = records[next(take)]
        correct = record["fields"]["vendor"]
        word = max(correct.split(), key=len)
        cut = len(word) // 2
        record["fields"]["vendor"] = correct.replace(word, word[:cut] + word[cut + 1 :])
        fault(record, "misspelled_vendor", "unknown_vendor", True, vendor=correct)
    for rate in (0.45, 0.38):
        record = records[next(take)]
        fields = record["fields"]
        record["tax_rate"] = rate
        fields["tax"] = round(fields["subtotal"] * rate, 2)
        fields["total"] = round(fields["subtotal"] + fields["tax"], 2)
        fault(record, "odd_tax_rate", "tax_rate", False)
    record = records[next(take)]
    record["fields"]["vendor"] = "Gloamreach Robotics"
    fault(record, "unknown_vendor", "unknown_vendor", False)

    for number, record in enumerate(records, start=1):
        record["id"] = f"doc{number:02d}"
    clean = [r for r in records if not r["faults"]]
    for number, original in enumerate(rng.sample(clean, 2), start=len(records) + 1):
        copy = json.loads(json.dumps(original))
        copy["id"], copy["duplicate_of"] = f"doc{number:02d}", original["id"]
        fault(copy, "duplicate", "duplicate", False)
        records.append(copy)
    return records


# --- Rendering --------------------------------------------------------------------------------


def money(value):
    return f"{value:,.2f}"


def shown_date(value, style):
    issued = date.fromisoformat(value)
    return [value, f"{issued:%d %B %Y}", f"{issued:%B %d, %Y}", f"{issued:%d %b %Y}"][style % 4]


def meta_rows(record, style):
    fields = record["fields"]
    rows = []
    if fields["invoice_number"]:
        label = {
            "invoice": "Invoice no.",
            "receipt": "Receipt no.",
            "credit_note": "Credit note no.",
        }[record["document_type"]]
        rows.append((label, fields["invoice_number"]))
    if fields["date"]:
        rows.append(("Date", shown_date(fields["date"], style)))
    rows.append(("Currency", fields["currency"]))
    return rows


def total_rows(record):
    fields = record["fields"]
    label = "Total credited" if record["document_type"] == "credit_note" else "Total"
    return [
        ("Subtotal", money(fields["subtotal"])),
        (f"Tax ({record['tax_rate'] * 100:g}%)", money(fields["tax"])),
        (f"{label} {fields['currency']}", money(fields["total"])),
    ]


def render_pdf(record, style, path):
    layout = style % 3
    pdf = FPDF(format="A4" if layout != 2 else (110, 200))
    pdf.creation_date = datetime(2026, 11, 1, tzinfo=UTC)
    pdf.add_page()
    font = ["Helvetica", "Times", "Courier"][layout]
    width = pdf.epw
    title, vendor = TITLES[record["document_type"]], record["fields"]["vendor"]

    def row(text, size=10, bold="", align="L", h=6):
        pdf.set_font(font, bold, size)
        pdf.cell(width, h, text, align=align, new_x="LMARGIN", new_y="NEXT")

    if layout == 0:  # classic: vendor top left, title below
        row(vendor, 18, "B", h=10)
        row("Fictional company, demo data only", 8)
        row(title, 14, "B", "R", 10)
        for label, value in meta_rows(record, style):
            row(f"{label}: {value}", align="R")
    elif layout == 1:  # modern: coloured band, meta on the left
        pdf.set_fill_color(40, 60, 110)
        pdf.rect(0, 0, 210, 32, "F")
        pdf.set_text_color(255, 255, 255)
        pdf.set_y(10)
        row(f"{title}  |  {vendor}", 17, "B", "C", 12)
        pdf.set_text_color(0, 0, 0)
        pdf.set_y(40)
        for label, value in meta_rows(record, style):
            row(f"{label}  {value}")
    else:  # compact till-roll style
        row(vendor, 11, "B", "C")
        row(title, 10, "", "C")
        for label, value in meta_rows(record, style):
            row(f"{label} {value}", 8, align="C", h=4.5)

    pdf.ln(4)
    if layout != 2:
        row("Bill to: " + ", ".join(CUSTOMER), 9)
        pdf.ln(3)
    small = 7 if layout == 2 else 10
    columns = [width * f for f in (0.46, 0.12, 0.2, 0.22)]
    table = [("Description", "Qty", "Unit price", "Amount")] + [
        (
            line["description"],
            str(line["quantity"]),
            money(line["unit_price"]),
            money(line["amount"]),
        )
        for line in record["fields"]["line_items"]
    ]
    for index, cells in enumerate(table):
        pdf.set_font(font, "B" if index == 0 else "", small)
        for column, text in enumerate(cells):
            pdf.cell(
                columns[column],
                6,
                text,
                border="B" if layout != 2 else 0,
                align="L" if column == 0 else "R",
            )
        pdf.ln()
    pdf.ln(4)
    for index, (label, value) in enumerate(total_rows(record)):
        pdf.set_font(font, "B" if index == 2 else "", small + (1 if index == 2 else 0))
        pdf.cell(width * 0.76, 6, label, align="R")
        pdf.cell(width * 0.24, 6, value, align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.output(str(path))


def scanify(image, rng):
    """Slight rotation, sensor noise, blur and JPEG artefacts."""
    image = image.rotate(
        rng.uniform(-3.0, 3.0),
        expand=True,
        fillcolor=(196, 192, 186),
        resample=Image.Resampling.BICUBIC,
    )
    noise = Image.frombytes("L", image.size, rng.randbytes(image.width * image.height))
    image = Image.blend(image, noise.convert("RGB"), rng.uniform(0.07, 0.13))
    return image.filter(ImageFilter.GaussianBlur(0.6))


def render_scan(record, style, path, rng):
    image = Image.new("RGB", (900, 1100), (250, 248, 242))
    draw = ImageDraw.Draw(image)

    def text(x, y, value, size=24, anchor="la"):
        draw.text(
            (x, y), value, fill=(25, 25, 30), font=ImageFont.load_default(size=size), anchor=anchor
        )

    centred = style % 2 == 0
    x, anchor = (450, "ma") if centred else (60, "la")
    text(x, 60, record["fields"]["vendor"], 38, anchor)
    text(x, 115, TITLES[record["document_type"]], 28, anchor)
    y = 180
    for label, value in meta_rows(record, style):
        text(60, y, f"{label}: {value}")
        y += 38
    y += 30
    for column, heading in zip(
        (60, 560, 700, 840), ("Description", "Qty", "Price", "Amount"), strict=True
    ):
        text(column, y, heading, 22, "la" if column == 60 else "ra")
    draw.line((60, y + 34, 840, y + 34), fill=(60, 60, 60), width=2)
    y += 52
    for line in record["fields"]["line_items"]:
        text(60, y, line["description"])
        text(560, y, str(line["quantity"]), anchor="ra")
        text(700, y, money(line["unit_price"]), anchor="ra")
        text(840, y, money(line["amount"]), anchor="ra")
        y += 42
    y += 30
    for index, (label, value) in enumerate(total_rows(record)):
        size = 30 if index == 2 else 24
        text(660, y, label, size, "ra")
        text(840, y, value, size, "ra")
        y += 46
    text(60, 1030, "Fictional demo document", 18)
    scanify(image, rng).save(path, "JPEG", quality=62)


def render_junk(rng):
    """Three documents that are not financial."""
    letters = {
        "doc_junk1": (
            "Team offsite agenda",
            [
                "09:30 Arrival and tea",
                "10:00 Planning games",
                "12:30 Walk by the river",
                "15:00 Retrospective",
            ],
        ),
        "doc_junk2": (
            "A letter from the allotment society",
            [
                "Dear neighbours,",
                "the shared shed will be repainted next week.",
                "Please collect your tools by Friday.",
                "Warm regards, the committee",
            ],
        ),
    }
    for doc_id, (title, lines) in letters.items():
        pdf = FPDF()
        pdf.creation_date = datetime(2026, 11, 1, tzinfo=UTC)
        pdf.add_page()
        pdf.set_font("Times", "B", 18)
        pdf.cell(0, 14, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Times", "", 12)
        for line in lines:
            pdf.cell(0, 9, line, new_x="LMARGIN", new_y="NEXT")
        pdf.output(str(DOCUMENTS / f"{doc_id}.pdf"))
    image = Image.new("RGB", (900, 600), (135, 190, 235))
    draw = ImageDraw.Draw(image)
    draw.ellipse((680, 60, 800, 180), fill=(250, 215, 80))
    draw.polygon([(0, 600), (260, 230), (520, 600)], fill=(80, 120, 90))
    draw.polygon([(280, 600), (600, 300), (900, 600)], fill=(60, 100, 75))
    scanify(image, rng).save(DOCUMENTS / "doc_junk3.jpg", "JPEG", quality=70)
    return [
        {
            "id": doc_id,
            "file": f"{doc_id}.{ext}",
            "document_type": "not_financial",
            "category": None,
            "fields": None,
            "faults": ["not_financial"],
            "expected_issues": [],
            "resolvable": None,
            "resolved_values": {},
            "duplicate_of": None,
        }
        for doc_id, ext in (("doc_junk1", "pdf"), ("doc_junk2", "pdf"), ("doc_junk3", "jpg"))
    ]


def write_samples(records):
    """Copy a few documents to the website's one-click samples."""
    wanted = [
        (
            "clean-invoice",
            "A clean invoice",
            lambda r: (
                not r["faults"] and r["file"].endswith("pdf") and r["document_type"] == "invoice"
            ),
        ),
        (
            "scanned-receipt",
            "A scanned receipt",
            lambda r: not r["faults"] and r["file"].endswith("jpg"),
        ),
        ("wrong-total", "Wrong total (one-click fix)", lambda r: "wrong_total" in r["faults"]),
        (
            "misspelled-vendor",
            "Misspelled vendor (auto-fixed)",
            lambda r: "misspelled_vendor" in r["faults"],
        ),
        (
            "missing-number",
            "Missing number (needs you)",
            lambda r: "missing_invoice_number" in r["faults"],
        ),
        ("odd-tax", "Odd tax rate (needs you)", lambda r: "odd_tax_rate" in r["faults"]),
        ("not-financial", "Not a financial document", lambda r: r["id"] == "doc_junk2"),
    ]
    shutil.rmtree(SAMPLES, ignore_errors=True)
    SAMPLES.mkdir(parents=True)
    index = []
    for name, label, matches in wanted:
        record = next(r for r in records if matches(r))
        filename = name + Path(record["file"]).suffix
        shutil.copyfile(DOCUMENTS / record["file"], SAMPLES / filename)
        index.append({"file": filename, "label": label})
    (SAMPLES / "index.json").write_text(json.dumps(index, indent=2) + "\n", newline="\n")


def main():
    rng = random.Random(2026)
    for folder in (DOCUMENTS, TRUTH):
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
    records = build_records(rng)
    # Ten of the financial documents are scans; the rest are PDFs.
    scans = set(rng.sample([r["id"] for r in records], 10))
    for style, record in enumerate(records):
        if record["id"] in scans:
            record["file"] = f"{record['id']}.jpg"
            render_scan(record, style, DOCUMENTS / record["file"], rng)
        else:
            record["file"] = f"{record['id']}.pdf"
            render_pdf(record, style, DOCUMENTS / record["file"])
    records += render_junk(rng)
    for record in records:
        record.pop("tax_rate", None)
        (TRUTH / f"{record['id']}.json").write_text(
            json.dumps(record, indent=2) + "\n", newline="\n"
        )
    write_samples(records)
    faults = [f for r in records for f in r["faults"]]
    print(f"{len(records)} documents, {len(scans) + 1} images")
    print({name: faults.count(name) for name in sorted(set(faults))})


if __name__ == "__main__":
    main()
