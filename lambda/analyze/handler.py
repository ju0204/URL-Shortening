# lambda/analyze/handler.py
import os
import json
import re
import uuid
import boto3
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from collections import Counter, defaultdict
from urllib.parse import urlparse
from decimal import Decimal, ROUND_HALF_UP
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError

DDB = boto3.resource("dynamodb")
CW = boto3.client("cloudwatch")
S3 = boto3.client("s3")

ANALYTICS_BUCKET = os.getenv("ANALYTICS_BUCKET", "")
ANALYTICS_PREFIX = os.getenv("ANALYTICS_PREFIX", "analytics").strip("/")  # "analytics"
EXPORT_ENABLED = os.getenv("EXPORT_ENABLED", "false").lower() == "true"
EXPORT_CHECKPOINT_KEY = os.getenv("EXPORT_CHECKPOINT_KEY", f"{ANALYTICS_PREFIX}/state/last_export_ts.json")

# Bedrock Runtime (서울: ap-northeast-2에서 지원) - 모델ID는 env로 주입
BEDROCK_RUNTIME = boto3.client("bedrock-runtime")

URLS_TABLE = os.environ["URLS_TABLE"]
CLICKS_TABLE = os.environ["CLICKS_TABLE"]
INSIGHTS_TABLE = os.environ["INSIGHTS_TABLE"]
AI_TABLE = os.environ["AI_TABLE"]

MODEL_TREND = os.getenv("BEDROCK_MODEL_TREND", "amazon.nova-micro-v1:0")
MODEL_INSIGHT = os.getenv("BEDROCK_MODEL_INSIGHT", "amazon.nova-lite-v1:0")

TOP_N_REFERER = int(os.getenv("TOP_N_REFERER", "5"))
MAX_URLS_PER_RUN = int(os.getenv("MAX_URLS_PER_RUN", "200"))  # 한 번에 너무 많이 돌리지 않게
ENABLE_AI_DEFAULT = os.getenv("ENABLE_AI_DEFAULT", "false").lower() == "true"

AI_TOP_URL_N = int(os.getenv("AI_TOP_URL_N", "20"))
AI_TOP_TIMEBIN_N = int(os.getenv("AI_TOP_TIMEBIN_N", "10"))
AI_SOURCE_PERIOD_DEFAULT = os.getenv("AI_SOURCE_PERIOD_DEFAULT", "P#24H")
MAX_CLICKS_PER_SID = int(os.getenv("MAX_CLICKS_PER_SID", "1000"))

KST = timezone(timedelta(hours=9))


SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")
ALERT_ONLY_PERIOD = os.getenv("ALERT_ONLY_PERIOD", "P#1H")
ALERT_STATE_KEY = os.getenv(
    "ALERT_STATE_KEY",
    "analytics/state/alert_last_suspicious_by_sid_p1h.json"
)
MAX_ALERTS_PER_RUN = int(os.getenv("MAX_ALERTS_PER_RUN", "5"))

# suspicious rule thresholds
SUSP_WINDOW_SEC = int(os.getenv("SUSP_WINDOW_SEC", "60"))
SUSP_REPEAT_THRESHOLD = int(os.getenv("SUSP_REPEAT_THRESHOLD", "10"))

BOT_UA_PAT = re.compile(r"(bot|spider|crawler|headless|python-requests|curl|wget)", re.I)

COMMON_2LEVEL_SUFFIX = {
    "co.kr", "or.kr", "go.kr", "ac.kr",
    "co.jp", "ne.jp", "or.jp",
    "co.uk", "org.uk", "ac.uk",
    "com.au", "net.au", "org.au",
}

def lambda_handler(event, context):
    event = event or {}

    rc = event.get("requestContext") or {}
    http = rc.get("http") or {}
    method = http.get("method")  # HTTP API면 존재
    stage = rc.get("stage") or ""  # 예: "prod"
    raw_path = event.get("rawPath") or ""

    # -------------------------
    # 1) HTTP API 라우팅 처리
    # -------------------------
    if method:
        # CORS preflight
        if method == "OPTIONS":
            return _resp(200, {})

        # ✅ stage prefix(/prod) 제거: "/prod/ai/latest" -> "/ai/latest"
        if stage and raw_path.startswith(f"/{stage}/"):
            path = raw_path[len(stage) + 1:]  # "/prod" 길이만큼 제거하고 "/" 유지
        elif stage and raw_path == f"/{stage}":
            path = "/"
        else:
            path = raw_path

        # (디버그용) 잠깐 켜두면 원인 바로 보임
        print(json.dumps({
            "type": "HTTP_API_IN",
            "method": method,
            "stage": stage,
            "rawPath": raw_path,
            "normalizedPath": path,
            "routeKey": rc.get("routeKey"),
            "query": event.get("queryStringParameters"),
        }, ensure_ascii=False))

        if path == "/ai/latest" and method == "GET":
            period_key = _get_query(event, "periodKey", "P#30MIN").upper()
            allowed = {"P#1MIN", "P#5MIN", "P#30MIN", "P#1H", "P#24H", "P#7D"}
            if period_key not in allowed:
                return _resp(400, {"message": "INVALID_periodKey", "allowed": sorted(list(allowed))})
            return _resp(200, get_latest_ai(period_key))

        return _resp(404, {"message": "NOT_FOUND"})

    # ---------------------------------
    # 2) EventBridge / 수동 invoke 처리
    # ---------------------------------
    job = event.get("job", "aggregate_only")

    if job == "ai_only":
        ai_period_key = event.get("aiPeriodKey", "P#30MIN")
        source_period_key = event.get("sourcePeriodKey", AI_SOURCE_PERIOD_DEFAULT)
        result = run_ai_job(ai_period_key, source_period_key)
        print(json.dumps({"type": "AI_ONLY_RESULT", "result": result}, ensure_ascii=False))
        return _resp(200, result)

    period_key = event.get("periodKey", "P#1H")
    result = run_aggregation(period_key)
    print(json.dumps({"type": "ANALYZE_RESULT", "result": result}, ensure_ascii=False))
    return _resp(200, result)







