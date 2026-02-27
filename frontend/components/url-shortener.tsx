"use client"

import React from "react"

import { useState, useCallback } from "react"
import { Link, ArrowRight, Copy, ExternalLink, RotateCcw, Check, Loader2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"
import { shortenUrl } from "@/lib/api"

const API_CONFIGURED = !!process.env.NEXT_PUBLIC_API_GATEWAY_URL

/** API 미연결 시 로컬 데모용 폴백 */
function generateDemoShortUrl(): string {
  const chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
  let code = ""
  for (let i = 0; i < 7; i++) {
    code += chars.charAt(Math.floor(Math.random() * chars.length))
  }
  return `https://shortify.cloud/${code}`
}

export function UrlShortener() {
  const [url, setUrl] = useState("")
  const [shortenedUrl, setShortenedUrl] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [isCopied, setIsCopied] = useState(false)
  const [error, setError] = useState("")
  const [shortId, setShortId] = useState("")


  const isValidUrl = useCallback((urlString: string) => {
    try {
      const parsed = new URL(urlString)
      return parsed.protocol === "http:" || parsed.protocol === "https:"
    } catch {
      return false
    }
  }, [])

  const handleShorten = useCallback(async () => {
    console.log("[SHORTEN] clicked") 
    console.log("[SHORTEN] API_CONFIGURED =", API_CONFIGURED)
    console.log("[SHORTEN] GW_URL =", process.env.NEXT_PUBLIC_API_GATEWAY_URL)
    setError("")

    if (!url.trim()) {
      setError("URL을 입력해주세요.")
      return
    }

    if (!isValidUrl(url.trim())) {
      setError("올바른 URL 형식이 아닙니다.")
      return
    }

    setIsLoading(true)
    try {
      if (API_CONFIGURED) {
        const inputUrl = url.trim()
  

  const result = await shortenUrl(inputUrl)

  console.log("[SHORTEN] shortId JSON =", JSON.stringify(result?.shortId))
  
  const id = String(result.shortId).trim()

  setShortId(id)

  const base = process.env.NEXT_PUBLIC_API_GATEWAY_URL!.replace(/\/$/, "")
  const redirectUrl = `${base}/${encodeURIComponent(id)}`
  console.log("[SHORTEN] redirectUrl =", redirectUrl)
  setShortenedUrl(redirectUrl)
      } else {
        // API 미연결 시 데모 모드
        await new Promise((resolve) => setTimeout(resolve, 600))
        setShortenedUrl(generateDemoShortUrl())
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)

      if (msg.toLowerCase().includes("failed to fetch")) {
        setError("주소를 잘못 입력하셨습니다.")
      } else {
        setError("주소를 잘못 입력하셨습니다.")
      }
    } finally {
      setIsLoading(false)
    }
  }, [url, isValidUrl])

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(shortenedUrl)
      setIsCopied(true)
      setTimeout(() => setIsCopied(false), 2000)
    } catch {
      // fallback
    }
  }, [shortenedUrl])

  const handleReset = useCallback(() => {
    setUrl("")
    setShortenedUrl("")
    setShortId("") 
    setError("")
    setIsCopied(false)
  }, [])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") {
        handleShorten()
      }
    },
    [handleShorten]
  )

  return (
    <section className="flex flex-col items-center gap-8 px-4 py-24 md:py-32">
      <div className="flex flex-col items-center gap-3 text-center">
        <div className="flex items-center gap-2 rounded-full border border-border bg-card px-4 py-1.5">
          <Link className="h-4 w-4 text-primary" />
          <span className="text-sm font-medium text-foreground">URL Shortener</span>
        </div>
        <h1 className="text-balance text-3xl font-bold tracking-tight text-foreground md:text-5xl">
          긴 URL을 간결하게
        </h1>
        <p className="max-w-md text-pretty text-muted-foreground md:text-lg">
          복잡한 링크를 짧고 깔끔하게 변환하세요
        </p>
      </div>

      <div className="w-full max-w-xl">
        <div className="rounded-xl border border-border bg-card p-2 shadow-sm">
          <div className="flex gap-2">
            <Input
              type="url"
              placeholder="https://example.com/very-long-url..."
              value={url}
              onChange={(e) => {
                setUrl(e.target.value)
                if (error) setError("")
              }}
              onKeyDown={handleKeyDown}
              disabled={isLoading || !!shortenedUrl}
              className={cn(
                "h-12 border-0 bg-transparent text-base shadow-none focus-visible:ring-0 focus-visible:ring-offset-0",
                error && "placeholder:text-destructive/50"
              )}
              aria-label="단축할 URL 입력"
            />
            {!shortenedUrl && (
              <Button
                onClick={handleShorten}
                disabled={isLoading || !url.trim()}
                className="h-12 gap-2 px-6"
                size="lg"
              >
                {isLoading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <>
                    <span className="hidden sm:inline">단축하기</span>
                    <ArrowRight className="h-4 w-4" />
                  </>
                )}
              </Button>
            )}
          </div>
        </div>

        {error && (
          <p className="mt-2 text-center text-sm text-destructive" role="alert">
            {error}
          </p>
        )}

        {shortenedUrl && (
          <div className="mt-4 animate-in fade-in slide-in-from-bottom-2 duration-300">
            <div className="rounded-xl border border-success/30 bg-success/5 p-4">
              <div className="mb-3 flex items-center gap-2">
                <div className="flex h-5 w-5 items-center justify-center rounded-full bg-success">
                  <Check className="h-3 w-3 text-success-foreground" />
                </div>
                <span className="text-sm font-medium text-foreground">
                  단축 완료
                </span>
              </div>

              <div className="mb-4 rounded-lg bg-card px-4 py-3 border border-border">
                <p className="font-mono text-base font-semibold text-primary select-all">
                  {shortenedUrl}
                </p>
                {/* <p className="mt-1 truncate text-xs text-muted-foreground">
                  {url}
                </p> */}
              </div>

              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleCopy}
                  className="flex-1 gap-2 bg-transparent"
                >
                  {isCopied ? (
                    <>
                      <Check className="h-3.5 w-3.5" />
                      복사됨
                    </>
                  ) : (
                    <>
                      <Copy className="h-3.5 w-3.5" />
                      복사
                    </>
                  )}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  asChild
                  className="flex-1 gap-2 bg-transparent"
                >
                  <a href={shortenedUrl} target="_blank" rel="noopener noreferrer">
                    <ExternalLink className="h-3.5 w-3.5" />
                    바로가기
                  </a>
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleReset}
                  className="flex-1 gap-2 bg-transparent"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  다시하기
                </Button>
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  )
}
