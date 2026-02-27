import json
import os
import urllib.request
from datetime import datetime, timezone, timedelta

import boto3


SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]  # AI 요약 전용 채널 Webhook
BEDROCK_MODEL_ID = os.environ["BEDROCK_MODEL_ID"]    # 루트 main.tf에서 주입 권장


# 기본값: ALARM일 때만 AI 요약
AI_ON_STATES = set(s.strip() for s in os.environ.get("AI_ON_STATES", "ALARM").split(",") if s.strip())
SEND_OK_SIMPLE = os.environ.get("SEND_OK_SIMPLE", "true").lower() == "true"
BEDROCK_REGION = os.getenv("BEDROCK_REGION", os.getenv("AWS_REGION", "ap-northeast-2"))

KST = timezone(timedelta(hours=9))

bedrock = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)


def post_to_slack(text: str):
    payload = {"text": text}
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        SLACK_WEBHOOK_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=5) as resp:
        body = resp.read().decode("utf-8")
        return resp.status, body


def to_kst_str(dt_str: str) -> str:
    """
    CloudWatch Alarm timestamp string -> KST string
    입력 예시:
      - 2026-02-24T12:38:41.731+0000
      - 2026-02-24T12:38:41.731Z
      - 2026-02-24T12:38:41+00:00
    """
    if not dt_str:
        return "-"

    s = dt_str.strip()

    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    if len(s) >= 5 and (s[-5] in ["+", "-"]) and s[-3] != ":":
        s = s[:-2] + ":" + s[-2:]

    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_kst = dt.astimezone(KST)
        return dt_kst.strftime("%Y-%m-%d %H:%M:%S KST")
    except Exception:
        return dt_str


def safe_trim(text: str, limit: int = 3000) -> str:
    if not text:
        return ""
    return text if len(text) <= limit else text[:limit] + "...(truncated)"


def build_summary_prompt(alarm_name, state, reason, region, changed_at_kst, raw_msg):
    """
    Slack용 짧은 운영 요약 프롬프트 (한국어)
    """
    raw_json = safe_trim(json.dumps(raw_msg, ensure_ascii=False), 3000)

    return f"""
너는 AWS 운영 알림 요약 도우미다.
CloudWatch Alarm 이벤트를 보고 Slack에 보낼 한국어 운영 요약을 작성하라.

규칙:
- 한국어로 작성
- 추정 내용은 반드시 '(추정)' 표시
- 과장 금지, 입력 정보 범위 내에서만 요약
- 최대 8줄 이내
- 불필요한 서론/인사 금지
- 각 줄은 반드시 '1) ', '2) ', '3) ', '4) '로 시작
- 출력 형식 고정(각 줄 시작 문자까지 반드시 동일하게)::
1) 요약: 1~2줄
2) 영향: 1~2줄
3) 원인: 1~2줄 (추정이면 (추정)표시)
4) 확인: 확인 항목 2~3개를 '/'로 구분 (예: API Gateway 로그 / Lambda 로그 / 최근 배포 변경사항)
- 문장 끝에 '...' 사용 금지

입력:
- AlarmName: {alarm_name}
- State: {state}
- Region: {region}
- Time(KST): {changed_at_kst}

원본 이벤트(JSON 일부):
{raw_json}
""".strip()


def invoke_bedrock(prompt: str) -> str:
    """
    Amazon Nova 계열용 Bedrock InvokeModel 형식 (간단 텍스트 생성)
    예시 모델:
      - apac.amazon.nova-lite-v1:0
      - apac.amazon.nova-micro-v1:0
    """
    body = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"text": prompt}
                ]
            }
        ],
        "inferenceConfig": {
            "max_new_tokens": 300,
            "temperature": 0.2
        }
    }

    resp = bedrock.invoke_model(
        modelId=BEDROCK_MODEL_ID,
        body=json.dumps(body).encode("utf-8"),
        contentType="application/json",
        accept="application/json",
    )

    payload = json.loads(resp["body"].read())

    # Nova 응답 파싱 (텍스트 추출)
    # 모델/버전에 따라 구조가 조금 다를 수 있어 fallback 포함
    texts = []

    # 패턴 1: output.message.content[]
    output = payload.get("output", {})
    message = output.get("message", {})
    for item in message.get("content", []):
        if isinstance(item, dict):
            t = item.get("text", "")
            if t:
                texts.append(t)

    # 패턴 2: results[0].outputText
    if not texts:
        for r in payload.get("results", []):
            t = r.get("outputText", "")
            if t:
                texts.append(t)

    # 패턴 3: generation / text (fallback)
    if not texts:
        for key in ("generation", "text", "outputText"):
            t = payload.get(key)
            if isinstance(t, str) and t.strip():
                texts.append(t.strip())

    result = "\n".join(texts).strip()
    return result or f"(AI 요약 결과 없음) payload_keys={list(payload.keys())}"


def build_simple_recovery_text(alarm_name, state, region, changed_at_kst, reason):
    return (
        f"✅ *CloudWatch Alarm Recovery (AI 채널)*\n"
        f"• Alarm: `{alarm_name}`\n"
        f"• State: *{state}*\n"
        f"• Region: `{region}`\n"
        f"• Time: `{changed_at_kst}`\n"
        f"• Reason: {safe_trim(reason, 1200)}"
    )


