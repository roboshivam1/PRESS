"""Headless Chromium renderer. One browser, reused across renders."""
from __future__ import annotations

from io import BytesIO

from PIL import Image
from playwright.sync_api import sync_playwright

LAUNCH_ARGS = ["--force-color-profile=srgb", "--font-render-hinting=none", "--disable-lcd-text"]


class RenderError(Exception):
    pass


class Renderer:
    def __enter__(self) -> "Renderer":
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch(args=LAUNCH_ARGS)
        except Exception:
            self._pw.stop()
            raise
        self._page = self._browser.new_page(
            viewport={"width": 1080, "height": 1350}, device_scale_factor=1
        )
        return self

    def __exit__(self, *exc) -> None:
        self._browser.close()
        self._pw.stop()

    def render(self, html: str, width: int, height: int) -> Image.Image:
        page = self._page
        page.set_viewport_size({"width": width, "height": height})
        page.set_content(html, wait_until="load")
        missing = page.evaluate("async () => window.pressLayout ? await window.pressLayout() : []")
        if missing:
            raise RenderError(f"font(s) failed to load: {', '.join(missing)}")
        png = page.screenshot(
            type="png",
            clip={"x": 0, "y": 0, "width": width, "height": height},
            animations="disabled",
        )
        return Image.open(BytesIO(png)).convert("RGB")
