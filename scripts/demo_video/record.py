"""Record a narrated walkthrough: Playwright video with a visible cursor + SAPI narration.

Each narration clip starts when its step starts and the next step waits for the clip to end, so
audio and actions stay in sync even though model calls take a variable time.
"""
import json
import re
import shutil
import time
import wave
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
CHROME = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
BASE = "http://localhost:8501"
W, H = 1280, 720
NARR = json.loads((HERE / "narration.json").read_text(encoding="utf-8"))


def wav_seconds(path: Path) -> float:
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


DUR = [wav_seconds(HERE / f"n{i:02d}.wav") for i in range(len(NARR))]

CURSOR_JS = """
(() => {
  const mk = () => {
    if (document.getElementById('__cur')) return;
    const c = document.createElement('div'); c.id = '__cur';
    c.style.cssText = 'position:fixed;z-index:2147483647;pointer-events:none;left:-50px;top:-50px;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;background:rgba(230,50,50,.85);border:2px solid #fff;box-shadow:0 0 0 2px rgba(0,0,0,.35);transition:transform .08s';
    document.documentElement.appendChild(c);
    addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
    addEventListener('mousedown', e => {
      c.style.transform = 'scale(.7)';
      const r = document.createElement('div');
      r.style.cssText = `position:fixed;z-index:2147483646;pointer-events:none;left:${e.clientX}px;top:${e.clientY}px;width:10px;height:10px;margin:-5px 0 0 -5px;border-radius:50%;border:3px solid rgba(230,50,50,.8);transition:all .45s ease-out;opacity:1`;
      document.documentElement.appendChild(r);
      requestAnimationFrame(() => { r.style.width = '60px'; r.style.height = '60px'; r.style.margin = '-30px 0 0 -30px'; r.style.opacity = '0'; });
      setTimeout(() => r.remove(), 600);
    }, true);
    addEventListener('mouseup', () => { c.style.transform = 'scale(1)'; }, true);
  };
  if (document.documentElement) mk(); else addEventListener('DOMContentLoaded', mk);
  new MutationObserver(mk).observe(document, {childList: true, subtree: true});
})();
"""

cues: list[tuple[int, float]] = []  # (narration index, start offset seconds)
T0 = 0.0
pos = [W / 2, H / 2]


def now():
    return time.monotonic() - T0


class Step:
    def __init__(self, i):
        self.i = i
        self.start = now()
        cues.append((i, self.start))

    def done(self, pad=0.6):
        left = self.start + DUR[self.i] + pad - now()
        if left > 0:
            time.sleep(left)


def move(page, x, y, steps=28):
    page.mouse.move(x, y, steps=steps)
    pos[0], pos[1] = x, y


def center(loc):
    loc.scroll_into_view_if_needed()
    b = loc.bounding_box()
    return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2


def click(page, loc, steps=28, pause=0.35):
    x, y = center(loc)
    move(page, x, y, steps)
    time.sleep(pause)
    page.mouse.click(x, y)


def hover(page, loc, steps=24):
    x, y = center(loc)
    move(page, x, y, steps)


def type_question(page, text):
    box = page.get_by_test_id("stChatInputTextArea")
    click(page, box)
    page.keyboard.type(text, delay=38)
    time.sleep(0.5)
    page.keyboard.press("Enter")


def smooth_scroll(page, dy, parts=12):
    for _ in range(parts):
        page.mouse.wheel(0, dy / parts)
        time.sleep(0.05)


