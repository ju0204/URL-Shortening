import { SiteHeader } from "@/components/site-header"
import { SiteFooter } from "@/components/site-footer"
import { UrlShortener } from "@/components/url-shortener"
import { UrlTrends } from "@/components/url-trends"
import { ShareTiming } from "@/components/share-timing"

export default function Page() {
  return (
    <div className="flex min-h-screen flex-col">
      <SiteHeader />
      <main className="flex-1">
        <div id="shortener">
          <UrlShortener />
        </div>
        <div className="mx-auto max-w-5xl px-4">
          <hr className="border-border" />
        </div>
        <div id="trends">
          <UrlTrends />
        </div>
        <div className="mx-auto max-w-5xl px-4">
          <hr className="border-border" />
        </div>
        <div id="timing">
          <ShareTiming />
        </div>
      </main>
      <SiteFooter />
    </div>
  )
}