def extract_domain(original_url: str) -> str:
    if not original_url:
        return ""
    u = original_url.strip()
    if "://" not in u:
        u = "https://" + u

    p = urlparse(u)
    host = (p.netloc or "").strip().lower()

    # netloc이 비는 케이스 보정 (rare)
    if not host and p.path:
        host = p.path.split("/")[0].lower()

    # userinfo 제거
    if "@" in host:
        host = host.split("@", 1)[1]

    # port 제거
    if ":" in host:
        host = host.split(":", 1)[0]

    # www 제거
    if host.startswith("www."):
        host = host[4:]

    if "." not in host:
        return ""
    return host

def to_root_domain(host: str) -> str:
    """
    비용 최소를 위해 tldextract 같은 외부 라이브러리 없이 "대부분 맞는" 루트 도메인만 처리.
    (notion.site, youtube.com 같이 UI에서 원하는 형태)
    """
    if not host:
        return ""
    parts = host.split(".")
    if len(parts) < 2:
        return ""

    last2 = ".".join(parts[-2:])
    last3 = ".".join(parts[-3:])

    # co.kr / co.uk 같은 2단 suffix면 마지막 3개를 루트로
    if last2 in COMMON_2LEVEL_SUFFIX and len(parts) >= 3:
        return last3

    return last2


def normalize_url(u: str, max_len: int = 140) -> str:
    """AI 입력 토큰 폭발 방지: query/fragment 제거 + 너무 길면 자르기"""
    if not u:
        return ""
    s = u.strip()
    if "://" not in s:
        s = "https://" + s
    p = urlparse(s)
    base = f"{p.scheme}://{p.netloc}{p.path}"
    return base[:max_len] if len(base) > max_len else base


