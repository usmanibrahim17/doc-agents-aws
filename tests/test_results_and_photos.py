from pathlib import Path

from PIL import Image

from evals import results_file
from scripts.clean_photos import PHOTO_SUFFIXES, clean

ROOT = Path(__file__).resolve().parent.parent


def test_history_rows_are_appended_and_only_one_section_changes():
    text = (ROOT / "evals" / "RESULTS.md").read_text(encoding="utf-8")
    first = results_file.update(text, "| new-1 |", "photos", "photo body 1")
    second = results_file.update(first, "| new-2 |", "photos", "photo body 2")
    assert second.index("| new-1 |") < second.index("| new-2 |") < second.index("runs:end")
    assert "photo body 2" in second and "photo body 1" not in second
    documents = text.split("documents:start")[1].split("documents:end")[0]
    assert documents in second


def test_clean_removes_metadata_turns_upright_and_shrinks(tmp_path):
    image = Image.new("RGB", (4000, 3000), "white")
    exif = Image.Exif()
    exif[0x0112] = 6  # orientation: rotate 90 degrees
    exif[0x010F] = "SomePhone"
    source = tmp_path / "doc02.jpg"
    image.save(source, exif=exif)
    clean(source, tmp_path / "out.jpg")
    with Image.open(tmp_path / "out.jpg") as result:
        assert result.size == (1650, 2200)
        assert dict(result.getexif()) == {}


def test_committed_photos_carry_no_metadata():
    """Phone photos hold GPS and device details: run scripts/clean_photos.py before committing."""
    for path in (ROOT / "evals" / "photos").iterdir():
        if path.suffix.lower() in PHOTO_SUFFIXES:
            with Image.open(path) as image:
                assert dict(image.getexif()) == {}, path.name
