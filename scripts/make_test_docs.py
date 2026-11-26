"""Write two throwaway test images (a receipt and a junk note):  make_test_docs.py OUT_DIR"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from try_gemini import sample_png  # noqa: E402

NOTE = ["Picnic planning!", "Bring the blue blanket", "and two frisbees.", "See you Saturday."]


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    (out / "receipt.png").write_bytes(sample_png())
    image = Image.new("RGB", (600, 320), "#fff8d0")
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(NOTE):
        draw.text((40, 40 + index * 56), line, fill="black", font=ImageFont.load_default(size=30))
    image.save(out / "junk.png")
    print(f"wrote receipt.png and junk.png to {out}")


if __name__ == "__main__":
    main()