def to_5min_slot(ts_iso: str) -> str:
    """KST(Asia/Seoul) 기준 5분 슬롯 -> 'HH:MM'"""
    dt_utc = datetime.strptime(ts_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    dt_kst = dt_utc.astimezone(KST)

    m = (dt_kst.minute // 5) * 5
    return f"{dt_kst.hour:02d}:{m:02d}"


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    # DynamoDB range_key(timestamp)와 정렬/비교가 안전하도록 ISO 8601 Z 형태 유지 권장
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_period_key(period_key: str):
    """
    periodKey 예: P#1MIN / P#1H / P#24H / P#7D
    """
    period_key = period_key.upper()
    if period_key == "P#1MIN":
        return timedelta(minutes=1)
    if period_key == "P#5MIN":          # ✅ 추가
        return timedelta(minutes=5)
    if period_key == "P#30MIN":
        return timedelta(minutes=30)
    if period_key == "P#1H":
        return timedelta(hours=1)
    if period_key == "P#24H":
        return timedelta(hours=24)
    if period_key == "P#7D":
        return timedelta(days=7)
    raise ValueError(f"Unsupported periodKey: {period_key}")


def chunked(iterable, size):
    buf = []
    for x in iterable:
        buf.append(x)
        if len(buf) >= size:
            yield buf
            buf = []
    if buf:
        yield buf


def bedrock_invoke_text(model_id: str, user_text: str, max_tokens: int = 300):
    """
    Nova (Inference Profile) 호출: messages 포맷 필요
    """
    body = {
        "messages": [
            {
                "role": "user",
                "content": [{"text": user_text}]
            }
        ],
        "inferenceConfig": {
            "maxTokens": max_tokens,
            "temperature": 0.2,
            "topP": 0.9
        }
    }

    resp = BEDROCK_RUNTIME.invoke_model(
        modelId=model_id,
        body=json.dumps(body).encode("utf-8"),
        accept="application/json",
        contentType="application/json",
    )

    raw = resp["body"].read()
    data = json.loads(raw)

    # Nova messages 응답에서 텍스트 추출 (방어적으로)
    if isinstance(data, dict):
        # 보통: output.message.content[0].text
        out = data.get("output") or {}
        msg = out.get("message") or {}
        content = msg.get("content")
        if isinstance(content, list) and content:
            c0 = content[0]
            if isinstance(c0, dict) and "text" in c0:
                return c0["text"]

        # 혹시 다른 키로 오는 경우 대비
        if "results" in data and data["results"]:
            r0 = data["results"][0]
            if isinstance(r0, dict):
                return r0.get("outputText") or r0.get("text") or json.dumps(data, ensure_ascii=False)

        for k in ("outputText", "completion", "generatedText", "text"):
            if k in data and isinstance(data[k], str):
                return data[k]

    return json.dumps(data, ensure_ascii=False)



def put_custom_metrics(namespace: str, metrics: dict, dims: list):
    # 커스텀 메트릭은 숫자만 가능 (문장/텍스트는 로그로)
    metric_data = []
    for k, v in metrics.items():
        metric_data.append({
            "MetricName": k,
            "Dimensions": dims,
            "Timestamp": datetime.utcnow(),
            "Value": float(v),
            "Unit": "Count" if "Clicks" in k or "Count" in k else "None",
        })
    # PutMetricData는 한 번에 최대 20개
    for batch in chunked(metric_data, 20):
        CW.put_metric_data(Namespace=namespace, MetricData=batch)


def compute_suspicious(click_items):
    """
    비정상 클릭 감지 룰 (OR):
    1) bot UA 패턴 포함 (클릭 1건 단위)
    2) 동일 ipHash + 동일 userAgent가 SUSP_WINDOW_SEC 내 SUSP_REPEAT_THRESHOLD 이상 반복(burst)

    반환: suspiciousClicks (중복 제거된 클릭 건수)
    """

    # 클릭 1건을 유니크하게 식별할 키 (중복 카운트 방지)
    def click_key(it):
        return (
            it.get("timestamp", "") or "",
            it.get("ip", "") or "",
            it.get("userAgent", "") or "",
        )

    suspicious = set()

    # 1) bot UA: 클릭 단위로 바로 suspicious 처리
    for it in click_items:
        ua = (it.get("userAgent") or "")
        if ua and BOT_UA_PAT.search(ua):
            suspicious.add(click_key(it))

    # 2) burst: (ip, ua) 그룹별 슬라이딩 윈도우
    by_group = defaultdict(list)

    for it in click_items:
        ip_hash = it.get("ip", "") or ""
        ua = it.get("userAgent", "") or ""
        ts = it.get("timestamp", "") or ""

        if not (ip_hash and ua and ts):
            continue

        try:
            dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except Exception:
            continue

        by_group[(ip_hash, ua)].append((dt, it))

    for _, pairs in by_group.items():
        pairs.sort(key=lambda x: x[0])

        i = 0
        for j in range(len(pairs)):
            while pairs[j][0] - pairs[i][0] > timedelta(seconds=SUSP_WINDOW_SEC):
                i += 1

            window_size = j - i + 1
            if window_size >= SUSP_REPEAT_THRESHOLD:
                # 이 윈도우 안의 클릭들을 suspicious로 처리 (중복은 set이 제거)
                for k in range(i, j + 1):
                    suspicious.add(click_key(pairs[k][1]))

                # 비용/연산 최소화를 위해 그룹당 첫 burst 발견 시 종료
                break
        # TODO(알림) - 지금은 구현하지 않음(주석만)
        # [추천 초기 알람 기준 - 균형]
        # - 1H(P#1H): totalClicks >= 100 AND suspiciousRate >= 0.35 (옵션: suspiciousClicks >= 30)
        # - 24H(P#24H): totalClicks >= 300 AND suspiciousRate >= 0.25 (옵션: suspiciousClicks >= 80)
        # - 1MIN(P#1MIN): 알림 X (로그/대시보드 표시만)
        #
        # 구현 후보:
        # 1) CloudWatch Alarm: suspiciousRate를 커스텀 메트릭으로 올리고, Metric Math로 조건 구성
        # 2) insights에 alertLevel 필드만 저장 후 프론트에서 배지 표시

    return len(suspicious)
        

DEVICE_PATTERNS = {
    "mobile": re.compile(r"(iphone|ipod|android.*mobile|windows phone|blackberry|opera mini)", re.I),
    "tablet": re.compile(r"(ipad|android(?!.*mobile)|tablet)", re.I),
    "desktop": re.compile(r"(windows nt|macintosh|x11|linux)", re.I),
}

def classify_device(user_agent: str) -> str:
    ua = (user_agent or "").strip()
    if not ua:
        return "unknown"
    if BOT_UA_PAT.search(ua):
        return "bot"
    if DEVICE_PATTERNS["tablet"].search(ua):
        return "tablet"
    if DEVICE_PATTERNS["mobile"].search(ua):
        return "mobile"
    if DEVICE_PATTERNS["desktop"].search(ua):
        return "desktop"
    return "other"


def aggregate(click_items):
    
    """
    returns:
      totalClicks, clicksByHour(0-23), clicksByDay(YYYY-MM-DD), clicksByReferer(topN+other)
    """
    total = len(click_items)

    by_hour = Counter()
    by_day = Counter()
    by_ref = Counter()
    by_device = Counter()

    for it in click_items:
        ts = it.get("timestamp")
        ref = it.get("referer") or "direct"
        ua = it.get("userAgent") or ""
        try:
            dt_utc = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            dt_kst = dt_utc.astimezone(KST)

            by_hour[f"{dt_kst.hour:02d}"] += 1        # ✅ KST + 2자리
            by_day[dt_kst.strftime("%Y-%m-%d")] += 1  # ✅ KST 날짜
        except Exception:
            pass
        by_ref[ref] += 1

        device = classify_device(ua)    
        by_device[device] += 1

    # Top N referer + other
    top = by_ref.most_common(TOP_N_REFERER)
    top_keys = set([k for k, _ in top])

    compact_ref = {}
    other_sum = 0
    for k, v in by_ref.items():
        if k in top_keys:
            compact_ref[k] = v
        else:
            other_sum += v
    if other_sum > 0:
        compact_ref["other"] = other_sum

    return total, dict(by_hour), dict(by_day), compact_ref, dict(by_device)


def fetch_clicks_for_shortid(short_id: str, start_iso: str, end_iso: str, limit: int = 0):
    table = DDB.Table(CLICKS_TABLE)
    items = []
    last_key = None

    while True:
        kwargs = {
            "KeyConditionExpression": Key("shortId").eq(short_id) & Key("timestamp").between(start_iso, end_iso),
            "ProjectionExpression": "#ts, ip, userAgent, referer",
            "ExpressionAttributeNames": {"#ts": "timestamp"},
            "ScanIndexForward": False,  # 최신부터
        }

        # limit 처리
        if limit and limit > 0:
            remaining = limit - len(items)
            if remaining <= 0:
                break
            kwargs["Limit"] = min(1000, remaining)

        if last_key:
            kwargs["ExclusiveStartKey"] = last_key

        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        last_key = resp.get("LastEvaluatedKey")

        if not last_key:
            break
        if limit and len(items) >= limit:
            break

    return items



def list_urls(limit: int):
    """
    urls 테이블에서 shortId 목록을 가져온다.
    규모가 커지면 Scan은 비싸짐 -> 지금 단계(개인 프로젝트/초기)에서는 단순화.
    """
    table = DDB.Table(URLS_TABLE)
    items = []
    last_key = None

    while len(items) < limit:
        kwargs = {
            "ProjectionExpression": "shortId, title, clickCount, originalUrl",
            "Limit": min(100, limit - len(items))
        }
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key

        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break

    return items


def upsert_insight(short_id: str, period_key: str, start_at: str, end_at: str,
                   total: int, by_hour: dict, by_day: dict, by_ref: dict, by_device: dict,
                   suspicious_clicks: int):
    table = DDB.Table(INSIGHTS_TABLE)
    if total == 0:
        suspicious_rate_dec = Decimal("0")
    else:
        suspicious_rate_dec = (Decimal(str(suspicious_clicks)) / Decimal(str(total))).quantize(
            Decimal("0.0001"),
            rounding=ROUND_HALF_UP
        )

    table.update_item(
        Key={"shortId": short_id, "periodKey": period_key},
        UpdateExpression="""
            SET startAt = :sa,
                endAt = :ea,
                totalClicks = :t,
                clicksByHour = :h,
                clicksByDay = :d,
                clicksByReferer = :r,
                clicksByDevice = :dv,
                generatedAt = :ga,
                suspiciousClicks = :sc,
                suspiciousRate = :sr
        """,
        ExpressionAttributeValues={
            ":sa": start_at,
            ":ea": end_at,
            ":t": int(total),
            ":h": by_hour,
            ":d": by_day,
            ":r": by_ref,
            ":dv": by_device,
            ":ga": iso(now_utc()),
            ":sc": int(suspicious_clicks),
            ":sr": suspicious_rate_dec,
        }
    )
    return float(suspicious_rate_dec)

def safe_json_obj(raw_text: str):
    if raw_text is None:
        return None
    if isinstance(raw_text, (dict, list)):
        return raw_text

    s = str(raw_text).strip()

    # ```json ... ``` 안쪽만 뽑기 (앞뒤 텍스트가 있어도 OK)
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", s, flags=re.I | re.S)
    if fence:
        s = fence.group(1).strip()

    # 첫 JSON 객체/배열만 뽑기
    m = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", s)
    if m:
        s = m.group(1).strip()

    try:
        return json.loads(s)
    except Exception:
        return {"raw": str(raw_text)}


def put_ai_result(period_key: str, ai_trend: dict | None, ai_insight: dict | None):
    """AI 결과를 ai 테이블에 '누적 저장'"""
    if ai_trend is None and ai_insight is None:
        return

    table = DDB.Table(AI_TABLE)
    gen = iso(now_utc())

    item = {
        "periodKey": period_key,       # PK
        "aiGeneratedAt": gen,          # SK
    }
    if ai_trend is not None:
        item["aiTrend"] = ai_trend
    if ai_insight is not None:
        item["aiInsight"] = ai_insight

    table.put_item(Item=item)

def _scan_all_insights_for_period(period_key: str):
    """
    INSIGHTS_TABLE에서 periodKey가 같은 모든 shortId 아이템을 scan으로 가져온다.
    (초기/개인프로젝트 규모 전제. 커지면 GSI 권장)
    """
    table = DDB.Table(INSIGHTS_TABLE)
    items = []
    last_key = None

    while True:
        kwargs = {
            "FilterExpression": Attr("periodKey").eq(period_key),
            "ProjectionExpression": "periodKey, clicksByHour",
        }
        if last_key:
            kwargs["ExclusiveStartKey"] = last_key

        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break

    return items


def build_global_hourly_timebins(period_key: str):
    """
    periodKey(P#30MIN 등) 기준으로,
    모든 shortId의 clicksByHour를 합산해서 timeBins 리스트로 반환.
    output 예: [{"time":"06","clicks":12}, ... {"time":"21","clicks":95}]
    """
    rows = _scan_all_insights_for_period(period_key)

    # hour(0~23) 합산
    summed = Counter()

    for it in rows:
        by_hour = it.get("clicksByHour") or {}
        if not isinstance(by_hour, dict):
            continue
        for h, c in by_hour.items():
            try:
                hh = int(h)  # "6" -> 6
                cc = int(c)
                if 0 <= hh <= 23:
                    summed[hh] += cc
            except Exception:
                continue

    # 프론트 차트용: 0~23 전부 채워서 반환(빈 시간대 0)
    time_bins = []
    for hh in range(24):
        time_bins.append({
            "time": f"{hh:02d}",          # "06"
            "clicks": int(summed.get(hh, 0))
        })

    return time_bins


def get_latest_ai(period_key: str = "P#30MIN") -> dict:
    """
    ai 테이블에서 periodKey의 최신 1건을 가져온다.
    (PK=periodKey, SK=aiGeneratedAt)
    """
    table = DDB.Table(AI_TABLE)

    resp = table.query(
        KeyConditionExpression=Key("periodKey").eq(period_key),
        ScanIndexForward=False,
        Limit=1,
    )

    items = resp.get("Items", [])
    if not items:
        return {
            "periodKey": period_key,
            "found": False,
            "message": "NO_AI_RESULT",
        }

    item = items[0]

    # ✅ (1) 차트 데이터: INSIGHTS_TABLE에서 periodKey 기준 전체 shortId 합산
    chart_period_key = "P#24H"
    time_bins = build_global_hourly_timebins(chart_period_key)
    # ✅ (2) 추천 데이터: AI가 준 top3만 사용 (clicks 붙이지 않음)
    raw_ai_insight = item.get("aiInsight") or {}
    top3 = []
    if isinstance(raw_ai_insight, dict) and isinstance(raw_ai_insight.get("top3"), list):
        # top3가 ["15:20", ...] 이거나 [{"time":"15:20"}, ...] 둘 다 방어
        for x in raw_ai_insight["top3"]:
            if isinstance(x, str):
                t = x.strip()
            elif isinstance(x, dict):
                t = str(x.get("time") or "").strip()
            else:
                t = ""
            if t and t not in top3:
                top3.append(t)
            if len(top3) >= 3:
                break

    # 프론트가 원하는 구조로 aiInsight를 "chart + recommendation" 형태로만 내려줌
    shaped_ai_insight = {
        "chart": {
            "timeBins": time_bins
        },
        "recommendation": {
            "top3": top3
        }
    }

    return {
        "found": True,
        "periodKey": item.get("periodKey"),
        "aiGeneratedAt": item.get("aiGeneratedAt"),

        # ✅ aiTrend는 절대 안 건드림 (그대로)
        "aiTrend": item.get("aiTrend"),

        # ✅ aiInsight만 원하는 형태로 변환
        "aiInsight": shaped_ai_insight,
    }


def _get_query(event: dict, key: str, default=None):
    q = (event or {}).get("queryStringParameters") or {}
    v = q.get(key)
    return v if v not in (None, "") else default

def run_ai_job(ai_period_key: str, source_period_key: str):
    """
    AI 전용 Job
    - source_period_key 기간(기본 P#24H) 동안의 클릭 로그를 바탕으로
      1) Trend (Nova Micro): 도메인 TOP5 + 카테고리 TOP5
      2) Insight (Nova Lite): 최적 공유 시간 HH:MM TOP3
    - 결과는 ai 테이블에 누적 저장 (PK=ai_period_key, SK=aiGeneratedAt)
    """

    # 1) 기간 계산
    duration = parse_period_key(source_period_key)
    end_dt = now_utc()
    start_dt = end_dt - duration
    start_iso = iso(start_dt)
    end_iso = iso(end_dt)

    # 2) URL 목록 로드 (초기 단계니까 scan 기반)
    urls = list_urls(MAX_URLS_PER_RUN)

    # 3) 전역 집계
    top_url_clicks = Counter()  # normalizedUrl -> clicks
    domain_clicks = Counter()   # (선택) AI 결과 검증/백업용으로 남겨도 됨. 필요없으면 삭제 가능

    time_bins = Counter()       # "HH:MM" -> clicks
    total_clicks_all = 0



    urls_sorted = sorted(urls, key=lambda x: safe_int(x.get("clickCount", 0)), reverse=True)

    # 비용 방지: shortId당 클릭 로그 상한
    per_sid_limit = MAX_CLICKS_PER_SID if MAX_CLICKS_PER_SID > 0 else 0

    for u in urls_sorted:
        sid = u.get("shortId")
        if not sid:
            continue

        click_items = fetch_clicks_for_shortid(sid, start_iso, end_iso, limit=per_sid_limit)
        if not click_items:
            continue

        total_clicks_all += len(click_items)

        # 도메인 집계 (Trend 입력용)
        ou = normalize_url(u.get("originalUrl", ""))
        if ou:
            top_url_clicks[ou] += len(click_items)

        # 5분 슬롯 집계 (Insight 입력용)
        for it in click_items:
            ts = it.get("timestamp")
            if not ts:
                continue
            try:
                slot = to_5min_slot(ts)  # "HH:MM" (KST)
                time_bins[slot] += 1
            except Exception:
                pass

    # 데이터 없으면 AI 호출 스킵
    if total_clicks_all == 0 or not top_url_clicks or not time_bins:
        return {
            "aiPeriodKey": ai_period_key,
            "sourcePeriodKey": source_period_key,
            "startAt": start_iso,
            "endAt": end_iso,
            "totalClicksSourceWindow": total_clicks_all,
            "skipped": True,
            "reason": "NO_DATA",
        }

    # 4) AI 입력 Top-N 생성
    # - 도메인은 AI가 top5 뽑게 할거지만, 입력은 20개 정도면 충분
    top_urls_input = top_url_clicks.most_common(AI_TOP_URL_N)
    top_bins_input = time_bins.most_common(AI_TOP_TIMEBIN_N)     # env 기본 10

    time_click_map = {t: int(c) for t, c in time_bins.items()}

    # 5) Trend 프롬프트 (도메인TOP5 + 카테고리TOP5 분리)
    trend_payload = {
        "topUrls": [{"url": url, "clicks": clicks} for url, clicks in top_urls_input]
    }

    trend_prompt = (
    "You are a classifier. Return ONLY valid JSON. No extra text.\n"
    "Task:\n"
    "1) From each input url, extract the domain in the form like 'youtube.com' or 'notion.so'.\n"
    "2) Aggregate clicks by domain.\n"
    "3) Choose top 5 domains by total clicks.\n"
    "4) Classify EACH top domain into ONE category from this fixed set:\n"
    "[video, blog, news, shopping, social, community, docs, dev, music, other]\n"
    "5) Produce topCategories by summing clicks of domains in the same category.\n"
    "Input JSON:\n"
    f"{json.dumps(trend_payload, ensure_ascii=False)}\n\n"
    "Output JSON schema:\n"
    "{"
    "\"topDomains\":[{\"domain\":\"example.com\",\"clicks\":123,\"category\":\"video\"}],"
    "\"topCategories\":[{\"category\":\"video\",\"clicks\":186}]"
    "}\n"
    "Rules:\n"
    "- topDomains length MUST be 5 (or less if distinct domains <5).\n"
    "- topCategories length MUST be 5 (or less if distinct categories <5).\n"
    "- Sort both lists by clicks desc.\n"
    "- Use only categories from the fixed set.\n"
)


    # 6) Insight 프롬프트 (HH:MM TOP3)
    insight_payload = {
        "topTimeBins": [{"time": t, "clicks": c} for t, c in top_bins_input]
    }

    insight_prompt = (
    "You are a recommender. Return ONLY valid JSON. No extra text.\n"
    "Timezone: Asia/Seoul (KST).\n"
    "Goal: output exactly 3 best share times in HH:MM.\n"
    "Input JSON:\n"
    f"{json.dumps(insight_payload, ensure_ascii=False)}\n\n"
    "Output JSON schema (MUST follow exactly):\n"
    "{\"top3\":[{\"time\":\"HH:MM\"},{\"time\":\"HH:MM\"},{\"time\":\"HH:MM\"}]}\n"
    "Rules (MUST follow):\n"
    "- top3 MUST contain exactly 3 items.\n"
    "- All 3 times MUST be unique.\n"
    "- Prefer times from the input list.\n"
    "- If input has fewer than 3 unique times, you MUST still output 3 unique times by generating\n"
    "  additional times in 5-minute steps around the best time.\n"
)


    # 7) Bedrock 호출
    ai_output = {}
    ai_trend_obj = None
    ai_insight_obj = None

    try:
        ai_output["trend_raw"] = bedrock_invoke_text(MODEL_TREND, trend_prompt, max_tokens=260)
        ai_output["insight_raw"] = bedrock_invoke_text(MODEL_INSIGHT, insight_prompt, max_tokens=120)

        # JSON 파싱 (프론트 깨짐 방지)
        ai_trend_obj = safe_json_obj(ai_output["trend_raw"])
        ai_insight_obj = safe_json_obj(ai_output["insight_raw"])

        # ✅ insight post-process:
        # - top3 unique 보장
        # - DB 집계 clicks(time_bins/top_bins_input) 매칭해서 붙이기
        if isinstance(ai_insight_obj, dict) and isinstance(ai_insight_obj.get("top3"), list):
            uniq_times = []
            enriched = []

            for item in ai_insight_obj["top3"]:
                # item이 {"time":"HH:MM"} 또는 "HH:MM" 둘 다 방어
                if isinstance(item, dict):
                    t = str(item.get("time") or "").strip()
                else:
                    t = str(item or "").strip()

                if not t or t in uniq_times:
                    continue

                uniq_times.append(t)

                # 🔥 clicks는 AI가 아니라 DB 집계값에서 붙임
                clicks = int(time_click_map.get(t, 0))

                enriched.append({
                    "time": t,
                    "clicks": clicks,
                })

                if len(enriched) >= 3:
                    break

            ai_insight_obj["top3"] = enriched


        # 파싱 실패(raw)면 저장하지 않기
        if isinstance(ai_trend_obj, dict) and "raw" in ai_trend_obj:
            ai_trend_obj = None
        if isinstance(ai_insight_obj, dict) and "raw" in ai_insight_obj:
            ai_insight_obj = None

        # ai 테이블 누적 저장 (PK=ai_period_key)
        put_ai_result(ai_period_key, ai_trend_obj, ai_insight_obj)

    except Exception as e:
        print(json.dumps({"type": "AI_JOB_ERROR", "error": str(e)}, ensure_ascii=False))


    return {
        "aiPeriodKey": ai_period_key,
        "sourcePeriodKey": source_period_key,
        "startAt": start_iso,
        "endAt": end_iso,
        "totalClicksSourceWindow": total_clicks_all,
        "input": {
            "urlsTopN": top_urls_input[:5],
            "timeBinsTopN": top_bins_input[:5],
        },
        "output": {
            "trend": ai_trend_obj,
            "insight": ai_insight_obj,
        },
        "raw": {
            "trend": ai_output.get("trend_raw"),
            "insight": ai_output.get("insight_raw"),
        }
    }

def safe_int(x):
    try:
        return int(x)
    except Exception:
        return 0

def run_aggregation(period_key: str):
    duration = parse_period_key(period_key)
    end_dt = now_utc()
    start_dt = end_dt - duration
    start_iso = iso(start_dt)
    end_iso = iso(end_dt)

    urls = list_urls(MAX_URLS_PER_RUN)

    

    # ✅ 0) S3 Export (신규 클릭만) - 스키마 변경 없이 fact_clicks 생성
    if EXPORT_ENABLED and ANALYTICS_BUCKET and period_key == "P#1H":
        try:
            last_ts = load_export_checkpoint()
            export_start = last_ts or start_iso  # ✅ 첫 실행은 현재 집계 window만 export
            run_id = f"{iso(end_dt).replace(':','').replace('-','')}-{uuid.uuid4().hex[:8]}"

            export_records = []

            # urls는 이미 scan 결과이므로 여기서 shortId만 돌면 됨
            for u in urls:
                sid = u.get("shortId")
                if not sid:
                    continue

                # 신규 클릭만
                items = fetch_clicks_for_shortid(sid, export_start, end_iso, limit=MAX_CLICKS_PER_SID)
                if not items:
                    continue

                for it in items:
                    export_records.append(click_to_fact_record(sid, it))

            # 파일 저장(데이터 없으면 파일은 생략)
            if export_records:
                export_fact_clicks_jsonl(export_records, end_dt=end_dt, run_id=run_id)

            # ✅ 데이터 없더라도 체크포인트는 앞으로 이동(재조회 방지)
            save_export_checkpoint(end_iso)

        except Exception as e:
            # export 실패가 집계/insights 업데이트를 막지 않게
            print(json.dumps({"type": "S3_EXPORT_ERROR", "error": str(e)}, ensure_ascii=False))
    

    urls_sorted = sorted(urls, key=lambda x: safe_int(x.get("clickCount", 0)), reverse=True)

    processed = 0
    total_clicks_all = 0

    notified = 0
    alert_state = {}
    if period_key == ALERT_ONLY_PERIOD:
        try:
            alert_state = load_alert_state()
            print(json.dumps({
                "type": "ALERT_STATE_LOADED",
                "periodKey": period_key,
                "count": len(alert_state)
            }, ensure_ascii=False))
        except Exception as e:
            print(json.dumps({
                "type": "ALERT_STATE_LOAD_ERROR",
                "error": str(e)
            }, ensure_ascii=False))
            alert_state = {}
    

    for u in urls_sorted:
        sid = u.get("shortId")
        if not sid:
            continue

        click_items = fetch_clicks_for_shortid(sid, start_iso, end_iso)
        total, by_hour, by_day, by_ref, by_device = aggregate(click_items)
        suspicious_clicks = compute_suspicious(click_items)

        print(json.dumps({
            "type": "SUSP_CHECK",
            "sid": sid,
            "total": total,
            "suspicious_clicks": suspicious_clicks,
            "periodKey": period_key,
            }, ensure_ascii=False))

        # ✅ Slack alert: P#1H에서만 + suspicious 증가했을 때만
        if period_key == ALERT_ONLY_PERIOD and suspicious_clicks > 0:
            last_alerted = int(alert_state.get(sid, 0))

            print(json.dumps({
                "type": "SLACK_ALERT_CHECK",
                "sid": sid,
                "periodKey": period_key,
                "suspicious_clicks": suspicious_clicks,
                "last_alerted": last_alerted,
                "notified": notified,
                "limit": MAX_ALERTS_PER_RUN
            }, ensure_ascii=False))

            if suspicious_clicks > last_alerted:
                if notified < MAX_ALERTS_PER_RUN:
                    suspect_rate = (suspicious_clicks / total) if total else 0.0

                    print(json.dumps({
                        "type": "SLACK_ALERT_TRY",
                        "sid": sid,
                        "periodKey": period_key,
                        "suspicious_clicks": suspicious_clicks,
                        "last_alerted": last_alerted,
                        "total": total,
                        "notified_before": notified,
                    }, ensure_ascii=False))

                    start_kst = iso_to_kst_display(start_iso)
                    end_kst = iso_to_kst_display(end_iso)

                    text = (
                        f"⚠️ 비정상 클릭 감지 (증가)\n"
                        f"- shortId: `{sid}`\n"
                        f"- periodKey: {period_key}\n"
                        f"- suspiciousClicks: {suspicious_clicks} (prev: {last_alerted})\n"
                        f"- totalClicks: {total}\n"
                        f"- suspiciousRate: {suspect_rate:.0%}\n"
                        f"- window(KST): {start_kst} ~ {end_kst}"
                    )

                    ok = send_slack(text)

                    if ok:
                        # ✅ 성공했을 때만 마지막 알림값 갱신
                        alert_state[sid] = suspicious_clicks

                        # ✅ 즉시 저장 (중간 실패/타임아웃 대비)
                        try:
                            save_alert_state(alert_state)
                            print(json.dumps({
                                "type": "ALERT_STATE_SAVED_IMMEDIATE",
                                "sid": sid,
                                "periodKey": period_key,
                                "new_last_alerted": suspicious_clicks,
                                "key": ALERT_STATE_KEY
                            }, ensure_ascii=False))
                        except Exception as e:
                            print(json.dumps({
                                "type": "ALERT_STATE_SAVE_IMMEDIATE_ERROR",
                                "sid": sid,
                                "periodKey": period_key,
                                "error": str(e),
                                "key": ALERT_STATE_KEY
                            }, ensure_ascii=False))

                        print(json.dumps({
                            "type": "SLACK_ALERT_SENT",
                            "sid": sid,
                            "periodKey": period_key,
                            "new_last_alerted": suspicious_clicks,
                            "notified_before": notified,
                        }, ensure_ascii=False))
                        notified += 1
                    else:
                        print(json.dumps({
                            "type": "SLACK_ALERT_NOT_SENT",
                            "sid": sid,
                            "periodKey": period_key,
                            "notified": notified
                        }, ensure_ascii=False))
                else:
                    print(json.dumps({
                        "type": "SLACK_SKIPPED_BY_LIMIT",
                        "sid": sid,
                        "limit": MAX_ALERTS_PER_RUN,
                        "notified": notified
                    }, ensure_ascii=False))
            else:
                # ✅ 증가 안 했으면 스킵 (중복 방지 핵심)
                print(json.dumps({
                    "type": "SLACK_SKIPPED_NOT_INCREASED",
                    "sid": sid,
                    "periodKey": period_key,
                    "suspicious_clicks": suspicious_clicks,
                    "last_alerted": last_alerted
                }, ensure_ascii=False))

        print("DEBUG_AGG_RESULT", sid, period_key, total, by_hour, by_day, by_ref, by_device)

        upsert_insight(
            short_id=sid,
            period_key=period_key,
            start_at=start_iso,
            end_at=end_iso,
            total=total,
            by_hour=by_hour,
            by_day=by_day,
            by_ref=by_ref,
            by_device=by_device,
            suspicious_clicks=suspicious_clicks,
        )

        total_clicks_all += total
        processed += 1
    
        # ✅ P#1H 알림 상태 저장
    if period_key == ALERT_ONLY_PERIOD:
        try:
            save_alert_state(alert_state)
            print(json.dumps({
                "type": "ALERT_STATE_SAVED",
                "periodKey": period_key,
                "count": len(alert_state)
            }, ensure_ascii=False))
        except Exception as e:
            print(json.dumps({
                "type": "ALERT_STATE_SAVE_ERROR",
                "error": str(e)
            }, ensure_ascii=False))

    # 커스텀 메트릭(개발자 모니터링용)
    put_custom_metrics(
        namespace="UrlShortener/Analytics",
        metrics={
            "ProcessedUrls": processed,
            "TotalClicksWindow": total_clicks_all,
        },
        dims=[{"Name": "PeriodKey", "Value": period_key}],
    )

    return {
        "periodKey": period_key,
        "startAt": start_iso,
        "endAt": end_iso,
        "processedUrls": processed,
        "totalClicksWindow": total_clicks_all,
    }

def _json_default(o):
    if isinstance(o, Decimal):
        # 정수면 int로, 소수면 float로
        if o % 1 == 0:
            return int(o)
        return float(o)
    raise TypeError(f"Type not serializable: {type(o)}")

def _resp(status: int, body_obj: dict):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
        },
        "body": json.dumps(body_obj, ensure_ascii=False, default=_json_default),
    }

