"""Upload N receipts at once through the public API and check that none is lost.

python scripts/load_test.py --url <api_url> [--count 20]
"""

import argparse
import sys
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api_client import Client  # noqa: E402
from try_gemini import LINES, sample_png  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--count", type=int, default=20)
    args = parser.parse_args()
    client = Client(args.url)

    with tempfile.TemporaryDirectory() as folder:
        paths = []
        for index in range(args.count):
            lines = [line.replace("TL-0042", f"TL-9{index:03d}") for line in LINES]
            lines[0] = "Tinlark Cafe"
            path = Path(folder) / f"load_{index:02d}.png"
            path.write_bytes(sample_png(lines))
            paths.append(path)
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=3) as pool:
            doc_ids = list(pool.map(client.upload, paths))
        documents = client.wait(doc_ids, timeout=1200)

    statuses = Counter(d["status"] for d in documents.values())
    seconds = time.monotonic() - started
    print(f"{len(documents)}/{args.count} finished in {seconds:.0f} s: {dict(statuses)}")
    csv_text = client.request("GET", "/export.csv")
    print(f"csv rows: {len(csv_text.strip().splitlines()) - 1}")
    first = doc_ids[0]
    audit = client.request("GET", f"/documents/{first}/audit")["audit"]
    print(f"audit entries for one document: {[e['agent'] for e in audit]}")
    other = Client(args.url)
    print(f"another session sees {len(other.documents())} documents")
    return 0 if statuses.get("failed", 0) == 0 and len(documents) == args.count else 1


if __name__ == "__main__":
    sys.exit(main())
