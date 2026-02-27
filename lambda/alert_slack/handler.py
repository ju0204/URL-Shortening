import json
import os
import urllib.request
from datetime import datetime, timezone, timedelta


SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]
KST = timezone(timedelta(hours=9))

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

        alarm_name = None
        state = None
        reason = None
        region = None
        changed_at = None

        try:
            msg = json.loads(message_str)
            alarm_name = msg.get("AlarmName")
            state = msg.get("NewStateValue")
            reason = msg.get("NewStateReason")
            region = msg.get("Region")
            changed_at = msg.get("StateChangeTime")
        except json.JSONDecodeError:
            msg = None

        if alarm_name:
            changed_at_kst = to_kst_str(changed_at)   # ✅ 추가

            emoji = "🚨" if state == "ALARM" else "✅" if state == "OK" else "ℹ️"
            text = (
                f"{emoji} *CloudWatch Alarm*\n"
                f"• Alarm: `{alarm_name}`\n"
                f"• State: *{state}*\n"
                f"• Region: `{region}`\n"
                f"• Time: `{changed_at_kst}`\n"      # ✅ changed_at -> changed_at_kst
                f"• Reason: {reason}"
            )
        else:
            text = (
                f"ℹ️ *SNS Notification*\n"
                f"• Subject: {subject}\n"
                f"• Message: {message_str[:1500]}"
            )

        status, body = post_to_slack(text)
        if status >= 300:
            raise RuntimeError(f"Slack webhook error: {status} {body}")

    return {"statusCode": 200, "body": "ok"}

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

    # Z 형태 처리
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    # +0000 형태를 +00:00 형태로 보정
    # ex) 2026-02-24T12:38:41.731+0000 -> ...+00:00
    if len(s) >= 5 and (s[-5] in ["+", "-"]) and s[-3] != ":":
        s = s[:-2] + ":" + s[-2:]

    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt_kst = dt.astimezone(KST)
        return dt_kst.strftime("%Y-%m-%d %H:%M:%S KST")
    except Exception:
        # 파싱 실패 시 원문 반환
        return dt_str