def build_ai_summary_text(alarm_name, state, region, changed_at_kst, summary):
    return (
        f"🤖 *AI Alarm Summary*\n"
        f"• Alarm: `{alarm_name}`\n"
        f"• State: *{state}*\n"
        f"• Region: `{region}`\n"
        f"• Time: `{changed_at_kst}`\n"
        f"{safe_trim(summary, 2500)}"
    )


def build_fallback_text(alarm_name, state, region, changed_at_kst, reason, error_msg):
    return (
        f"⚠️ *AI Alarm Summary (fallback)*\n"
        f"• Alarm: `{alarm_name}`\n"
        f"• State: *{state}*\n"
        f"• Region: `{region}`\n"
        f"• Time: `{changed_at_kst}`\n"
        f"• AI 요약 실패: `{safe_trim(error_msg, 300)}`\n"
        f"• Reason: {safe_trim(reason, 1200)}"
    )


def lambda_handler(event, context):
    records = event.get("Records", [])
    if not records:
        return {"statusCode": 200, "body": "No records"}

    for record in records:
        if record.get("EventSource") != "aws:sns":
            continue

        sns = record.get("Sns", {})
        subject = sns.get("Subject", "(no-subject)")
        message_str = sns.get("Message", "")

        try:
            msg = json.loads(message_str)
        except json.JSONDecodeError:
            msg = None

        # CloudWatch Alarm 형식이 아니면 pass-through (원하면 skip 가능)
        if not msg or "AlarmName" not in msg:
            text = (
                f"ℹ️ *AI Summary Channel (pass-through)*\n"
                f"• Subject: {subject}\n"
                f"• Message: {safe_trim(message_str, 1200)}"
            )
            status, body = post_to_slack(text)
            if status >= 300:
                raise RuntimeError(f"Slack webhook error: {status} {body}")
            continue

        alarm_name = msg.get("AlarmName", "(unknown)")
        state = msg.get("NewStateValue", "(unknown)")
        reason = msg.get("NewStateReason", "")
        region = msg.get("Region", "")
        changed_at = msg.get("StateChangeTime")
        changed_at_kst = to_kst_str(changed_at)

        # AI 요약 대상 상태가 아니면(기본: ALARM만)
        if state not in AI_ON_STATES:
            if SEND_OK_SIMPLE and state == "OK":
                text = build_simple_recovery_text(alarm_name, state, region, changed_at_kst, reason)
                status, body = post_to_slack(text)
                if status >= 300:
                    raise RuntimeError(f"Slack webhook error: {status} {body}")
            continue

        # AI 요약 생성 + 전송
        try:
            prompt = build_summary_prompt(
                alarm_name=alarm_name,
                state=state,
                reason=reason,
                region=region,
                changed_at_kst=changed_at_kst,
                raw_msg=msg,
            )
            summary = invoke_bedrock(prompt)
            summary = normalize_summary_format(summary)  # 이거 쓰면
            text = build_ai_summary_text(alarm_name, state, region, changed_at_kst, summary)
        except Exception as e:
            text = build_fallback_text(alarm_name, state, region, changed_at_kst, reason, str(e))

        status, body = post_to_slack(text)
        if status >= 300:
            raise RuntimeError(f"Slack webhook error: {status} {body}")

    return {"statusCode": 200, "body": "ok"}

def normalize_summary_format(summary: str) -> str:
    """
    모델이 번호/형식을 흐트러뜨려도 최소한 1)~4) 형태로 맞춰준다.
    """
    if not summary:
        return (
            "1) 요약: 요약 생성 실패\n"
            "2) 영향: 확인 필요\n"
            "3) 원인: 확인 필요 (추정)\n"
            "4) 확인: API Gateway 로그 / Lambda 로그 / 최근 배포 변경사항"
        )

    lines = [line.strip() for line in summary.splitlines() if line.strip()]

    # 이미 1)~4)로 잘 왔으면 그대로
    if len(lines) >= 4 and all(lines[i].startswith(f"{i+1})") for i in range(4)):
        return "\n".join(lines[:4])

    # 번호 없으면 강제로 붙이기 (최대 4줄)
    normalized = []
    for i, line in enumerate(lines[:4], start=1):
        # "요약:", "영향:" 같은 접두만 오면 번호 붙임
        if line.startswith(f"{i})"):
            normalized.append(line)
        else:
            normalized.append(f"{i}) {line}")

    # 부족하면 기본값 채우기
    defaults = [
        "1) 요약: CloudWatch 알람이 발생했습니다.",
        "2) 영향: 서비스 영향 여부 확인이 필요합니다.",
        "3) 원인: 메트릭 임계치 초과로 추정됩니다. (추정)",
        "4) 확인: API Gateway 로그 / Lambda 로그 / 최근 배포 변경사항",
    ]
    while len(normalized) < 4:
        normalized.append(defaults[len(normalized)])

    return "\n".join(normalized[:4])