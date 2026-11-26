"""One-off check: send a generated sample receipt image to the provider and print the JSON.

    set AWS_PROFILE=rag-demo, then:  python scripts/try_gemini.py

The API key is read from SSM at runtime and never printed.
"""

import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from app.common import schemas  # noqa: E402
from app.common.providers import FilePart, get_provider  # noqa: E402

LINES = [
    "TINLARK CAFE  (fictional sample)",
    "Receipt no. TL-0042        2026-11-03",
    "",
    "2 x Oat latte        4.50      9.00",
    "1 x Cheese toastie   7.00      7.00",
    "",
    "Subtotal                      16.00",
    "Tax 10%                        1.60",
    "TOTAL USD                     17.60",
]


def sample_png(lines: list[str] = LINES) -> bytes:
    image = Image.new("RGB", (720, 480), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=24)
    for index, line in enumerate(lines):
        draw.text((40, 40 + index * 42), line, fill="black", font=font)
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def main() -> None:
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    os.environ.setdefault("GEMINI_API_KEY_PARAM", "/rag-demo/gemini-api-key")
    os.environ.setdefault("GEMINI_GENERATION_MODEL", "gemini-3.5-flash-lite")
    result = get_provider().generate_json(
        "You extract data from financial documents. Use null for anything not shown.",
        "Extract the fields from this document.",
        schemas.EXTRACTION,
        FilePart(sample_png(), "image/png"),
    )
    print(json.dumps(result.data, indent=2))
    print(f"model={result.model} tokens in/out={result.input_tokens}/{result.output_tokens}")


if __name__ == "__main__":
    main()
