"""Developer tool: run one file through the deployed pipeline and print what happened.

    python scripts/submit.py path/to/document.pdf

Needs AWS_PROFILE=rag-demo (only to read the API address from `terraform output`).
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from api_client import Client  # noqa: E402


def outputs() -> dict:
    raw = subprocess.check_output(
        ["terraform", "output", "-json"], cwd=ROOT / "infra" / "envs" / "demo"
    )
    return {name: item["value"] for name, item in json.loads(raw).items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("file", type=Path)
    args = parser.parse_args()

    client = Client(outputs()["api_url"])
    doc_id = client.upload(args.file)
    client.wait([doc_id])
    detail = client.request("GET", f"/documents/{doc_id}")
    print(json.dumps(detail["document"], indent=2))
    for entry in detail["audit"]:
        print(f"  {entry['timestamp'][11:19]} {entry['agent']}: {entry['decision']}")


if __name__ == "__main__":
    main()