def main():
    global T0
    out = HERE / "raw"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir()
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME, headless=True)
        ctx = b.new_context(viewport={"width": W, "height": H}, record_video_dir=str(out),
                            record_video_size={"width": W, "height": H})
        ctx.add_init_script(CURSOR_JS)
        T0 = time.monotonic()
        global PAGE
        page = PAGE = ctx.new_page()
        page.goto(BASE)
        page.wait_for_selector("text=Items flagged for review", timeout=30000)
        page.wait_for_timeout(800)
        move(page, W / 2, 300, 5)

        # 1. Home snapshot
        s = Step(0)
        time.sleep(2.0)
        hover(page, page.get_by_text("Properties", exact=True).first)
        time.sleep(1.5)
        hover(page, page.get_by_text("Revenue vs budget").first)
        time.sleep(1.2)
        hover(page, page.get_by_text("NOI vs budget").first)
        s.done()

        # 2. Sample question
        s = Step(1)
        btn = page.get_by_role("button", name="Which 5 cities have the most properties?")
        click(page, btn)
        s.done(0.2)
        s = Step(2)
        page.wait_for_selector("text=Working on it", timeout=20000)
        move(page, 760, 420, 20)
        page.wait_for_selector("text=Sources (", timeout=150000)
        s.done(0.3)
        s = Step(3)
        page.wait_for_timeout(500)
        hover(page, page.get_by_text("Answered. Every number traced").first)
        s.done(0.4)
        s = Step(4)
        click(page, page.get_by_text("Sources (").first)
        page.wait_for_timeout(800)
        hover(page, page.get_by_text("Database query Q1").first)
        time.sleep(1.2)
        smooth_scroll(page, 200)
        s.done()

        # 3. Hybrid question
        s = Step(5)
        type_question(page, "What base rent per square foot does the lease abstract state for "
                            "Christian-Rivas's lease at Santos Office Chicago (Suite 3), and does it "
                            "match the database?")
        s.done(0.2)
        s = Step(6)
        page.wait_for_selector("text=Working on it", timeout=20000)
        move(page, 800, 300, 20)
        page.wait_for_function("document.querySelectorAll('[data-testid=stExpander]').length >= 2",
                               timeout=150000)
        page.wait_for_timeout(1500)
        s.done(0.2)
        s = Step(7)
        page.mouse.wheel(0, -2000)
        time.sleep(0.4)
        last_answer = page.get_by_test_id("stChatMessage").last
        last_answer.scroll_into_view_if_needed()
        hover(page, last_answer.get_by_text("Answered").first)
        s.done()
        s = Step(8)
        exp = last_answer.get_by_text("Sources (").first
        exp.scroll_into_view_if_needed()
        click(page, exp)
        page.wait_for_timeout(800)
        smooth_scroll(page, 520)
        doc = page.get_by_text("passage that was cited").last
        hover(page, doc)
        s.done()
        s = Step(9)
        smooth_scroll(page, 900)
        click(page, page.get_by_role("button", name=re.compile(r"^\W*Helpful$")).last)
        page.wait_for_timeout(1200)
        s.done()

        # 4. Refusal
        s = Step(10)
        type_question(page, "What will NOI be for the whole portfolio next year?")
        page.wait_for_selector("text=Cannot be determined", timeout=150000)
        page.wait_for_timeout(1200)
        hover(page, page.get_by_text("Cannot be determined").last)
        s.done()

        # 5. View toggle
        s = Step(11)
        click(page, page.get_by_test_id("stSidebar").get_by_text("Analyst", exact=True))
        page.wait_for_timeout(1500)
        page.mouse.wheel(0, -4000)
        time.sleep(0.8)
        hover(page, page.get_by_text("model call").first)
        s.done()

        # 6. Variance report
        s = Step(12)
        click(page, page.get_by_test_id("stSidebar").get_by_text("Variance report", exact=True))
        page.wait_for_selector("text=Generate report", timeout=30000)
        click(page, page.get_by_role("button", name="Generate report"))
        page.wait_for_selector("text=Flagged for review", timeout=180000)
        page.wait_for_timeout(1200)
        move(page, 700, 520, 18)
        s.done(0.2)
        s = Step(13)
        page.wait_for_selector("text=Drafted by the model", timeout=180000)
        page.mouse.wheel(0, 700)
        time.sleep(1.0)
        hover(page, page.get_by_text("Drafted by the model").first)
        s.done()
        s = Step(14)
        page.mouse.wheel(0, -2000)
        time.sleep(0.8)
        grid = page.get_by_test_id("stDataFrame").first
        gb = grid.bounding_box()
        move(page, gb["x"] + 14, gb["y"] + 60, 25)
        time.sleep(0.4)
        page.mouse.click(gb["x"] + 14, gb["y"] + 60)
        page.wait_for_selector("text=Open the full report", timeout=60000)
        page.wait_for_timeout(1000)
        smooth_scroll(page, 330)
        time.sleep(1.5)
        click(page, page.get_by_role("button", name="Open the full report for this property"))
        page.wait_for_timeout(2000)
        s.done()

        # 7. Close
        s = Step(15)
        click(page, page.get_by_test_id("stSidebar").get_by_text("Home", exact=True))
        page.wait_for_selector("text=Items flagged for review", timeout=30000)
        move(page, W / 2, 380, 20)
        s.done(1.5)
        total = now()
        ctx.close()
        b.close()
    vid = next(out.glob("*.webm"))
    (HERE / "cues.json").write_text(json.dumps({"cues": cues, "total": total}), encoding="utf-8")
    print("video", vid, "total", round(total, 1), "s; cues", len(cues))


PAGE = None
if __name__ == "__main__":
    try:
        main()
    except Exception:
        if PAGE:
            PAGE.screenshot(path=str(HERE / "fail.png"))
        raise
