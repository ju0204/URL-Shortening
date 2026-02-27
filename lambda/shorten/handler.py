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
    start = time.time()

    method, route, path = extract_http_info(event)
    headers = event.get("headers") or {}
    user_agent = get_header(headers, "user-agent")

    request_id = getattr(context, "aws_request_id", None)
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
            latency_ms = int((time.time() - start) * 1000)
            log_json(
                "WARN",
                "shorten invalid url",
                requestId=request_id,
                statusCode=400,
                latencyMs=latency_ms,
                route=route,
                method=method,
                path=path,
                userAgent=user_agent,
                urlDomain=safe_domain(original_url),
                hasProvidedTitle=bool(provided_title),
                errorMessage=err,
            )
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
                latency_ms = int((time.time() - start) * 1000)
                log_json(
                    "ERROR",
                    "shorten dynamodb error",
                    requestId=request_id,
                    statusCode=500,
                    latencyMs=latency_ms,
                    route=route,
                    method=method,
                    path=path,
                    userAgent=user_agent,
                    urlDomain=safe_domain(original_url),
                    errorType=type(e).__name__,
                    errorMessage=str(e),
                )
                return create_response(500, {"error": "Internal server error"})

        if not short_id:
            latency_ms = int((time.time() - start) * 1000)
            log_json(
                "ERROR",
                "shorten id generation failed",
                requestId=request_id,
                statusCode=500,
                latencyMs=latency_ms,
                route=route,
                method=method,
                path=path,
                userAgent=user_agent,
                urlDomain=safe_domain(original_url),
            )
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

        latency_ms = int((time.time() - start) * 1000)
        log_json(
            "INFO",
            "shorten created",
            requestId=request_id,
            statusCode=200,
            latencyMs=latency_ms,
            route=route,
            method=method,
            path=path,
            userAgent=user_agent,
            createdShortId=short_id,
            urlDomain=safe_domain(original_url),
            hasProvidedTitle=bool(provided_title),
        )

        return create_response(200, {
            "shortId": short_id,
            "shortUrl": short_url,
            "title": title,
            "originalUrl": original_url
        })

    except ValueError:
        latency_ms = int((time.time() - start) * 1000)
        log_json(
            "WARN",
            "shorten invalid json body",
            requestId=request_id,
            statusCode=400,
            latencyMs=latency_ms,
            route=route,
            method=method,
            path=path,
            userAgent=user_agent,
        )
        return create_response(400, {"error": "Invalid JSON body"})
    
    except Exception as e:
        print("Unhandled error:", str(e))
        latency_ms = int((time.time() - start) * 1000)
        log_json(
            "ERROR",
            "shorten failed",
            requestId=request_id,
            statusCode=500,
            latencyMs=latency_ms,
            route=route,
            method=method,
            path=path,
            userAgent=user_agent,
            errorType=type(e).__name__,
            errorMessage=str(e),
        )
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

def log_json(level, message, **kwargs):
    log_obj = {
        "level": level,
        "message": message,
        **kwargs,
    }
    print(json.dumps(log_obj, ensure_ascii=False))


def extract_http_info(event):
    method = None
    route = None
    path = None

    # HTTP API (v2)
    rc = event.get("requestContext", {}) or {}
    http = rc.get("http", {}) or {}
    if http:
        method = http.get("method")
        path = http.get("path")
        route_key = event.get("routeKey")  # ex) "POST /shorten"
        route = route_key if route_key and route_key != "$default" else path

    # REST API (v1) fallback
    if method is None:
        method = event.get("httpMethod")
    if path is None:
        path = event.get("path")
    if route is None:
        route = event.get("resource") or path

    return method, route, path


def get_header(headers, key):
    if not headers:
        return None
    return headers.get(key) or headers.get(key.lower()) or headers.get(key.title())


def safe_domain(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return (urlparse(url).hostname or "").lower() or None
    except Exception:
        return None