"use client"

import { useEffect, useMemo, useState } from "react"
import { Clock, Share2 } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart"
import { Bar, BarChart, XAxis, YAxis, ResponsiveContainer, Cell } from "recharts"
import { fetchAiLatest, type AiLatestResponse } from "@/lib/api"

// 지금 코드에 이미 색을 직접 지정해둔 상태라 유지
const PRIMARY_COLOR = "hsl(220, 72%, 50%)"
const PRIMARY_LIGHT = "hsl(220, 72%, 78%)"

function formatRangeMessage(top3: string[]) {
  if (!top3?.length) return null
  const sorted = [...top3].sort()
  if (sorted.length === 1) return `${sorted[0]} 전후`
  return `${sorted[0]}~${sorted[sorted.length - 1]} 사이`
}

export function ShareTiming() {
  const [ai, setAi] = useState<AiLatestResponse | null>(null)
  const [error, setError] = useState("")

  useEffect(() => {
    fetchAiLatest("P#30MIN")
      .then((data) => setAi(data))
      .catch((e) => setError(e?.message || "불러오기 실패"))
  }, [])

  // ✅ API 응답에서 차트 데이터 추출
  // ai.aiInsight.chart.timeBins: [{time:"00", clicks:0}, ...]
  const chartData = useMemo(() => {
    if (!ai?.found) return []
    const insight: any = ai.aiInsight
    const bins = insight?.chart?.timeBins

    if (!Array.isArray(bins)) return []

    // Recharts용으로 time 라벨을 "00시"로 만들어주고 정렬 보장
    return bins
      .map((b: any) => {
        const hh = String(b?.time ?? "").padStart(2, "0")
        const clicks = Number(b?.clicks ?? 0)
        return {
          time: `${hh}시`,
          hour: hh, // tooltip 등에서 쓰고 싶으면
          clicks: Number.isFinite(clicks) ? clicks : 0,
        }
      })
      .sort((a, b) => a.hour.localeCompare(b.hour))
  }, [ai])

  const maxClicks = useMemo(() => {
    if (!chartData.length) return 1
    return Math.max(1, ...chartData.map((d) => d.clicks))
  }, [chartData])

  function getBarColor(clicks: number): string {
    const ratio = clicks / maxClicks
    if (ratio >= 0.85) return PRIMARY_COLOR
    if (ratio >= 0.6) return "hsl(220, 60%, 60%)"
    return PRIMARY_LIGHT
  }

  // ✅ 추천 top3: ai.aiInsight.recommendation.top3
  const top3: string[] = useMemo(() => {
    if (!ai?.found) return []
    const insight: any = ai.aiInsight
    const arr = insight?.recommendation?.top3
    return Array.isArray(arr) ? arr.filter(Boolean).slice(0, 3) : []
  }, [ai])

  const bestTimes = useMemo(() => {
    return top3.map((t, idx) => ({
      time: t,
      reason: idx === 0 ? "1순위 추천" : idx === 1 ? "2순위 추천" : "3순위 추천",
    }))
  }, [top3])

  const rangeMsg = useMemo(() => formatRangeMessage(top3), [top3])

  return (
    <section className="px-4 py-12 md:py-16">
      <div className="mx-auto max-w-5xl">
        <div className="mb-8 flex flex-col items-center gap-2 text-center">
          <div className="flex items-center gap-2 rounded-full border border-border bg-card px-4 py-1.5">
            <Share2 className="h-4 w-4 text-primary" />
            <span className="text-sm font-medium text-foreground">Best Time to Share</span>
          </div>
          <h2 className="text-balance text-2xl font-bold tracking-tight text-foreground md:text-3xl">
            최적의 공유 시간대
          </h2>
          <p className="max-w-md text-pretty text-muted-foreground">
            링크를 공유하기 가장 좋은 시간을 확인하세요
          </p>

          {error && <p className="text-sm text-red-500">{error}</p>}
          
        </div>

        <div className="grid gap-6 md:grid-cols-3">
          {/* Chart */}
          <Card className="md:col-span-2">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-lg">
                <Clock className="h-5 w-5 text-primary" />
                시간대별 클릭 추이
              </CardTitle>
              <CardDescription>최근 24시간 기준 시간대별 클릭수 합산</CardDescription>
            </CardHeader>
            <CardContent>
              <ChartContainer
                config={{
                  clicks: { label: "클릭수", color: PRIMARY_COLOR },
                }}
                className="h-[280px]"
              >
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} margin={{ top: 5, right: 5, left: -20, bottom: 0 }}>
                    <XAxis dataKey="time" tickLine={false} axisLine={false} fontSize={11} interval={2} />
                    <YAxis tickLine={false} axisLine={false} fontSize={11} />
                    <ChartTooltip content={<ChartTooltipContent />} />
                    <Bar dataKey="clicks" radius={[4, 4, 0, 0]} name="클릭수">
                      {chartData.map((entry) => (
                        <Cell key={entry.time} fill={getBarColor(entry.clicks)} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </ChartContainer>

              {!error && ai?.found && !chartData.length && (
                <div className="mt-3 rounded-lg bg-secondary/50 p-3">
                  <p className="text-xs leading-relaxed text-muted-foreground">
                    아직 차트 데이터가 없어요. 클릭 데이터가 더 쌓이면 표시됩니다.
                  </p>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Best Times Sidebar */}
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">추천 시간대</CardTitle>
              <CardDescription>AI가 추천한 공유 시간</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex flex-col gap-4">
                {bestTimes.map((item, index) => (
                  <div
                    key={item.time}
                    className="flex items-center gap-3 rounded-lg border border-border p-3"
                  >
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary text-sm font-bold text-primary-foreground">
                      {index + 1}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="font-mono text-lg font-bold text-foreground">{item.time}</p>
                      <p className="text-xs text-muted-foreground">{item.reason}</p>
                    </div>
                    <div className="text-right">
                      <p className="font-mono text-sm font-semibold text-primary">추천</p>
                      <p className="text-xs text-muted-foreground">time</p>
                    </div>
                  </div>
                ))}

                {!error && !bestTimes.length && (
                  <div className="rounded-lg bg-secondary/50 p-3">
                    <p className="text-xs leading-relaxed text-muted-foreground">
                      아직 추천 시간이 없어요. 클릭 데이터가 더 쌓이면 생성됩니다.
                    </p>
                  </div>
                )}

                {!!bestTimes.length && (
                  <div className="rounded-lg bg-secondary/50 p-3">
                    <p className="text-xs leading-relaxed text-muted-foreground">
                      {rangeMsg ? (
                        <>
                          <span className="font-semibold text-primary">{rangeMsg}</span>에 공유하면
                          효과가 좋을 가능성이 높아요.
                        </>
                      ) : (
                        <>추천 시간대에 공유하면 효과가 좋을 가능성이 높아요.</>
                      )}
                    </p>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </section>
  )
}
