import { PageHeader } from "@/components/app/page-header";
import { Alert } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api";
import type { StudentProfile } from "@/lib/types";

import { ProfileClient } from "./profile-client";

export default async function ProfilePage() {
  let profile: StudentProfile | null = null;
  let failure: string | null = null;
  try {
    profile = await api.profile.get();
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    failure = error.message;
  }

  if (failure) {
    return (
      <>
        <PageHeader title="Profile" />
        <div className="p-5">
          <Alert tone="danger" title="Could not load your profile">
            {failure}
          </Alert>
        </div>
      </>
    );
  }

  if (!profile) {
    return (
      <>
        <PageHeader title="Profile" />
        <div className="p-5">
          <Alert tone="neutral" title="No profile yet">
            Finish onboarding and your profile will appear here.
          </Alert>
        </div>
      </>
    );
  }

  return <ProfileClient initial={profile} />;
}
