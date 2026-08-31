import { Sidebar, MobileNav } from "@/components/app/nav";
import { api } from "@/lib/api";

/**
 * App shell. Server component so the sidebar knows the university on first
 * paint without a client round trip.
 */
export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  let university: string | null = null;
  try {
    const profile = await api.profile.get();
    university = profile?.university ?? null;
  } catch {
    // Backend down or not onboarded yet — the shell still renders.
  }

  return (
    <div className="flex h-dvh overflow-hidden">
      <div className="hidden md:block">
        <Sidebar university={university} />
      </div>
      <main className="flex min-w-0 flex-1 flex-col overflow-hidden pb-14 md:pb-0">
        {children}
      </main>
      <MobileNav />
    </div>
  );
}
