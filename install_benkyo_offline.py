#!/usr/bin/env python3
"""Patch an existing benkyo/index.html for Wikimedia image URLs + offline caching.

Run this script in the repository root, next to index.html:
    python3 install_benkyo_offline.py

The script creates sw.js, backs up index.html, and inserts a service-worker
registration snippet. It does not download any image files; images are cached by
the browser after they load online.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
import re
import sys

HTML_FILE = Path("index.html")
SW_FILE = Path("sw.js")
IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE | re.DOTALL)
SRC_ATTR_RE = re.compile(
    r'''(?P<prefix>(?<![\w:-])src\s*=\s*)(?P<quote>["'])(?P<url>.*?)(?P=quote)''',
    re.IGNORECASE | re.DOTALL,
)
REGISTRATION_MARKER = "benkyo-offline-sw-registration"
REGISTRATION = '''\n<!-- benkyo-offline-sw-registration: cache page and successfully loaded images for offline use -->
<script id="benkyo-offline-sw-registration">
if ("serviceWorker" in navigator) {
  window.addEventListener("load", function () {
    navigator.serviceWorker.register("./sw.js", { scope: "./" })
      .catch(function (error) { console.warn("Offline cache could not be enabled:", error); });
  });
}
</script>
'''

SW_CONTENT = r'''/* benkyo offline cache: page shell + images loaded at least once online */
const SHELL_CACHE = "benkyo-shell-v1";
const IMAGE_CACHE = "benkyo-images-v1";

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    // Keep the page available for offline navigation. Do not fail installation
    // if the hosting platform temporarily refuses this initial cache request.
    const cache = await caches.open(SHELL_CACHE);
    try {
      const home = new Request(new URL("./", self.location.href).href, { cache: "reload" });
      await cache.add(home);
    } catch (error) {
      // A successful online visit followed by a reload can populate the cache.
      console.warn("Could not pre-cache the home page:", error);
    }
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keep = new Set([SHELL_CACHE, IMAGE_CACHE]);
    const keys = await caches.keys();
    await Promise.all(keys
      .filter((key) => key.startsWith("benkyo-") && !keep.has(key))
      .map((key) => caches.delete(key)));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  // Cache images from this site and third-party image hosts. Opaque responses
  // from cross-origin <img> requests are intentionally supported by Cache API.
  if (request.destination === "image") {
    event.respondWith((async () => {
      const cache = await caches.open(IMAGE_CACHE);
      const cached = await cache.match(request, { ignoreVary: true });
      if (cached) return cached;

      try {
        const response = await fetch(request);
        if (response && (response.ok || response.type === "opaque")) {
          try { await cache.put(request, response.clone()); }
          catch (error) { console.warn("Could not cache image:", request.url, error); }
        }
        return response;
      } catch (error) {
        const fallback = await cache.match(request, { ignoreVary: true });
        if (fallback) return fallback;
        return new Response("Image is not cached for offline use.", {
          status: 504,
          statusText: "Offline image cache miss",
          headers: { "Content-Type": "text/plain; charset=utf-8" }
        });
      }
    })());
    return;
  }

  // Cache the page shell. When offline, return the saved homepage for a reload.
  const url = new URL(request.url);
  if (url.origin === self.location.origin && request.mode === "navigate") {
    event.respondWith((async () => {
      const cache = await caches.open(SHELL_CACHE);
      try {
        const response = await fetch(request);
        if (response && response.ok) {
          try { await cache.put(request, response.clone()); } catch (_) {}
        }
        return response;
      } catch (error) {
        return (await cache.match(request))
          || (await cache.match(new URL("./", self.location.href).href))
          || new Response("オフラインです。このページをオンラインで一度開いてから再試行してください。", {
            status: 503,
            headers: { "Content-Type": "text/plain; charset=utf-8" }
          });
      }
    })());
  }
});
'''


def to_commons_redirect(image_url: str) -> str | None:
    """Use Commons' documented Special:Redirect/file endpoint for Commons images."""
    parsed = urlsplit(image_url.strip())
    if (parsed.hostname or "").lower() != "upload.wikimedia.org":
        return None

    path = parsed.path
    width = "400"
    if "/thumb/" in path:
        parts = path.split("/thumb/", 1)[1].split("/")
        # thumb URLs are hash dirs / filename / widthpx-filename
        if len(parts) < 4:
            return None
        filename = parts[-2]
        thumb_name = parts[-1]
        match = re.match(r"(\d+)px-", thumb_name)
        if match:
            width = match.group(1)
    else:
        filename = path.rsplit("/", 1)[-1]

    if not filename:
        return None

    # Normalize escaped characters; encode the filename as a query value.
    filename = quote(unquote(filename), safe="()'!$+,;=:@-._~")
    return (
        "https://commons.wikimedia.org/w/index.php?title=Special:Redirect/file/"
        + filename
        + "&amp;width="
        + width
    )


