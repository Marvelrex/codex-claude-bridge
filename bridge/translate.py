"""zh2en: translate Chinese text to English (or any DeepL target) via the DeepL API.

Standalone tool for agents. Reads text from an argument, a file or stdin, prints the
translation to stdout, and uses exit codes agents can branch on. Standard library only.

    zh2en "中文文本"
    echo 中文 | zh2en
    zh2en -f notes.md --to EN-GB

Key: environment variable DEEPL_AUTH_KEY (or --key). Keys ending in ":fx" use the Free endpoint.
API reference: https://developers.deepl.com/docs/api-reference/translate
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Callable, Optional

FREE_URL = "https://api-free.deepl.com/v2/translate"
PRO_URL = "https://api.deepl.com/v2/translate"
ENV_KEY = "DEEPL_AUTH_KEY"

EXIT_OK, EXIT_USAGE, EXIT_NO_KEY, EXIT_AUTH_OR_QUOTA, EXIT_NETWORK, EXIT_HTTP = 0, 1, 2, 3, 4, 5

RETRYABLE = {429, 500, 529}
NO_RETRY_FATAL = {403, 456}

# Han ideographs only; CJK punctuation on its own does not count as Chinese text.
_HAN = re.compile(r"[一-鿿㐀-䶿豈-﫿]")


class DeepLError(Exception):
    """status 0 means a transport-level failure (no HTTP response)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def endpoint_for(key: str) -> str:
    return FREE_URL if key.endswith(":fx") else PRO_URL


def contains_chinese(text: str) -> bool:
    return bool(_HAN.search(text))


def http_post(url: str, headers: dict, body: dict, timeout: float):
    """Real transport. Returns (status, parsed_json_or_text). Raises OSError on transport failure."""
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, _decode(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, _decode(e.read())


def _decode(raw: bytes):
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _message(payload) -> str:
    if isinstance(payload, dict):
        return str(payload.get("message") or payload)
    return str(payload).strip()[:500]


def translate(text: str, key: str, *, source: Optional[str] = "ZH", target: str = "EN-US",
              formality: Optional[str] = None, context: Optional[str] = None,
              timeout: float = 30.0, retries: int = 2,
              post: Callable = http_post, sleep: Callable = time.sleep) -> str:
    """Translate `text` and return the translated string. Raises DeepLError on failure."""
    body: dict = {"text": [text], "target_lang": target, "preserve_formatting": True}
    if source and source.lower() != "auto":
        body["source_lang"] = source
    if formality:
        body["formality"] = formality
    if context:
        body["context"] = context
    headers = {"Authorization": f"DeepL-Auth-Key {key}", "Content-Type": "application/json"}
    url = endpoint_for(key)

    attempt = 0
    while True:
        try:
            status, payload = post(url, headers, body, timeout)
        except OSError as e:
            raise DeepLError(0, f"network error: {e}") from e
        if status == 200 and isinstance(payload, dict):
            return "\n".join(t.get("text", "") for t in payload.get("translations", []))
        if status in RETRYABLE and attempt < retries:
            attempt += 1
            sleep(min(2 ** attempt, 8))
            continue
        raise DeepLError(status, _message(payload))


# ---- CLI ---------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="zh2en",
        description="Translate Chinese text to English via DeepL. Reads an argument, a file (-f) or stdin.",
    )
    p.add_argument("text", nargs="?", help="text to translate (omit to read stdin)")
    p.add_argument("-f", "--file", help="read text from this file")
    p.add_argument("--from", dest="source", default="ZH",
                   help="source language code, or 'auto' for detection (default: ZH)")
    p.add_argument("--to", dest="target", default="EN-US", help="target language code (default: EN-US)")
    p.add_argument("--formality", choices=["default", "more", "less", "prefer_more", "prefer_less"])
    p.add_argument("--context", help="extra context that influences the translation but is not translated")
    p.add_argument("--key", help=f"DeepL auth key (default: ${ENV_KEY})")
    p.add_argument("--timeout", type=float, default=30.0)
    p.add_argument("--force", action="store_true",
                   help="call the API even if the input contains no Chinese characters")
    return p


def read_input(args, stdin) -> str:
    if args.text is not None:
        return args.text
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            return f.read()
    return stdin.read()


def main(argv=None, stdin=None, post: Callable = http_post) -> int:
    args = build_parser().parse_args(argv)
    stdin = stdin if stdin is not None else sys.stdin
    text = read_input(args, stdin)
    if not text.strip():
        print("zh2en: no input text", file=sys.stderr)
        return EXIT_USAGE
    if not args.force and not contains_chinese(text):
        sys.stdout.write(text if text.endswith("\n") else text + "\n")
        return EXIT_OK
    key = args.key or os.environ.get(ENV_KEY)
    if not key:
        print(f"zh2en: no API key. Set {ENV_KEY} or pass --key.", file=sys.stderr)
        return EXIT_NO_KEY
    try:
        out = translate(text, key, source=args.source, target=args.target, formality=args.formality,
                        context=args.context, timeout=args.timeout, post=post)
    except DeepLError as e:
        if e.status == 0:
            print(f"zh2en: {e}", file=sys.stderr)
            return EXIT_NETWORK
        print(f"zh2en: DeepL returned HTTP {e.status}: {e}", file=sys.stderr)
        return EXIT_AUTH_OR_QUOTA if e.status in NO_RETRY_FATAL else EXIT_HTTP
    sys.stdout.write(out if out.endswith("\n") else out + "\n")
    return EXIT_OK


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
