"""URL handling, robots.txt, polite fetching and link discovery."""
import logging
import posixpath
import re
import time
from collections import deque
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

import config

log = logging.getLogger("neu.crawler")
_TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|mc_|ref$)", re.I)


def normalize_url(url):
    """Canonical form used for de-duplication: https, lowercase host, no fragment/tracking params."""
    parts = urlsplit(url.strip())
    scheme = "https" if parts.scheme in ("http", "https") else parts.scheme
    host = (parts.hostname or "").lower()
    port = f":{parts.port}" if parts.port and parts.port not in (80, 443) else ""
    path = re.sub(r"/{2,}", "/", parts.path) or "/"
    query = urlencode(sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING.match(k)
    ))
    return urlunsplit((scheme, host + port, path, query, ""))


def in_scope(url):
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
    except ValueError:
        return False
    if parts.scheme not in ("http", "https"):
        return False
    if not any(host == d or host.endswith("." + d) for d in config.ALLOWED_DOMAINS):
        return False
    if posixpath.splitext(parts.path)[1].lower() in config.SKIP_EXTENSIONS:
        return False
    low = url.lower()
    return not any(part in low for part in config.SKIP_URL_PARTS)


@dataclass
class Page:
    requested: str
    url: str                 # final URL after redirects (normalized)
    kind: str                # "html" | "pdf" | ""
    content: bytes | None
    status: str              # ok | failed | blocked | skipped
    error: str = ""


class Fetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": config.USER_AGENT,
            "Accept": "text/html,application/pdf;q=0.9,*/*;q=0.5",
        })
        self._robots = {}
        self._last_request = 0.0

    def _throttle(self, delay):
        wait = delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def _robot_parser(self, url):
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            rp = RobotFileParser()
            self._throttle(config.REQUEST_DELAY_SECONDS)
            try:
                r = self.session.get(origin + "/robots.txt", timeout=config.REQUEST_TIMEOUT)
                if r.status_code == 200:
                    rp.parse(r.text.splitlines())
                elif r.status_code in (401, 403):
                    rp.disallow_all = True
                else:
                    rp.allow_all = True          # no robots.txt (e.g. 404) means no restrictions
            except requests.RequestException as exc:
                log.warning("Could not read robots.txt for %s (%s); treating as disallowed.", origin, exc)
                rp.disallow_all = True
            self._robots[origin] = rp
        return self._robots[origin]

    def get(self, url):
        rp = self._robot_parser(url)
        if not rp.can_fetch(config.USER_AGENT, url):
            return Page(url, url, "", None, "blocked", "Disallowed by robots.txt")
        delay = max(config.REQUEST_DELAY_SECONDS, float(rp.crawl_delay(config.USER_AGENT) or 0))
        last_error = "unknown error"
        for attempt in range(1, config.MAX_RETRIES + 1):
            self._throttle(delay)
            try:
                with self.session.get(url, timeout=config.REQUEST_TIMEOUT, stream=True) as r:
                    final = normalize_url(r.url)
                    if r.status_code in (429, 500, 502, 503, 504):
                        last_error = f"HTTP {r.status_code}"
                        time.sleep(2 ** attempt)
                        continue
                    if r.status_code != 200:
                        return Page(url, final, "", None, "failed", f"HTTP {r.status_code}")
                    if not in_scope(final):
                        return Page(url, final, "", None, "skipped", f"Redirected outside crawl scope: {final}")
                    ctype = r.headers.get("Content-Type", "").lower()
                    if "pdf" in ctype or final.lower().endswith(".pdf"):
                        kind, limit = "pdf", config.MAX_PDF_BYTES
                    elif "html" in ctype:
                        kind, limit = "html", config.MAX_HTML_BYTES
                    else:
                        return Page(url, final, "", None, "skipped", f"Unsupported content type: {ctype or 'unknown'}")
                    declared = r.headers.get("Content-Length", "")
                    if declared.isdigit() and int(declared) > limit:
                        return Page(url, final, "", None, "skipped", "File too large")
                    data = bytearray()
                    for block in r.iter_content(65536):
                        data.extend(block)
                        if len(data) > limit:
                            return Page(url, final, "", None, "skipped", "File too large")
                    return Page(url, final, kind, bytes(data), "ok")
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                time.sleep(2 ** attempt)
        return Page(url, url, "", None, "failed", last_error)


class Crawler:
    """Breadth-first crawl. Yields one Page per fetched URL; discovers links from HTML pages."""

    def __init__(self, fetcher, start_urls):
        self.fetcher = fetcher
        self.queue = deque()
        self.seen = set()          # every URL ever queued
        self.yielded = set()       # final URLs already handed to the caller
        self.redirect_duplicates = 0
        for url in start_urls:
            self.enqueue(url)

    def enqueue(self, url):
        try:
            url = normalize_url(url)
        except ValueError:
            return False
        if url in self.seen or not in_scope(url):
            return False
        self.seen.add(url)
        self.queue.append(url)
        return True

    def crawl(self, limit):
        fetched = 0
        while self.queue and fetched < limit:
            url = self.queue.popleft()
            fetched += 1
            page = self.fetcher.get(url)
            log.info("[%d/%d] %s %s", fetched, limit, page.status, url)
            if page.status == "ok":
                if page.url in self.yielded:     # a redirect landed on a page we already have
                    self.redirect_duplicates += 1
                    continue
                self.yielded.add(page.url)
                self.seen.add(page.url)
                if page.kind == "html":
                    self._discover(page)
            yield page

    def _discover(self, page):
        soup = BeautifulSoup(page.content, "lxml")
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            self.enqueue(urljoin(page.url, href))