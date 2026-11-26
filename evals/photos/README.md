# Real-photo eval set

Print 10 of the generated documents, photograph them, and run the same evaluation on the photos.
They are scored against the same ground truth as the generated set and reported as their own row
in [`../RESULTS.md`](../RESULTS.md).

## Print

From [`../data/documents/`](../data/documents/), print at 100% size, black and white is fine.
`doc21.pdf` and `doc27.pdf` are narrow till-roll style pages.

## Photograph

One photo per document. Name it after the document: `doc02.jpg`.

| # | Print this | Why it is in the set | How to photograph it |
|---|---|---|---|
| 1 | `doc02.pdf` | Clean invoice (baseline) | Flat on a table, straight from above, daylight, no shadow |
| 2 | `doc07.pdf` | Clean receipt | Straight from above, warm indoor lamp light in the evening |
| 3 | `doc05.pdf` | Credit note (negative amounts) | Tilted: camera about 30 degrees from vertical, from the bottom edge |
| 4 | `doc13.pdf` | Clean invoice | **Crumple it into a loose ball, flatten it**, then shoot from above |
| 5 | `doc26.pdf` | Clean receipt | Rotated about 20 degrees on a dark or patterned surface |
| 6 | `doc16.pdf` | Wrong total | Side light from one lamp, with your phone's or hand's shadow across part of it |
| 7 | `doc01.pdf` | Misspelled vendor | Strong angle: about 45 degrees from the left side |
| 8 | `doc21.pdf` | Missing receipt number | Fold it twice, open it, hold it in your hand while shooting |
| 9 | `doc27.pdf` | Odd tax rate | Dim light, no flash |
| 10 | `doc_junk2.pdf` | Not a financial document | Casual snapshot with some of the table around it |

Rules:

- The whole page must be in the frame and in focus enough for you to read it.
- Set the phone camera to **JPEG** (iPhone: Settings, Camera, Formats, "Most Compatible"). HEIC is
  not accepted.
- This repository is public. Keep faces, other papers, screens and anything personal out of frame.

## Run

```
python scripts/clean_photos.py     # before committing: removes GPS and camera metadata
python evals/run_evals.py --url <api_url> --set photos
```

`clean_photos.py` rewrites the files here (upright, at most 2200 px, no metadata), so keep your
originals elsewhere. A test fails if a photo with metadata is committed. With fewer than 10
photos the run uses the ones present and reports the count.
