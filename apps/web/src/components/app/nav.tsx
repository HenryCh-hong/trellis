"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Overview", icon: OverviewIcon },
  { href: "/opportunities", label: "Opportunities", icon: ListIcon },
  { href: "/research", label: "Research", icon: FlaskIcon },
  { href: "/applications", label: "Applications", icon: SendIcon },
  { href: "/resumes", label: "Resumes", icon: DocIcon },
] as const;

const FOOTER_NAV = [
  { href: "/profile", label: "Profile", icon: UserIcon },
  { href: "/settings", label: "Settings", icon: GearIcon },
] as const;

export function Sidebar({ university }: { university?: string | null }) {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Main"
      className="flex h-full w-[196px] shrink-0 flex-col border-r border-[var(--border)] bg-[var(--bg-subtle)]"
    >
      <div className="flex h-12 items-center gap-2 px-4">
        <Logo />
        <div className="min-w-0">
          <div className="text-[13px] font-semibold leading-none tracking-[-0.01em]">
            Trellis
          </div>
          {university && (
            <div className="mt-0.5 truncate text-2xs text-[var(--text-tertiary)]">
              {university}
            </div>
          )}
        </div>
      </div>

      <div className="flex flex-1 flex-col gap-0.5 px-2 py-2">
        {NAV.map((item) => (
          <NavLink key={item.href} {...item} pathname={pathname} />
        ))}
      </div>

      <div className="flex flex-col gap-0.5 border-t border-[var(--border)] px-2 py-2">
        {FOOTER_NAV.map((item) => (
          <NavLink key={item.href} {...item} pathname={pathname} />
        ))}
      </div>
    </nav>
  );
}

function NavLink({
  href,
  label,
  icon: Icon,
  pathname,
}: {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  pathname: string;
}) {
  const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex h-7 items-center gap-2 rounded-[var(--radius-sm)] px-2 text-xs font-medium",
        "transition-colors duration-100",
        active
          ? "bg-[var(--bg-active)] text-[var(--text-primary)]"
          : "text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]",
      )}
    >
      <Icon className={cn("size-3.5 shrink-0", active ? "opacity-90" : "opacity-60")} />
      {label}
    </Link>
  );
}

/** Mobile: the sidebar collapses to a bottom bar. */
export function MobileNav() {
  const pathname = usePathname();
  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-30 flex h-14 items-stretch border-t border-[var(--border)] bg-[var(--bg)] md:hidden"
    >
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            className={cn(
              "flex flex-1 flex-col items-center justify-center gap-1 text-[10px] font-medium",
              active ? "text-[var(--accent)]" : "text-[var(--text-tertiary)]",
            )}
          >
            <Icon className="size-4" />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

function Logo() {
  return (
    <div className="flex size-6 shrink-0 items-center justify-center rounded-[var(--radius-sm)] bg-[var(--accent)]">
      <svg className="size-3.5 text-white" viewBox="0 0 16 16" fill="none" aria-hidden>
        <path
          d="M8 14V6M8 6 4.5 3M8 6l3.5-3M8 10l-3-2M8 10l3-2"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
}

/* --- icons: single stroke weight, 16px grid, no filled shapes ----------- */

function OverviewIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" aria-hidden>
      <rect x="2.5" y="2.5" width="4.5" height="5.5" rx="1.2" stroke="currentColor" strokeWidth="1.3" />
      <rect x="9" y="2.5" width="4.5" height="3" rx="1.2" stroke="currentColor" strokeWidth="1.3" />
      <rect x="2.5" y="10" width="4.5" height="3.5" rx="1.2" stroke="currentColor" strokeWidth="1.3" />
      <rect x="9" y="7.5" width="4.5" height="6" rx="1.2" stroke="currentColor" strokeWidth="1.3" />
    </svg>
  );
}
function ListIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" aria-hidden>
      <path d="M5.5 4h8M5.5 8h8M5.5 12h8M2.5 4h.01M2.5 8h.01M2.5 12h.01" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}
function FlaskIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" aria-hidden>
      <path d="M6.5 2v4L3 12.2A1.2 1.2 0 0 0 4 14h8a1.2 1.2 0 0 0 1-1.8L9.5 6V2" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      <path d="M5.5 2h5M4.6 10h6.8" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}
function SendIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" aria-hidden>
      <path d="M13.5 2.5 7 9M13.5 2.5l-4 11-2.5-4.5L2.5 6.5l11-4Z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
    </svg>
  );
}
function DocIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" aria-hidden>
      <path d="M9 2H4.5A1.5 1.5 0 0 0 3 3.5v9A1.5 1.5 0 0 0 4.5 14h7a1.5 1.5 0 0 0 1.5-1.5V6L9 2Z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      <path d="M9 2v3.2c0 .4.4.8.8.8H13M5.8 9h4.4M5.8 11.3h3" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}
function UserIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" aria-hidden>
      <circle cx="8" cy="5.5" r="2.6" stroke="currentColor" strokeWidth="1.3" />
      <path d="M3 13.2c.7-2.3 2.6-3.5 5-3.5s4.3 1.2 5 3.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}
function GearIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" aria-hidden>
      <circle cx="8" cy="8" r="2.2" stroke="currentColor" strokeWidth="1.3" />
      <path d="M8 1.8v1.6M8 12.6v1.6M14.2 8h-1.6M3.4 8H1.8M12.4 3.6l-1.1 1.1M4.7 11.3l-1.1 1.1M12.4 12.4l-1.1-1.1M4.7 4.7 3.6 3.6" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  );
}
