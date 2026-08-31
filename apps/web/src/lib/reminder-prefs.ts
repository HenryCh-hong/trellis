/**
 * Default reminder offsets, per browser.
 *
 * Deliberately local: this is a display preference, not profile data, and it
 * only seeds the value in the reminder dialog. Each reminder stores its own
 * offsets server-side once created, so changing this never silently rewrites
 * a reminder you already made.
 */

const KEY = "trellis-reminder-offsets";
export const FALLBACK_OFFSETS = [7, 3, 1];

export function parseOffsets(raw: string): number[] {
  return raw
    .split(/[,\s]+/)
    .map((s) => Number.parseInt(s, 10))
    .filter((n) => Number.isFinite(n) && n >= 0 && n <= 120);
}

export function readDefaultOffsets(): number[] {
  try {
    const stored = window.localStorage.getItem(KEY);
    if (!stored) return FALLBACK_OFFSETS;
    const parsed = parseOffsets(stored);
    return parsed.length ? parsed : FALLBACK_OFFSETS;
  } catch {
    return FALLBACK_OFFSETS;
  }
}

export function writeDefaultOffsets(offsets: number[]): boolean {
  try {
    window.localStorage.setItem(KEY, offsets.join(", "));
    return true;
  } catch {
    return false;
  }
}
