from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger(__name__)
UA = {"User-Agent": "climbing-conditions-advisor (+https://github.com; open-source, low volume)"}


def get(url: str, params: dict | None = None, timeout: int = 60, retries: int = 3, wait: int = 10,
        err_cls=RuntimeError) -> requests.Response:
    last = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=timeout)
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}: {r.text[:200]}"
            if 400 <= r.status_code < 500 and r.status_code != 429:
                break  # client error: retrying will not help
        except requests.RequestException as e:
            last = repr(e)
        log.warning("GET %s failed (attempt %d/%d): %s", url, attempt, retries, last)
        if attempt < retries:
            time.sleep(wait * attempt)
    raise err_cls(f"GET {url} failed: {last}")
