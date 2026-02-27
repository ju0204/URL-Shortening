# lambda/stats/handler.py
import json
import os
import time
from datetime import datetime, timedelta, timezone
from collections import defaultdict, Counter
from urllib.parse import urlparse

import boto3
from boto3.dynamodb.conditions import Key

# ---- DynamoDB ----
dynamodb = boto3.resource("dynamodb")
URLS_TABLE = os.environ.get("URLS_TABLE", "url-shortener-urls")
CLICKS_TABLE = os.environ.get("CLICKS_TABLE", "url-shortener-clicks")

urls_table = dynamodb.Table(URLS_TABLE)
clicks_table = dynamodb.Table(CLICKS_TABLE)

# ---- Config ----
TOP_REFERERS = int(os.environ.get("TOP_REFERERS", "5"))

# period → timedelta 매핑
PERIOD_MAP = {
    "1min": timedelta(minutes=1),
    "1m": timedelta(minutes=1),
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "1d": timedelta(days=1),
    "7d": timedelta(days=7),
}

def lambda_handler(event, context):
    """
    GET /stats/{shortId}?period=7d
    - urls 테이블: shortId 존재 확인 + 기본 정보(title, originalUrl)
    - clicks 테이블: 기간 내 클릭 로그 Query
    - 통계 계산: clicksByHour, clicksByDay, clicksByReferer(TopN+other), totalClicks
    """
    start = time.time()

    method, route, path = extract_http_info(event)
    headers = event.get("headers") or {}
    user_agent = get_header(headers, "user-agent")
    request_id = getattr(context, "aws_request_id", None)

    short_id = None
    period = None
    try:
        # 1) shortId
        short_id = (event.get("pathParameters") or {}).get("shortId")
        if not short_id:
            latency_ms = int((time.time() - start) * 1000)
            log_json(
                "WARN",
                "stats shortId missing",
                requestId=request_id,
                shortId=short_id,
                statusCode=400,
                latencyMs=latency_ms,
                route=route,
                method=method,
                path=path,
                userAgent=user_agent,
            )
            return create_response(400, {"error": "Short ID is required"})

        # 2) period 파싱 (기본 7d)
        qs = event.get("queryStringParameters") or {}
        period = (qs.get("period") or "7d").lower().strip()
        delta = PERIOD_MAP.get(period)
        if not delta:
            latency_ms = int((time.time() - start) * 1000)
            log_json(
                "WARN",
                "stats invalid period",
                requestId=request_id,
                shortId=short_id,
                period=period,
                statusCode=400,
                latencyMs=latency_ms,
                route=route,
                method=method,
                path=path,
                userAgent=user_agent,
            )
            return create_response(400, {"Invalid period (use 1min/1m, 1h, 24h/1d, 7d)"})
        now = datetime.now(timezone.utc)
        start_at = now - delta

        # 3) URL 정보 조회(존재 확인)
        url_item = urls_table.get_item(Key={"shortId": short_id}).get("Item")
        if not url_item:
            latency_ms = int((time.time() - start) * 1000)
            log_json(
                "WARN",
                "stats url not found",
                requestId=request_id,
                shortId=short_id,
                period=period,
                statusCode=404,
                latencyMs=latency_ms,
                route=route,
                method=method,
                path=path,
                userAgent=user_agent,
            )
            return create_response(404, {"error": "URL not found"})

        # 4) clicks 조회 (timestamp는 ISO string, SK)
        # DynamoDB query 조건: timestamp >= start_at_iso
        start_iso = start_at.isoformat(timespec="seconds").replace("+00:00", "Z")

        clicks = query_clicks_since(short_id, start_iso)

        # 5) 통계 계산
        stats = calculate_stats(clicks)

        # totalClicks: urls 테이블의 clickCount를 우선 사용(없으면 clicks count)
        total_clicks = int(url_item.get("clickCount", len(clicks)))

        latency_ms = int((time.time() - start) * 1000)
        log_json(
            "INFO",
            "stats fetched",
            requestId=request_id,
            shortId=short_id,
            period=period,
            statusCode=200,
            latencyMs=latency_ms,
            route=route,
            method=method,
            path=path,
            userAgent=user_agent,
            resultClicks=len(clicks),   # 기간 내 클릭 수
            totalClicks=total_clicks,   # 누적 클릭 수
        )

        return create_response(200, {
            "shortId": short_id,
            "originalUrl": url_item.get("originalUrl", ""),
            "title": url_item.get("title", ""),
            "period": period,
            "startAt": start_iso,
            "endAt": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "totalClicks": total_clicks,
            **stats
        })

    except Exception as e:
        print("Error:", str(e))
        latency_ms = int((time.time() - start) * 1000)
        log_json(
            "ERROR",
            "stats failed",
            requestId=request_id,
            shortId=short_id,
            period=period,
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


def query_clicks_since(short_id: str, start_iso: str):
    """
    clicks 테이블:
      PK: shortId (S)
      SK: timestamp (S, ISO)
    조건: shortId = :sid AND timestamp >= :start
    pagination 처리(LastEvaluatedKey)
    """
    items = []
    kwargs = {
        "KeyConditionExpression": Key("shortId").eq(short_id) & Key("timestamp").gte(start_iso),
        "ScanIndexForward": True,  # 시간 오름차순(원하면 False로 바꿔도 됨)
    }

    while True:
        resp = clicks_table.query(**kwargs)
        items.extend(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek

    return items


def calculate_stats(clicks: list):
    """
    clicksByHour: {"0":1, "1":0, ..., "23":2} (문자열 키로 통일)
    clicksByDay: {"YYYY-MM-DD": n, ...}
    clicksByReferer: Top N + other
    peakHour / topReferer: 선택 편의 필드
    """
    clicks_by_hour = {str(h): 0 for h in range(24)}
    clicks_by_day = defaultdict(int)
    referer_counter = Counter()

    for click in clicks:
        ts = click.get("timestamp") or ""
        ref = click.get("referer") or "direct"
        ref_domain = extract_domain(ref)
        referer_counter[ref_domain] += 1

        dt = parse_iso(ts)
        if dt:
            clicks_by_hour[str(dt.hour)] += 1
            clicks_by_day[dt.date().isoformat()] += 1

    # referer topN + other
    top = referer_counter.most_common(TOP_REFERERS)
    clicks_by_referer = {}
    used = 0
    for k, v in top:
        clicks_by_referer[k] = v
        used += v
    other = len(clicks) - used
    if other > 0:
        clicks_by_referer["other"] = other

    peak_hour = max(clicks_by_hour, key=lambda k: clicks_by_hour[k]) if clicks else None
    top_ref = top[0][0] if top else None

    return {
        "clicksByHour": clicks_by_hour,
        "clicksByDay": dict(sorted(clicks_by_day.items())),
        "clicksByReferer": clicks_by_referer,
        "peakHour": peak_hour,
        "topReferer": top_ref,
    }


def extract_domain(url: str) -> str:
    if not url or url == "direct":
        return "direct"
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        return host if host else "unknown"
    except Exception:
        return "unknown"


def parse_iso(ts: str):
    try:
        if ts.endswith("Z"):
            ts = ts.replace("Z", "+00:00")
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def create_response(status_code: int, body: dict):
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

    # HTTP API (v2)
    rc = event.get("requestContext", {}) or {}
    http = rc.get("http", {}) or {}
    if http:
        method = http.get("method")
        path = http.get("path")
        route_key = event.get("routeKey")  # ex) "GET /stats/{shortId}"
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