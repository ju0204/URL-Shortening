
import Image from "next/image"
import { Link2 } from "lucide-react"


export function SiteHeader() {
  return (
    <header className="sticky top-0 z-50 border-b border-border bg-background/80 backdrop-blur-md">
      <div className="mx-auto flex h-16 max-w-5xl items-center justify-between px-4">
        <div className="flex items-center gap-2">
          {/* 로고 */}
          <Image
            src="/logo.png"
            alt="Shortify logo"
            width={180}
            height={84}
            
            priority
          />
          <span className="text-lg font-bold tracking-tight text-foreground">
            
          </span>
        </div>
        <nav className="flex items-center gap-6" aria-label="Main navigation">
          <a href="#shortener" className="text-sm text-muted-foreground transition-colors hover:text-foreground">
            URL 단축
          </a>
          <a href="#trends" className="text-sm text-muted-foreground transition-colors hover:text-foreground">
            트렌드
          </a>
          <a href="#timing" className="text-sm text-muted-foreground transition-colors hover:text-foreground">
            공유 시간
          </a>
        </nav>
      </div>
    </header>
  )
}
