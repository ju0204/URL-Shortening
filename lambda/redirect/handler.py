import json
import os
import hashlib
import time
from datetime import datetime, timezone
from decimal import Decimal


import boto3

dynamodb = boto3.resource("dynamodb")
urls_table = dynamodb.Table(os.environ.get("URLS_TABLE", "url-shortener-urls"))
clicks_table = dynamodb.Table(os.environ.get("CLICKS_TABLE", "url-shortener-clicks"))

# Redirect code: 301(영구) or 302(임시)
REDIRECT_STATUS = int(os.environ.get("REDIRECT_STATUS", "301"))


def lambda_handler(event, context):
    """
    GET /{shortId}
    - urls 테이블에서 원본 조회
    - clicks 테이블에 클릭 로그 저장
    - urls 테이블 clickCount 증가
    - 301/302 Redirect
    """
    start = time.time()

    method, route, path = extract_http_info(event)

    headers = event.get("headers") or {}
    user_agent = get_header(headers, "user-agent")
    referer = get_header(headers, "referer") or "direct"

    request_context = event.get("requestContext", {}) or {}
    source_ip = (
        ((request_context.get("http") or {}).get("sourceIp"))
        or ((request_context.get("identity") or {}).get("sourceIp"))
        or ""
    )
    ip_hash = hash_ip(source_ip)

    short_id = None  # 예외 발생해도 로그 찍기 위해 미리 선언

    try:
        short_id = extract_short_id(event)
        if not short_id:
            latency_ms = int((time.time() - start) * 1000)
            log_json(
                "WARN",
                "shortId missing",
                requestId=context.aws_request_id,
                shortId=short_id,
                statusCode=400,
                latencyMs=latency_ms,
                referer=referer,
                userAgent=user_agent,
                ipHash=ip_hash,
                route=route,
                method=method,
                path=path,
            )
            return json_response(400, {"error": "Short ID is required"})

        # 1) 원본 URL 조회
        resp = urls_table.get_item(Key={"shortId": short_id})
        item = resp.get("Item")
        if not item:
            latency_ms = int((time.time() - start) * 1000)
            log_json(
                "WARN",
                "url not found",
                requestId=context.aws_request_id,
                shortId=short_id,
                statusCode=404,
                latencyMs=latency_ms,
                referer=referer,
                userAgent=user_agent,
                ipHash=ip_hash,
                route=route,
                method=method,
                path=path,
            )
            return json_response(404, {"error": "URL not found"})

        original_url = item.get("originalUrl")
        if not original_url:
            latency_ms = int((time.time() - start) * 1000)
            log_json(
                "ERROR",
                "originalUrl missing",
                requestId=context.aws_request_id,
                shortId=short_id,
                statusCode=500,
                latencyMs=latency_ms,
                referer=referer,
                userAgent=user_agent,
                ipHash=ip_hash,
                route=route,
                method=method,
                path=path,
            )
            return json_response(500, {"error": "Invalid data: originalUrl missing"})
        # 2) 클릭 로그 + 카운트 증가 (실패해도 리다이렉트는 되게)
        try:
            log_click(short_id, event)
        except Exception as e:
            print("Failed to log click:", str(e))

        try:
            urls_table.update_item(
                Key={"shortId": short_id},
                UpdateExpression="SET clickCount = if_not_exists(clickCount, :zero) + :inc",
                ExpressionAttributeValues={
                    ":zero": Decimal(0),
                    ":inc": Decimal(1),
                },
            )
        except Exception as e:
            print("Failed to update clickCount:", str(e))

        # 3) Redirect
        latency_ms = int((time.time() - start) * 1000)
        log_json(
            "INFO",
            "redirect handled",
            requestId=context.aws_request_id,
            shortId=short_id,
            statusCode=REDIRECT_STATUS,
            latencyMs=latency_ms,
            referer=referer,
            userAgent=user_agent,
            ipHash=ip_hash,
            route=route,
            method=method,
            path=path,
        )
        return {
            "statusCode": REDIRECT_STATUS,
            "headers": {
                "Location": original_url,
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
            "body": "",
        }

    except Exception as e:
        latency_ms = int((time.time() - start) * 1000)
        log_json(
            "ERROR",
            "redirect failed",
            requestId=context.aws_request_id,
            shortId=short_id,
            statusCode=500,
            latencyMs=latency_ms,
            referer=referer,
            userAgent=user_agent,
            ipHash=ip_hash,
            route=route,
            method=method,
            path=path,
            errorType=type(e).__name__,
            errorMessage=str(e),
        )
        return json_response(500, {"error": "Internal server error"})

# ---------------- helpers ----------------

def extract_short_id(event) -> str | None:
    pp = event.get("pathParameters") or {}
    short_id = pp.get("shortId")
    if short_id:
        return short_id

    raw_path = (event.get("rawPath") or event.get("path") or "").strip("/")
    if raw_path and raw_path.lower() not in ("prod", "dev"):
        return raw_path.split("/")[-1]

    return None


def log_click(short_id: str, event: dict):
    headers = event.get("headers") or {}
    headers_lc = {str(k).lower(): str(v) for k, v in headers.items()}

    source_ip = (
        (event.get("requestContext") or {}).get("http", {}).get("sourceIp")
        or (event.get("requestContext") or {}).get("identity", {}).get("sourceIp")
        or ""
    )

    ua = headers_lc.get("user-agent", "")
    referer = headers_lc.get("referer", "direct")

    ts = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    click_item = {
        "shortId": short_id,
        "timestamp": ts,
        "ip": hash_ip(source_ip),
        "userAgent": ua,
        "referer": referer,
    }

    clicks_table.put_item(Item=click_item)


def hash_ip(ip: str) -> str:
    if not ip:
        return "unknown"
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()[:16]


def json_response(status_code: int, body: dict):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
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

    # API Gateway HTTP API (v2)
    rc = event.get("requestContext", {}) or {}
    http = rc.get("http", {}) or {}
    if http:
        method = http.get("method")
        path = http.get("path")
        route_key = event.get("routeKey")  # 예: "GET /{shortId}"
        route = route_key if route_key and route_key != "$default" else path

    # API Gateway REST API (v1) fallback
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