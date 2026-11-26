"""Zip the app/ package for Lambda:  python scripts/build_zip.py  ->  dist/app.zip

All functions share one zip (they differ only by handler). boto3 is already in the Lambda
runtime, so there is nothing to vendor. Same approach as project 1: Python writes the archive
so entry names use forward slashes, with fixed timestamps so equal input gives equal bytes.
"""

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXED_TIME = (2020, 1, 1, 0, 0, 0)


def main() -> None:
    out = ROOT / "dist" / "app.zip"
    out.parent.mkdir(exist_ok=True)
    paths = sorted(p for p in (ROOT / "app").rglob("*.py") if "__pycache__" not in p.parts)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            info = zipfile.ZipInfo(path.relative_to(ROOT).as_posix(), FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes().replace(b"\r\n", b"\n"))
    print(f"wrote {out} ({len(paths)} files, {out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
