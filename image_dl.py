import re
import os
import sys
import queue
import datetime
import json

from pprint import pprint
from typing import Callable, Dict, Any, Tuple

from playwright.sync_api import sync_playwright, Browser


class SiteConfig:
    url: str
    handler: Callable
    patterns: Dict[str, Any]

    initial_pagenum: int
    window_size: Tuple[int, int]
    extra_styles: str
    timing: Dict[str, int]
    cookies: Dict[str, str]
    tips: str

    def __init__(self, raw: Dict[str, Any]) -> "SiteConfig":
        assert ("url" in raw)
        assert ("handler" in raw)
        assert ("patterns" in raw)

        self.url = raw["url"]
        self.handler = raw["handler"]
        self.patterns = raw["patterns"]

        self.initial_pagenum = raw.get("initial-pagenum", 1)
        self.window_size = raw.get("window-size", (2000, 3500))
        self.extra_styles = "".join(raw.get("extra-styles", []))
        self.timing = raw.get(
            "timing", {"ep-load-time-ms": 5000, "page-load-time-ms": 3000}
        )
        self.cookies = raw.get("cookies", None)

        self.tips = "\n".join(raw.get("tips", []))

    def say_hello(self):
        print("="*30)
        print(f"ℹ️ Site Configs:")
        print(f"ℹ️ \turl = '{self.url}'")
        print(f"ℹ️ \thandler = '{self.handler.__name__}'")
        print(f"ℹ️ \tpatterns = \n")
        pprint(self.patterns)
        print(f"ℹ️ \tinitial_pagenum = {self.initial_pagenum}")
        print(f"ℹ️ \twindow_size = '{self.window_size}'")
        print(f"ℹ️ \textra_styles = '{self.extra_styles}'")
        print(f"ℹ️ \tcookies = '{self.cookies}'")
        print(f"ℹ️ \ttips: '{self.tips}'")
        print("="*30 + "\n\n")

    def build_cookies(self, cookies_file_path: str, add_cookies: Callable) -> None:
        if self.cookies is not None:
            cookies = []
            with open(cookies_file_path, "r") as cookies_file:
                raw_cookies = json.load(cookies_file)

                for raw_cookie in raw_cookies:
                    for key, val in raw_cookie.items():
                        cookies.append({
                            "name": key,
                            "value": val,
                            "domain": self.cookies["domain"],
                            "path": "/",
                        })
            # pprint(cookies)
            add_cookies(cookies)

    @staticmethod
    def find_match(target_url, configs: list["SiteConfig"]) -> "SiteConfig":
        for config in configs:
            if target_url.startswith(config.url):
                config.say_hello()
                return config
        print("💥 Not supported...")
        raise ValueError


