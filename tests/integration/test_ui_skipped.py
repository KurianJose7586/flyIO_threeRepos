"""Browser check for review finding #2: a 'skipped' reply from
/api/admin/crawl/auto (no job, no results) must show the backend's reason
and leave no card stuck on 'queued'. The reply is forced with a route
intercept — after the explicit-selection fix the real endpoint no longer
produces it from this screen, but the UI must still handle it.

Run with the scraper venv's Python (it has Playwright):
    flyio-scraper-service/.venv/bin/python tests/integration/test_ui_skipped.py
"""
import json
import sys
import time

from playwright.sync_api import sync_playwright

from _support import ADMIN, check, reset, summary

DETAIL = "Nothing to crawl for 'Jabalpur' — all 3 candidate(s) are already indexed or need manual review."


def main():
    reset()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(ADMIN)
        page.fill('input[placeholder="Enter your username"]', "admin")
        page.fill('input[type="password"]', "integration-test-admin-pw")
        page.click("form button, button[type=submit]")
        page.click("#nav-knowledge-base")
        page.fill("#kb-destination-input", "Jabalpur")
        page.click("text=Find sources")
        page.wait_for_selector("text=results kept")

        page.route("**/api/admin/crawl/auto**", lambda r: r.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"success": True, "destination": "Jabalpur",
                             "job_id": None, "status": "skipped", "detail": DETAIL})))
        page.click("text=/Crawl \\d+ selected/")
        time.sleep(1.5)
        body = page.inner_text("body")
        browser.close()

    print("\n=== UI handles a 'skipped' reply ===")
    check("the backend's reason is shown", DETAIL in body)
    check("no card is left on 'queued'", "queued" not in body.lower())
    return summary()


if __name__ == "__main__":
    sys.exit(main())
