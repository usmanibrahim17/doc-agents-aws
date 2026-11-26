# Burst test

`python scripts/load_test.py --url <api_url> --count 20`, run on 2026-11-26 against the deployed
stack (Gemini free tier, 3 documents processed at a time).

| Uploaded at once | Finished | Valid | Sent to review | Failed | In dead-letter queue | Time for all |
|---|---|---|---|---|---|---|
| 20 | 20 | 20 | 0 | 0 | 0 | 366 s |

Also checked in the same run: the CSV export had 20 rows, and a second session saw 0 documents.
