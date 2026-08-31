import { PageHeader } from "@/components/app/page-header";
import { Alert } from "@/components/ui/primitives";
import { ApiError, api } from "@/lib/api";
import type { DataSourceInfo, ProvenanceInfo, ReminderProviderInfo } from "@/lib/types";

import { SettingsClient } from "./settings-client";

export default async function SettingsPage() {
  let sources: DataSourceInfo[] = [];
  let provenance: ProvenanceInfo[] = [];
  let providers: ReminderProviderInfo[] = [];
  let failure: string | null = null;

  try {
    [sources, provenance, providers] = await Promise.all([
      api.settings.sources(),
      api.settings.provenance(),
      api.reminders.providers(),
    ]);
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    failure = error.message;
  }

  if (failure) {
    return (
      <>
        <PageHeader title="Settings" />
        <div className="p-5">
          <Alert tone="danger" title="Could not load settings">
            {failure}
          </Alert>
        </div>
      </>
    );
  }

  return <SettingsClient sources={sources} provenance={provenance} providers={providers} />;
}
