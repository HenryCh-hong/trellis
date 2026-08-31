import { redirect } from "next/navigation";

import { api } from "@/lib/api";

import { OnboardingClient } from "./onboarding-client";

/** Outside the (app) group on purpose: onboarding has no sidebar. */
export default async function OnboardingPage() {
  try {
    const profile = await api.profile.get();
    if (profile?.onboarding_completed_at) redirect("/");
  } catch {
    // Backend unreachable — still show the form rather than a blank screen.
  }
  return <OnboardingClient />;
}