class DL:

    SCREENSHOT_LISTENER = f"""
        document.addEventListener('keydown', async (e) => {{
            if (e.key === 'd' || e.key === 'D') {{
                try {{
                    await window.py_screenshot();
                }} catch (err) {{
                    console.error(err);
                }}
            }}
        }});
    """

    TASK_QUEUE = queue.Queue()
    PAGE = 0
    CFG = SiteConfig

    @staticmethod
    def namefile(output_dir: str, page_index: int) -> str:
        return f"{output_dir}/page_{page_index:03d}.png"

    @staticmethod
    def hint_page_number(page):
        now_page = "?"
        now_page_pat = DL.CFG.patterns["page-number"]["now"]
        all_page = "?"
        all_page_pat = DL.CFG.patterns["page-number"]["all"]

        if now_page_pat:
            now_page = page.locator(now_page_pat).first.inner_text()

        if all_page_pat:
            all_page = page.locator(all_page_pat).first.inner_text()

        print(f"ℹ️ Page Number = {now_page} / {all_page}")

    @staticmethod
    def select_image_by_rule(page, output_dir):
        display_index = DL.PAGE
        print(f"\nProcessing page {display_index}...")
        DL.hint_page_number(page)

        try:
            # 1. Find the first matching container
            container = page.locator(DL.CFG.patterns["rule"]).first
            if container.count() == 0:
                print(f"⚠️ Cannot find container for page {display_index}")
                return

            # 2. Find the target image inside that container
            image = container.locator(DL.CFG.patterns["image"]).first
            if image.count() == 0:
                print(f"⚠️ Cannot find image for page {display_index}")
                return

            # 3. Screenshot
            filename = DL.namefile(output_dir, display_index)
            image.screenshot(path=filename)
            print(f"✅ Page {display_index} done ({filename})\n\n")

            DL.PAGE += 1
        except Exception as e:
            print(f"💥 {str(e)}")
            try:
                page.evaluate(f"alert('{str(e)}')")
            except:
                pass

    @staticmethod
    def select_image_from_area(page, output_dir):
        # 1-based page index
        display_index = DL.PAGE
        print(f"\nProcessing page {display_index}...")
        DL.hint_page_number(page)

        try:
            # 1. Try to find the target page container (usually all preloaded)
            target_area = page.locator(
                DL.CFG.patterns["area"]).nth(display_index - 1)  # 0-based
            if target_area.count() == 0:
                print(
                    f"⚠️ Cannot {display_index}-th area (probably last page)")
                return

            # 2. Try to find 1st image under the area
            loc = target_area.locator(
                DL.CFG.patterns["image"]).first
            if loc.count() == 0:
                print(
                    f"⚠️ Cannot find {display_index}-th image (unloaded or AD page)"
                    f"\n Rule = {DL.CFG.patterns['image']}")
                return

            # 3. do screenshot
            filename = DL.namefile(output_dir, display_index)
            loc.screenshot(path=filename)

            print(f"✅ Page {display_index} done ({filename})\n\n")
            DL.PAGE += 1

        except Exception as e:
            print(f"💥 {str(e)}")
            try:
                page.evaluate(f"alert('{str(e)}')")
            except:
                pass

    @staticmethod
    def do_task(page, start_time):
        try:
            {
                "screenshot": DL.CFG.handler
            }[DL.TASK_QUEUE.get_nowait()](page, start_time)
        except queue.Empty:
            pass

    @staticmethod
    def task_screenshot():
        print("✅ Request 'screenshot' received")
        DL.TASK_QUEUE.put("screenshot")
        return "✅ Request received"

    @staticmethod
    def build_dir(page) -> str:
        name_patterns = DL.CFG.patterns["name"]

        fullname = ""
        for pat in ["author", "title", "episode"]:
            if name_patterns[pat] is None:
                continue
            loc = page.locator(name_patterns[pat]).first
            loc.wait_for(timeout=DL.CFG.timing["ep-load-time-ms"])

            print(f"ℹ️ {name_patterns}[{pat}] => {loc.inner_text()}")
            fullname += loc.inner_text() + (" - " if pat == "author" else " ")

        return re.sub(r'[<>:"/\\|?*]', '_', fullname).strip()


def run(browser: Browser, dirname: str, ep_url: str, cookies_file_path: str):
    context = browser.new_context(no_viewport=True)

    DL.CFG.build_cookies(cookies_file_path, context.add_cookies)

    page = context.new_page()
    page.expose_function("py_screenshot", DL.task_screenshot)

    try:
        print(f"ℹ️ GOTO: {ep_url}")
        page.goto(ep_url)
    except Exception as e:
        print(f"💥 Load URL failed... {e}")
        return

    try:
        safe_title = DL.build_dir(page)
        if safe_title:
            dirname = safe_title
            print(f"✅ Create output dir from title: '{dirname}'")
        else:
            print("⚠️ Create output dir from default name")
    except Exception as e:
        print(f"⚠️ Create output dir error: {e}")

    # --- Inject JS to website ---
    page.evaluate(f"""
        () => {{
            {DL.SCREENSHOT_LISTENER}

            const style = document.createElement("style");
            style.textContent = `
                {DL.CFG.extra_styles}
            `;
            document.head.appendChild(style);
        }}
    """)

    try:
        if not os.path.exists(dirname):
            os.makedirs(dirname)

        print("\n" + "="*30)
        print("✅ Page is now ready!")

        DL.PAGE = DL.CFG.initial_pagenum
        print(f"ℹ️ Starting from page {DL.CFG.initial_pagenum}")
        print(f"⚠️ Tips: \n{DL.CFG.tips}")

        print("ℹ️ Press 'd' key after current page being loaded")
        print("="*30 + "\n")

        while not page.is_closed():
            DL.do_task(page, dirname)
            page.wait_for_timeout(100)

    except Exception as e:
        print(f"⚠️ Stop reason: {e}")


CONFIGS: list[SiteConfig] = [
]

if __name__ == "__main__":
    argc = len(sys.argv)
    if argc > 1:
        ep_url = sys.argv[1]
        cookies_file_path = sys.argv[2] if argc > 2 else "cookies.json"

        DL.CFG = SiteConfig.find_match(ep_url, CONFIGS)

        with sync_playwright() as p:
            launch_options = {
                "headless": False,
                "executable_path":  "/usr/bin/chromium",
                "args": [f"--window-size={DL.CFG.window_size[0]},{DL.CFG.window_size[1]}"],
            }

            try:
                run(
                    p.chromium.launch(**launch_options),
                    datetime.datetime.now().strftime("%Y%m%d-%H%M%S"),
                    ep_url,
                    cookies_file_path
                )
            except Exception as e:
                print(f"💥 Launch failed ...: {e}")
    else:
        print("💥 No URL given...")
