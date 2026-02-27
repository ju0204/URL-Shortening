# Shortify

- **GitHub:** https://github.com/ju0204/URL-Shortening  
- **Service URL:** https://shortify.cloud/  
- **API Base URL:** https://api.shortify.cloud  

> AWS 서버리스(Lambda, API Gateway, DynamoDB) 기반 URL 단축 서비스.  
> 리다이렉트 클릭을 수집/집계하고, AI로 트렌드·인사이트를 생성해 제공합니다.

---

## 1) 서비스 소개

Shortify는 긴 URL을 짧은 코드로 변환하고, 접속 시 원본 URL로 리다이렉트합니다.  
리다이렉트에서 발생한 클릭만 집계 대상으로 기록하며, 클릭 데이터를 기반으로 통계 리포트와 AI 트렌드/인사이트를 제공합니다.

- URL 단축 생성 / 리다이렉트
- 클릭 로깅 및 통계(시간대/요일/유입경로/디바이스)
- 비정상(의심) 클릭 탐지 + Slack 알림
- 배치 집계(EventBridge) + 분석(Athena/Grafana)
- AI 분석(Bedrock) 결과 제공

---

## 2) 핵심 기능

### URL 단축 생성
- `POST /shorten` → `shortId` 생성(Base62 랜덤) → DynamoDB 저장(조건부 Put로 충돌 방지) → `{ shortId, shortUrl }`

### 리다이렉트 + 클릭 로깅
- `GET /{shortId}` → 원본 URL 조회 → `301/302 Redirect`
- **클릭 집계 기준:** 리다이렉트가 발생한 이벤트만 클릭으로 인정 (**copy 버튼은 미집계**)
- 클릭 저장 필드: `timestamp`, `ipHash`, `userAgent`, `referer`

### 통계 조회(집계 결과)
- `GET /stats/{shortId}?periodKey=...` → DynamoDB `insights` 조회
- 제공: `totalClicks`, `clicksByHour`, `clicksByDay`, `clicksByReferer(Top N)`, `peakHour`, `topReferer`, `suspiciousClicks`, `suspiciousRate`

### 배치 집계/AI 분석(EventBridge)
- 주기 실행으로 `analyze` Lambda 호출 → 집계(insights 갱신) + AI 결과(ai 저장) 생성

### URL 만료(TTL)
- `urls.expiresAt` TTL 적용으로 일정 시간 후 자동 만료/삭제

---

## 3) Tech Stack (요약)

| Category | Tech | Why |
| --- | --- | --- |
| Serverless Backend | AWS Lambda, API Gateway | 핵심 비즈니스 로직 실행 + REST 엔드포인트 제공 |
| Data | DynamoDB | URL/클릭/집계/AI 결과 저장 및 저지연 조회 |
| Scheduler | EventBridge | 5분/30분/24시간 주기 배치 실행 |
| Analytics | S3, Glue, Athena | 클릭 데이터 Export → SQL 분석 → 대시보드 쿼리 |
| Observability | CloudWatch, X-Ray | 지표/로그/알람 + 트레이싱(병목 분석) |
| Dashboard | Grafana | Athena/CloudWatch 기반 운영·분석 시각화 |
| Frontend Quality | Sentry(Frontend) | 프론트 에러/성능/사용자 영향도 추적 |
| AI | Amazon Bedrock | 트렌드/인사이트 생성(분석 파이프라인 연결) |
| Infra | Terraform | 인프라 IaC로 반복 가능한 배포 |
| Frontend | Next.js, CloudFront | 정적 배포 + CDN 캐싱/HTTPS |
| Alerts | SNS + Slack/Discord Webhook | 장애/이상징후 알림 수신 |

---

## 4) Architecture

> 📌 **아키텍처 다이어그램 이미지 필요**  
> - API Gateway ↔ Lambda(Shorten/Redirect/Stats/Analyze) ↔ DynamoDB  
> - EventBridge → Analyze Lambda  
> - Analyze → S3 Export → Glue/Athena → Grafana  
> - CloudWatch Alarms → SNS → Slack 알림 Lambda → Slack  
> - X-Ray 트레이싱, Sentry(Frontend)

- **[IMAGE]** `docs/architecture.png` (전체 아키텍처)

---

## 5) API Endpoints

| Method | Endpoint | Description |
| --- | --- | --- |
| POST | `/shorten` | URL 단축 생성 (`{ url, title? }` → `{ shortId, shortUrl }`) |
| GET | `/{shortId}` | 리다이렉트 + 클릭 로깅 (`301/302 Redirect`) |
| GET | `/stats/{shortId}` | 클릭 통계 조회(집계 결과) |
| GET | `/ai/latest` | AI 분석 최신 1건 조회 (Query: `periodKey`, default `P#30MIN`) |

### Example
```bash
curl -X POST "https://api.shortify.cloud/shorten" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","title":"example"}'
