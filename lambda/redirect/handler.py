import json
import os
import hashlib
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
    try:
        short_id = extract_short_id(event)
        if not short_id:
            return json_response(400, {"error": "Short ID is required"})

        # 1) 원본 URL 조회
        resp = urls_table.get_item(Key={"shortId": short_id})
        item = resp.get("Item")
        if not item:
            return json_response(404, {"error": "URL not found"})

        original_url = item.get("originalUrl")
        if not original_url:
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
        print("Unhandled error:", str(e))
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
