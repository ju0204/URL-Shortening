import json
import os
import re
import time
import random
import string
from datetime import datetime, timezone
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import boto3
from botocore.exceptions import ClientError

# --- DynamoDB ---
dynamodb = boto3.resource("dynamodb")
URLS_TABLE = os.environ.get("URLS_TABLE", "url-shortener-urls")
table = dynamodb.Table(URLS_TABLE)

# --- Config ---
BASE_URL = os.environ.get("BASE_URL", "").rstrip("/")  # e.g. https://short.url
SHORT_ID_LEN = int(os.environ.get("SHORT_ID_LEN", "8"))
MAX_RETRIES = int(os.environ.get("MAX_RETRIES", "5"))
TITLE_FETCH_TIMEOUT = float(os.environ.get("TITLE_FETCH_TIMEOUT", "2.5"))  # seconds
MAX_HTML_BYTES = int(os.environ.get("MAX_HTML_BYTES", "262144"))  # 256KB

BASE62_ALPHABET = string.ascii_letters + string.digits  # a-zA-Z0-9 (62 chars)


def lambda_handler(event, context):
    # CORS preflight
    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS" or event.get("httpMethod") == "OPTIONS":
        return create_response(200, {})

    try:
        body = parse_body(event)
        original_url = (body.get("url") or "").strip()
        provided_title = (body.get("title") or "").strip()

        # 1) Validate URL
        err = validate_url(original_url)
        if err:
            return create_response(400, {"error": err})

        # 2) Title: prefer provided, else fetch
        title = provided_title
        if not title:
            title = fetch_title_safe(original_url)

        # fallback: title이 없으면 도메인으로 채우기
        if not title:
            host = (urlparse(original_url).hostname or "").lower()
            title = host if host else "Untitled"


        # 3) Create shortId + conditional put with retries
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        short_id = None

        for attempt in range(MAX_RETRIES):
            candidate = generate_base62_id(SHORT_ID_LEN)

            item = {
                "shortId": candidate,
                "originalUrl": original_url,
                "title": title,
                "createdAt": created_at,
                "clickCount": 0,
            }

            try:
                table.put_item(
                    Item=item,
                    ConditionExpression="attribute_not_exists(shortId)",
                )
                short_id = candidate
                break
            except ClientError as e:
                if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                    # collision -> retry
                    continue
                # other dynamodb error
                print("DynamoDB error:", e)
                return create_response(500, {"error": "Internal server error"})

        if not short_id:
            return create_response(500, {"error": "Failed to generate unique shortId"})

        # 4) shortUrl
        if BASE_URL:
            short_url = f"{BASE_URL}/{short_id}"
        else:
            # API Gateway (HTTP API v2) fallback
            domain = event.get("requestContext", {}).get("domainName")
            stage = event.get("requestContext", {}).get("stage")
            if domain and stage:
                short_url = f"https://{domain}/{stage}/{short_id}"
            elif domain:
                short_url = f"https://{domain}/{short_id}"
            else:
                short_url = f"/{short_id}"  # minimal fallback

        return create_response(200, {"shortId": short_id, "shortUrl": short_url, "title": title,"originalUrl": original_url})

    except ValueError:
        return create_response(400, {"error": "Invalid JSON body"})
    except Exception as e:
        print("Unhandled error:", str(e))
        return create_response(500, {"error": "Internal server error"})


# ---------------- helpers ----------------

def parse_body(event):
    raw = event.get("body")
    if raw is None:
        return {}
    if event.get("isBase64Encoded"):
        import base64
        raw = base64.b64decode(raw).decode("utf-8", errors="replace")
    if isinstance(raw, (dict, list)):
        return raw
    return json.loads(raw)


def validate_url(url: str):
    if not url:
        return "Invalid URL"
    try:
        p = urlparse(url)
    except Exception:
        return "Invalid URL"

    if p.scheme not in ("http", "https"):
        return "Invalid URL"
    if not p.netloc:
        return "Invalid URL"

    # optional: basic SSRF mitigation (very light)
    # - block localhost
    host = (p.hostname or "").lower()
    if host in ("localhost", "127.0.0.1", "::1"):
        return "Invalid URL"

    return None


def generate_base62_id(length: int) -> str:
    # cryptographically strong randomness
    try:
        import secrets
        return "".join(secrets.choice(BASE62_ALPHABET) for _ in range(length))
    except Exception:
        return "".join(random.choice(BASE62_ALPHABET) for _ in range(length))


def fetch_title_safe(url: str) -> str | None:
    """
    Fetch HTML and extract <title>.
    Fallback to og:title if <title> is missing.
    """
    try:
        req = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; url-shortener-bot/1.0)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            method="GET",
        )

        with urlopen(req, timeout=TITLE_FETCH_TIMEOUT) as resp:
            content_type = (resp.headers.get("Content-Type") or "").lower()
            if "text/html" not in content_type:
                return None

            data = resp.read(MAX_HTML_BYTES)
            html = data.decode("utf-8", errors="ignore")

        # 1) <title> 우선
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if m:
            title = re.sub(r"\s+", " ", m.group(1)).strip()
            if title:
                return title[:200]

        # 2) og:title fallback (유튜브/미디어 사이트에 자주 있음)
        m = re.search(
            r'<meta[^>]+property=["\']og:title["\'][^>]*content=["\']([^"\']+)["\']',
            html,
            re.IGNORECASE
        )
        if m:
            og = re.sub(r"\s+", " ", m.group(1)).strip()
            if og:
                return og[:200]

        return None

    except Exception as e:
        print("title fetch failed:", str(e))
        return None



def create_response(status_code: int, body: dict):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "POST,OPTIONS",
        },
        "body": json.dumps(body, ensure_ascii=False),
    }
