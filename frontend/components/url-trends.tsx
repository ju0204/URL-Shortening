"use client"

import { useEffect, useMemo, useState } from "react"
import { Globe, TrendingUp } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { fetchAiLatest, type AiLatestResponse } from "@/lib/api"

function formatNumber(num: number): string {
  if (num >= 1000) return `${(num / 1000).toFixed(1)}K`
  return num.toString()
}

function toPercentage(value: number, total: number) {
  if (!total) return 0
  return Math.round((value / total) * 100)
}

export function UrlTrends() {
  console.log("[UrlTrends] render")
  const [ai, setAi] = useState<AiLatestResponse | null>(null)
  const [error, setError] = useState("")

  useEffect(() => {
    console.log("[UrlTrends] fetching /ai/latest...")
    fetchAiLatest("P#30MIN")
      .then((data) => {
        console.log("[UrlTrends] ai/latest:", data) 
        setAi(data)
      })
      .catch((e) => setError(e?.message || "불러오기 실패"))
  }, [])

  const { domains, categories } = useMemo(() => {
    const trend = (ai?.found ? (ai.aiTrend as any) : null) ?? null
    const topDomains: any[] = trend?.topDomains ?? []
    const topCategories: any[] = trend?.topCategories ?? []

    // 도메인 총합(퍼센트/프로그레스 계산용)
    const totalDomainClicks = topDomains.reduce((sum, d) => sum + (Number(d?.clicks) || 0), 0)

    const domains = topDomains.map((d) => {
      const clicks = Number(d?.clicks) || 0
      return {
        domain: String(d?.domain ?? ""),
        count: clicks,
        percentage: toPercentage(clicks, totalDomainClicks),
        category: String(d?.category ?? "other"),
      }
    })

    // 카테고리 카드용 (count는 "xxK" 문자열로 보여주던 스타일 유지)
    const categories = topCategories.map((c) => {
      const clicks = Number(c?.clicks) || 0
      return {
        name: String(c?.category ?? "other"),
        count: formatNumber(clicks),
        icon: "•", // 아이콘/색상은 아래에서 매핑
      }
    })

    return { domains, categories }
  }, [ai])

  // 카테고리별 아이콘/색상 매핑 (네 UI 유지)
  const categoryStyle = (name: string) => {
    switch (name) {
      case "video":
      case "동영상":
        return { icon: "▶", color: "bg-chart-1 text-primary-foreground", label: "동영상" }
      case "blog":
      case "블로그":
        return { icon: "✎", color: "bg-chart-2 text-primary-foreground", label: "블로그" }
      case "dev":
      case "개발":
        return { icon: "</>", color: "bg-chart-3 text-primary-foreground", label: "개발" }
      case "social":
      case "SNS":
        return { icon: "@", color: "bg-chart-4 text-primary-foreground", label: "SNS" }
      case "docs":
      case "생산성":
        return { icon: "⚡", color: "bg-chart-5 text-primary-foreground", label: "생산성" }
      case "design":
      case "디자인":
        return { icon: "◇", color: "bg-muted-foreground text-card", label: "디자인" }
      default:
        return { icon: "•", color: "bg-secondary text-secondary-foreground", label: name }
    }
  }

  return (
    <section className="px-4 py-12 md:py-16">
      <div className="mx-auto max-w-5xl">
        <div className="mb-8 flex flex-col items-center gap-2 text-center">
          <div className="flex items-center gap-2 rounded-full border border-border bg-card px-4 py-1.5">
            <TrendingUp className="h-4 w-4 text-primary" />
            <span className="text-sm font-medium text-foreground">URL Trends</span>
          </div>
          <h2 className="text-balance text-2xl font-bold tracking-tight text-foreground md:text-3xl">
            인기 URL 트렌드
          </h2>
          <p className="max-w-md text-pretty text-muted-foreground">
            가장 많이 단축되는 도메인과 카테고리를 확인하세요
          </p>

          {/* 상태 표시(선택) */}
          {error && <p className="text-sm text-red-500">{error}</p>}
          
        </div>

        <div className="grid gap-6 md:grid-cols-2">
          {/* Popular Domains */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-lg">
                <Globe className="h-5 w-5 text-primary" />
                인기 도메인
              </CardTitle>
              <CardDescription>어떤 도메인이 인기일까요?</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="flex flex-col gap-4">
                {(domains.length ? domains : []).map((item, index) => (
                  <div key={item.domain || index} className="flex flex-col gap-1.5">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-3">
                        <span className="flex h-6 w-6 items-center justify-center rounded-md bg-secondary text-xs font-semibold text-secondary-foreground">
                          {index + 1}
                        </span>
                        <span className="font-mono text-sm font-medium text-foreground">
                          {item.domain}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge variant="secondary" className="text-xs font-normal">
                          {item.category}
                        </Badge>
                        <span className="text-xs tabular-nums text-muted-foreground">
                          {formatNumber(item.count)}
                        </span>
                      </div>
                    </div>
                    <Progress value={item.percentage} className="h-1.5" />
                  </div>
                ))}

                {!error && !domains.length && (
                  <p className="text-sm text-muted-foreground">데이터가 아직 없어요.</p>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Categories */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-lg">
                <TrendingUp className="h-5 w-5 text-primary" />
                카테고리별 분포
              </CardTitle>
              <CardDescription>어떤 종류의 링크가 가장 많을까요?</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-3">
                {(categories.length ? categories : []).map((cat) => {
                  const s = categoryStyle(cat.name)
                  return (
                    <div
                      key={cat.name}
                      className="flex items-center gap-3 rounded-lg border border-border bg-card p-3 transition-colors hover:bg-secondary/50"
                    >
                      <div
                        className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-sm font-bold ${s.color}`}
                      >
                        {s.icon}
                      </div>
                      <div className="min-w-0">
                        <p className="text-sm font-semibold text-foreground">{s.label}</p>
                        <p className="text-xs text-muted-foreground">{cat.count} links</p>
                      </div>
                    </div>
                  )
                })}

                {!error && !categories.length && (
                  <p className="text-sm text-muted-foreground col-span-2">데이터가 아직 없어요.</p>
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </section>
  )
}
