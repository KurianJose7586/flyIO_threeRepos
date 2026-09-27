"""Records the destination-driven ingestion flow through the real admin UI.

    flyio-scraper-service/.venv/bin/python tests/integration/harness/record_demo.py OUT_DIR

Needs the stack from up.sh on a reset database. Writes OUT_DIR/demo.webm and
four PNG stills; convert with any ffmpeg that has libx264, e.g.
    ffmpeg -i demo.webm -c:v libx264 -crf 22 -pix_fmt yuv420p demo.mp4
The captions and the stub disclaimer are injected into the page, so they are
part of the recording.
"""
import os
import re
import shutil
import sys
import time

from playwright.sync_api import sync_playwright

OUT = sys.argv[1] if len(sys.argv) > 1 else 'demo-out'
os.makedirs(OUT, exist_ok=True)
BASE = "http://127.0.0.1:3100"

CAPTION_JS = """
(text) => {
  let el = document.getElementById('__demo_caption');
  if (!el) {
    el = document.createElement('div');
    el.id = '__demo_caption';
    Object.assign(el.style, {
      position: 'fixed', left: '50%', bottom: '40px', transform: 'translateX(-50%)',
      width: '1060px', padding: '12px 22px', borderRadius: '12px', zIndex: 99999,
      background: 'rgba(17,24,39,0.92)', color: '#fff', font: '600 18px/1.4 system-ui, sans-serif',
      boxShadow: '0 8px 30px rgba(0,0,0,.35)', textAlign: 'center', transition: 'opacity .3s',
    });
    document.body.appendChild(el);
  }
  el.innerHTML = text;
}
"""

BANNER_JS = """
() => {
  if (document.getElementById('__demo_banner')) return;
  const el = document.createElement('div');
  el.id = '__demo_banner';
  Object.assign(el.style, {
    position: 'fixed', bottom: '0', left: '0', right: '0', zIndex: 99998, padding: '6px 12px',
    background: '#fef3c7', color: '#92400e', font: '500 13px system-ui, sans-serif', textAlign: 'center',
  });
  el.textContent = 'Sandbox recording — the web-search API is stubbed and pages are served locally. '
                 + 'The crawl (headless Chromium), parsing, Postgres and this UI are the real code.';
  document.body.appendChild(el);
}
"""


def caption(page, text, hold=2.5):
    page.evaluate(CAPTION_JS, text)
    page.evaluate(BANNER_JS)
    time.sleep(hold)


def focus(page, locator, gap=80):
    """Scroll `locator` to just below the sticky nav, leaving the lower part
    of the screen for the caption."""
    locator.first.evaluate(
        "(el, gap) => window.scrollTo({top: el.getBoundingClientRect().top + window.scrollY - gap, behavior: 'smooth'})",
        gap,
    )
    time.sleep(0.9)


def shot(page, name):
    page.screenshot(path=os.path.join(OUT, name))


with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(
        viewport={"width": 1280, "height": 900},
        record_video_dir=os.path.join(OUT, "raw"),
        record_video_size={"width": 1280, "height": 900},
    )
    page = ctx.new_page()

    page.goto(BASE)
    caption(page, "Building a travel knowledge base <b>from a destination name</b> — no URLs typed by hand", 3.5)

    page.fill('input[placeholder="Enter your username"]', "admin")
    page.fill('input[type="password"]', "integration-test-admin-pw")
    page.click("form button, button[type=submit]")
    page.wait_for_selector("#nav-knowledge-base")
    page.click("#nav-knowledge-base")
    page.wait_for_selector("#kb-destination-input")
    caption(page, "Before: someone had to find and paste every URL. Now: type a destination.", 3)

    page.click("#kb-destination-input")
    page.type("#kb-destination-input", "Jabalpur", delay=140)
    caption(page, "1 · <b>Find sources</b> runs 5 topic searches — guide, things to do, how to reach, best time, where to stay", 3.5)
    page.click("text=Find sources")
    page.wait_for_selector("text=results kept")
    focus(page, page.get_by_text("results kept"))
    caption(page, "2 · 25 raw results → 3 kept. Spam and social links dropped, duplicates merged, ranked by trust.", 4)
    shot(page, "1-candidates.png")
    caption(page, "Trusted sources come <b>pre-selected</b>. The unknown blog is listed for review — <b>never crawled automatically</b>.", 4.5)

    caption(page, "3 · Crawl — real headless browser → split into sections → stored with vector embeddings", 2.5)
    page.click("text=/Crawl \\d+ selected/")
    page.wait_for_function("document.body.innerText.includes('2 saved')", timeout=120_000)
    focus(page, page.get_by_text("2 saved"), gap=110)
    caption(page, "Both pages crawled and stored — each split into sections like <i>Get in</i>, <i>See</i>, <i>Sleep</i>", 4)
    shot(page, "2-crawled.png")

    focus(page, page.get_by_text(re.compile(r"knowledge base \(\d+ url", re.I)), gap=90)
    caption(page, "They're now in the knowledge base the AI trip planner searches", 3.5)
    shot(page, "3-knowledge-base.png")
    page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
    time.sleep(0.9)

    caption(page, "4 · Run the same destination again…", 2)
    page.click("text=Find sources")
    page.wait_for_selector("text=Already indexed")
    focus(page, page.get_by_text("results kept"))
    caption(page, "Already-indexed pages are recognised and skipped — <b>no duplicate crawls, no duplicate embeddings</b>", 4.5)
    shot(page, "4-rerun-dedup.png")

    caption(page, "Destination in → searched, filtered, crawled, embedded. Pages older than 90 days are offered for refresh.", 4.5)

    video_path = page.video.path()
    ctx.close()
    browser.close()
    shutil.move(video_path, os.path.join(OUT, "demo.webm"))
    shutil.rmtree(os.path.join(OUT, "raw"), ignore_errors=True)
    print("recorded", os.path.join(OUT, "demo.webm"))
