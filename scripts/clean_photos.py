"""Prepare phone photos in evals/photos/ before committing them (this rewrites the files).

    python scripts/clean_photos.py

Each photo is turned upright, shrunk to at most 2200 px, saved as <name>.jpg and stripped of all
camera metadata, including GPS position. Keep your originals outside the repository.
"""

from pathlib import Path

from PIL import Image, ImageOps

PHOTOS = Path(__file__).resolve().parent.parent / "evals" / "photos"
PHOTO_SUFFIXES = {".jpg", ".jpeg", ".png"}
MAX_SIDE = 2200  # plenty to read a document, and well under the 5 MB upload limit


def clean(source: Path, target: Path) -> None:
    with Image.open(source) as image:
        upright = ImageOps.exif_transpose(image).convert("RGB")
    upright.thumbnail((MAX_SIDE, MAX_SIDE))
    # A fresh image carries pixels only: no EXIF, comments or colour profile.
    bare = Image.new("RGB", upright.size)
    bare.paste(upright)
    bare.save(target, "JPEG", quality=85)


def main() -> None:
    photos = [p for p in sorted(PHOTOS.iterdir()) if p.suffix.lower() in PHOTO_SUFFIXES]
    for photo in photos:
        target = photo.with_name(f"{photo.stem}.jpg")
        clean(photo, target)
        if photo.name.lower() != target.name.lower():
            photo.unlink()
        print(f"cleaned {target.name}")
    print(f"{len(photos)} photo(s)")


if __name__ == "__main__":
    main()
