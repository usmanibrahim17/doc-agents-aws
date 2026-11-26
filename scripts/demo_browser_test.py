"""Headless-browser test of the live demo site, plus the README screenshots.

    pip install playwright && playwright install chromium     # not in requirements-dev (heavy)
    python scripts/demo_browser_test.py --url https://<cloudfront-domain> [--out docs/img]

Uses the page like a visitor: clicks samples, waits for the agents, approves a review, opens an
audit trail and downloads the CSV. Fails on console errors, CSP violations or failed requests.
It processes a handful of real documents.
"""

import argparse
import sys
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

SAMPLES = ["clean-invoice.pdf", "wrong-total.jpg", "missing-number.pdf", "not-financial.pdf"]
SLOW = 240_000  # milliseconds: free-tier rate limits can make the agents wait


def check(condition: bool, message: str, failures: list[str]) -> None:
    print(("  ok   " if condition else "  FAIL ") + message)
    if not condition:
        failures.append(message)


def row(page: Page, filename: str):
    return page.locator("#results tr", has_text=filename)


def wait_status(page: Page, filename: str, status: str) -> None:
    expect(row(page, filename).locator(".status")).to_have_text(status, timeout=SLOW)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", required=True, help="CloudFront URL of the demo site")
    parser.add_argument("--out", type=Path, default=Path("docs/img"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    failures: list[str] = []
    problems: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        page.on(
            "console",
            lambda m: problems.append(f"console: {m.text}") if m.type == "error" else None,
        )
        page.on("pageerror", lambda e: problems.append(f"page error: {e}"))
        page.on("requestfailed", lambda r: problems.append(f"request failed: {r.url.split('?')[0]}"))

        print("page")
        response = page.goto(args.url)
        check(response.status == 200, "page loads with HTTP 200", failures)
        headers = response.headers
        check("content-security-policy" in headers, "CSP header is set", failures)
        check("strict-transport-security" in headers, "HSTS header is set", failures)
        check(
            "real invoices" in page.locator(".banner").inner_text(),
            "demo-only banner is shown",
            failures,
        )
        expect(page.locator("#samples button")).to_have_count(7)

        print("samples")
        for name in SAMPLES:
            page.locator(f'button[data-sample="{name}"]').click()
            expect(row(page, name)).to_have_count(1, timeout=30_000)
        wait_status(page, "clean-invoice.pdf", "valid")
        wait_status(page, "wrong-total.jpg", "valid")
        wait_status(page, "missing-number.pdf", "needs review")
        wait_status(page, "not-financial.pdf", "rejected")
        check(True, "four samples reached the expected statuses", failures)
        check(
            "resolver" in row(page, "wrong-total.jpg").inner_text(),
            "the Resolver ran on the wrong total",
            failures,
        )
        page.screenshot(path=str(args.out / "demo-results.png"), full_page=True)

        print("review")
        card = page.locator(".card", has_text="missing-number.pdf")
        check("document number is missing" in card.inner_text(), "explanation is shown", failures)
        card.scroll_into_view_if_needed()
        card.screenshot(path=str(args.out / "demo-review.png"))
        card.locator('input[name="invoice_number"]').fill("INV-HUMAN-1")
        card.get_by_role("button", name="Approve").click()
        wait_status(page, "missing-number.pdf", "approved")
        check(True, "approval resumed the workflow", failures)

        print("audit trail")
        row(page, "wrong-total.jpg").click()
        expect(page.locator("#audit li").first).to_be_visible(timeout=30_000)
        audit = page.locator("#audit").inner_text()
        for agent in ("classifier", "extractor", "validator", "resolver", "finalizer"):
            check(agent in audit, f"audit shows the {agent}", failures)
        page.locator("#detail").screenshot(path=str(args.out / "demo-audit.png"))

        print("export")
        with page.expect_download() as download:
            page.locator("#export").click()
        csv = Path(download.value.path()).read_text(encoding="utf-8")
        check(len(csv.strip().splitlines()) == 4, "CSV has the three saved documents", failures)
        check("INV-HUMAN-1" in csv, "CSV contains the human correction", failures)

        print("isolation and mobile")
        other = browser.new_context().new_page()
        other.goto(args.url)
        expect(other.locator("#empty")).to_be_visible()
        other.wait_for_timeout(4000)
        check(other.locator("#results tr").count() == 0, "a second visitor sees nothing", failures)
        page.set_viewport_size({"width": 390, "height": 800})
        overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth")
        check(not overflow, "no page-wide horizontal scrolling at 390px", failures)
        browser.close()

    print("browser problems")
    check(not problems, "no console errors, CSP violations or failed requests", failures)
    for problem in problems:
        print("   ", problem)
    print(f"\n{'FAILED' if failures else 'PASSED'}: {len(failures)} failing check(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
