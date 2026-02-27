// lib/api.ts
const API_BASE_URL = (process.env.NEXT_PUBLIC_API_GATEWAY_URL || "").replace(/\/$/, "")

export interface ShortenResponse {
  shortUrl: string
  shortId: string
  title?: string
  originalUrl?: string
}

/** URL 단축 요청 */
export async function shortenUrl(originalUrl: string): Promise<ShortenResponse> {
  if (!API_BASE_URL) throw new Error("API URL이 설정되지 않았습니다.")

  const res = await fetch(`${API_BASE_URL}/shorten`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url: originalUrl }),
  })

  const data = await res.json().catch(() => ({}))

  if (!res.ok) {
    // 너 Lambda는 { error: "..." } 형태도 쓰고 있어서 둘 다 커버
    throw new Error(data.error || data.message || "URL 단축에 실패했습니다.")
  }

  return data as ShortenResponse
}

/**
 * 아래 2개는 아직 백엔드 엔드포인트(/trends, /share-timing)가 없으면
 * 호출 시 무조건 실패하니, 구현 전까지는 주석 처리하거나
 * 나중에 stats/analyze 만들고 붙이는 걸 추천.
 */
// export async function fetchTrends() { ... }
// export async function fetchShareTiming() { ... }

export type PeriodKey = "P#1MIN" | "P#30MIN" | "P#1H" | "P#24H" | "P#7D"

export interface AiLatestResponse {
  found: boolean
  periodKey: PeriodKey | string
  aiGeneratedAt?: string
  aiTrend?: unknown
  aiInsight?: unknown
  message?: string
  allowed?: string[]
}

/** AI 최신 결과 조회 */
export async function fetchAiLatest(periodKey: PeriodKey = "P#30MIN"): Promise<AiLatestResponse> {
  if (!API_BASE_URL) throw new Error("API URL이 설정되지 않았습니다.")

  // P#30MIN 같은 값에 #가 들어가서 반드시 인코딩 필요
  const qs = new URLSearchParams({ periodKey }).toString()

  const res = await fetch(`${API_BASE_URL}/ai/latest?${qs}`, {
    method: "GET",
    headers: { "Content-Type": "application/json" },
    // 최신값 바로 보고 싶으면(선택)
    cache: "no-store",
  })

  const data = await res.json().catch(() => ({}))

  console.log("[fetchAiLatest]", { url: `${API_BASE_URL}/ai/latest?${qs}`, status: res.status, data })


  if (!res.ok) {
    throw new Error(data.error || data.message || `AI 최신 조회 실패 (HTTP ${res.status})`)
  }

  return data as AiLatestResponse
}