def unique_backup() -> Path:
    base = Path("index.html.before-offline-cache.bak")
    if not base.exists():
        return base
    i = 1
    while True:
        candidate = base.with_name(f"{base.stem}.{i}{base.suffix}")
        if not candidate.exists():
            return candidate
        i += 1


def main() -> int:
    if not HTML_FILE.is_file():
        print("ERROR: index.html が見つかりません。リポジトリのルートで実行してください。", file=sys.stderr)
        return 1

    original = HTML_FILE.read_text(encoding="utf-8")
    changed_count = 0
    unparsed_count = 0

    def rewrite_img(match: re.Match[str]) -> str:
        nonlocal changed_count, unparsed_count
        tag = match.group(0)
        src = SRC_ATTR_RE.search(tag)
        if not src:
            return tag
        old_url = src.group("url")
        new_url = to_commons_redirect(old_url)
        if new_url is None:
            if "upload.wikimedia.org" in old_url:
                unparsed_count += 1
            return tag
        if new_url == old_url:
            return tag
        changed_count += 1
        return tag[:src.start("url")] + new_url + tag[src.end("url"):]

    updated = IMG_TAG_RE.sub(rewrite_img, original)

    if REGISTRATION_MARKER not in updated:
        if re.search(r"</body\s*>", updated, flags=re.IGNORECASE):
            updated = re.sub(
                r"</body\s*>",
                lambda match: REGISTRATION + match.group(0),
                updated,
                count=1,
                flags=re.IGNORECASE,
            )
        else:
            print("ERROR: index.html に </body> が見つかりません。HTMLを変更していません。", file=sys.stderr)
            return 1

    # Update outdated notes so users know that first-load caching needs a connection.
    updated = updated.replace(
        "ブラウザで表示するにはインターネット接続が必要。画像の読み込みが遅い場合も、名前と要点はテキストで学習できる。",
        "初回の画像読み込みにはインターネット接続が必要。読み込んだ肖像画像はブラウザにキャッシュされ、キャッシュが残っていれば次回以降オフラインでも表示できる。",
    )
    updated = updated.replace(
        "Web画像はインターネット接続が必要。本文は印刷可能。",
        "肖像画像はオンラインで読み込んだ後、ブラウザのキャッシュが残っていればオフライン表示できる。本文は印刷可能。",
    )

    backup = unique_backup()
    backup.write_text(original, encoding="utf-8")
    HTML_FILE.write_text(updated, encoding="utf-8")
    SW_FILE.write_text(SW_CONTENT, encoding="utf-8")

    print(f"完了: Wikimedia画像URLを {changed_count} 件修正しました。")
    print("完了: index.html に Service Worker 登録を追加しました。")
    print("完了: sw.js を作成しました。")
    print(f"バックアップ: {backup}")
    print("次に index.html / sw.js を GitHub に push してください。Vercel の再デプロイ後、オンライン状態でサイトを一度開いてから再読み込みしてください。")
    print("遅延読み込みの肖像は、オフラインで必要になるものをオンライン中に一度表示させてください。")
    if unparsed_count:
        print(f"注意: {unparsed_count} 件の Wikimedia URL は自動変換できず、そのまま残しました。")
    if changed_count == 0:
        print("注: 変換対象の upload.wikimedia.org 画像 URL は検出されませんでした。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