def _s3_get_json(bucket: str, key: str):
    try:
        resp = S3.get_object(Bucket=bucket, Key=key)
        body = resp["Body"].read().decode("utf-8")
        return json.loads(body) if body else None
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code")
        if code in ("NoSuchKey", "404"):
            return None
        print(json.dumps({"type": "S3_GET_JSON_ERROR", "bucket": bucket, "key": key, "error": str(e)}, ensure_ascii=False))
        return None


def _s3_put_json(bucket: str, key: str, obj: dict):
    S3.put_object(
        Bucket=bucket,
        Key=key,
        Body=(json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"),
        ContentType="application/json",
    )


def load_export_checkpoint() -> str | None:
    if not (ANALYTICS_BUCKET and EXPORT_CHECKPOINT_KEY):
        return None
    obj = _s3_get_json(ANALYTICS_BUCKET, EXPORT_CHECKPOINT_KEY)
    if isinstance(obj, dict):
        ts = obj.get("lastExportTs")
        if isinstance(ts, str) and ts:
            return ts
    return None


def save_export_checkpoint(ts_iso: str):
    if not (ANALYTICS_BUCKET and EXPORT_CHECKPOINT_KEY):
        return
    _s3_put_json(ANALYTICS_BUCKET, EXPORT_CHECKPOINT_KEY, {"lastExportTs": ts_iso})


def click_to_fact_record(short_id: str, it: dict) -> dict:
    ts = it.get("timestamp") or ""
    referer = it.get("referer") or "direct"
    ua = it.get("userAgent") or ""
    ip_hash = it.get("ip") or ""

    device = classify_device(ua)
    # ✅ 최소 버전: bot UA면 suspect 처리 (burst 룰까지 이벤트 단위로 찍는 건 나중에 확장 가능)
    is_suspect = bool(ua and BOT_UA_PAT.search(ua))

    return {
        "ts": ts,                 # ISO string (Z)
        "shortId": short_id,
        "referer": referer,
        "device": device,
        "isSuspect": is_suspect,
        # 선택 컬럼(있으면 6C 디버깅/필터에 도움)
        "ipHash": ip_hash,
        "userAgent": ua,
    }


def export_fact_clicks_jsonl(records: list[dict], end_dt: datetime, run_id: str):
    """
    S3에 JSON Lines로 저장:
    s3://{bucket}/{prefix}/fact_clicks/dt=YYYY-MM-DD/hr=HH/run_id.jsonl
    """
    if not (ANALYTICS_BUCKET and ANALYTICS_PREFIX):
        return

    dt = end_dt.strftime("%Y-%m-%d")
    hr = end_dt.strftime("%H")

    key = f"{ANALYTICS_PREFIX}/fact_clicks/dt={dt}/hr={hr}/{run_id}.jsonl"
    body = "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n"

    S3.put_object(
        Bucket=ANALYTICS_BUCKET,
        Key=key,
        Body=body.encode("utf-8"),
        ContentType="application/x-ndjson",
    )

    print(json.dumps({
        "type": "S3_EXPORT_OK",
        "bucket": ANALYTICS_BUCKET,
        "key": key,
        "records": len(records),
    }, ensure_ascii=False))


def send_slack(text: str) -> bool:
    webhook_url = os.getenv("SLACK_WEBHOOK_URL", "").strip()

    print(json.dumps({
        "type": "SLACK_FUNC_ENTER",
        "has_webhook": bool(webhook_url),
        "text_preview": text[:80]
    }, ensure_ascii=False))

    if not webhook_url:
        print(json.dumps({"type": "SLACK_SKIP_NO_WEBHOOK"}, ensure_ascii=False))
        return False

    req = urllib.request.Request(
        webhook_url,
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            body = resp.read().decode("utf-8", errors="ignore")
            print(json.dumps({
                "type": "SLACK_HTTP_OK",
                "status": status,
                "body_preview": body[:200]
            }, ensure_ascii=False))
            return True

    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        print(json.dumps({
            "type": "SLACK_HTTP_ERROR",
            "status": e.code,
            "reason": str(e.reason),
            "body": err_body[:500]
        }, ensure_ascii=False))
        return False

    except Exception as e:
        print(json.dumps({
            "type": "SLACK_SEND_EXCEPTION",
            "error": str(e)
        }, ensure_ascii=False))
        return False

def iso_to_kst_display(ts_iso: str) -> str:
    """
    '2026-02-23T14:22:48Z' -> '2026-02-23 23:22:48 KST'
    """
    if not ts_iso:
        return "-"
    try:
        dt_utc = datetime.strptime(ts_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        dt_kst = dt_utc.astimezone(KST)
        return dt_kst.strftime("%Y-%m-%d %H:%M:%S KST")
    except Exception:
        return ts_iso
    

def load_alert_state() -> dict:
    """
    shortId별 마지막 알림 suspiciousClicks 저장값 로드
    예: {"abc123": 2, "def456": 5}
    """
    if not (ANALYTICS_BUCKET and ALERT_STATE_KEY):
        return {}

    obj = _s3_get_json(ANALYTICS_BUCKET, ALERT_STATE_KEY)
    if isinstance(obj, dict):
        # 값 정리 (숫자 아닌 값 방어)
        cleaned = {}
        for k, v in obj.items():
            try:
                cleaned[str(k)] = int(v)
            except Exception:
                continue
        return cleaned
    return {}


def save_alert_state(state: dict):
    if not (ANALYTICS_BUCKET and ALERT_STATE_KEY):
        return
    _s3_put_json(ANALYTICS_BUCKET, ALERT_STATE_KEY, state)