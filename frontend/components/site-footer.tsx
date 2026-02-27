import { Link2 } from "lucide-react"

export function SiteFooter() {
  return (
    <footer className="border-t border-border bg-card">
      <div className="mx-auto flex max-w-5xl flex-col items-center gap-4 px-4 py-8 md:flex-row md:justify-between">
        <div className="flex items-center gap-2">
          {/* <div className="flex h-6 w-6 items-center justify-center rounded-md bg-primary">
            <Link2 className="h-3 w-3 text-primary-foreground" />
          </div> */}
          <span className="text-sm font-semibold text-foreground">© Shortify</span>
        </div>
        <p className="text-xs text-muted-foreground">
          Serverless URL Shortener. Fast, simple, and clean.
        </p>
      </div>
    </footer>
  )
}
