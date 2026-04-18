/** Local persistence of past patient artifacts so the guided-questions
 *  AI assistant can answer cross-sectional questions across prior reports.
 *
 *  This is intentionally a thin, UI-facing store (localStorage). The
 *  authoritative record of an artifact remains the backend; this store
 *  only exists so the chat assistant has memory during manual UX testing
 *  even when the backend is offline.
 */

import type { PatientArtifact } from '../types';
import { unsupportedReasonDisplay } from '../types';

const STORAGE_KEY = 'elfie.labHistory.v1';
const MAX_ENTRIES = 20;

export interface LabHistoryEntry {
  /** Stable id: we use the job_id from the artifact. */
  id: string;
  /** ISO timestamp when this report was added to history. */
  recordedAt: string;
  /** Short human label (e.g. "Report · 2026-04-17"). */
  label: string;
  /** Full artifact snapshot. */
  artifact: PatientArtifact;
}

function safeParse(raw: string | null): LabHistoryEntry[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (entry): entry is LabHistoryEntry =>
        !!entry && typeof entry.id === 'string' && !!entry.artifact,
    );
  } catch {
    return [];
  }
}

export function loadLabHistory(): LabHistoryEntry[] {
  if (typeof window === 'undefined') return [];
  return safeParse(window.localStorage.getItem(STORAGE_KEY));
}

export function saveLabHistory(entries: LabHistoryEntry[]): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(entries));
  } catch {
    /* storage full / disabled — ignore */
  }
}

export function addLabReportToHistory(artifact: PatientArtifact): LabHistoryEntry[] {
  const existing = loadLabHistory();
  const filtered = existing.filter((entry) => entry.id !== artifact.job_id);
  const recordedAt = new Date().toISOString();
  const label = `Report · ${recordedAt.slice(0, 10)}`;
  const next: LabHistoryEntry = {
    id: artifact.job_id,
    recordedAt,
    label,
    artifact,
  };
  const combined = [next, ...filtered].slice(0, MAX_ENTRIES);
  saveLabHistory(combined);
  return combined;
}

export function clearLabHistory(): void {
  if (typeof window === 'undefined') return;
  window.localStorage.removeItem(STORAGE_KEY);
}

/** Compact, LLM-friendly summary of one artifact. Keeps only fields that
 *  are structurally defensible (flagged items, severity, next steps,
 *  comparable history, not-assessed). No free-form interpretation. */
export function summarizeArtifactForLLM(entry: LabHistoryEntry): string {
  const a = entry.artifact;
  const lines: string[] = [];
  lines.push(`## ${entry.label} (job ${a.job_id})`);
  lines.push(`- recorded_at: ${entry.recordedAt}`);
  lines.push(`- support_banner: ${a.support_banner}`);
  lines.push(`- trust_status: ${a.trust_status}`);
  lines.push(`- overall_severity: ${a.overall_severity}`);
  lines.push(`- language: ${a.language_id}`);

  if (a.flagged_cards.length > 0) {
    lines.push(`- flagged:`);
    for (const card of a.flagged_cards) {
      lines.push(
        `  * ${card.analyte_display}: ${card.value} ${card.unit} ` +
          `[${card.severity_chip}] — ${card.finding_sentence} ` +
          `(threshold: ${card.threshold_provenance})`,
      );
    }
  } else {
    lines.push(`- flagged: none`);
  }

  if (a.reviewed_not_flagged.length > 0) {
    lines.push(`- reviewed_not_flagged: ${a.reviewed_not_flagged.join(', ')}`);
  }

  lines.push(`- next_step_title: ${a.nextstep_title}`);
  if (a.nextstep_timing) lines.push(`- next_step_timing: ${a.nextstep_timing}`);
  if (a.nextstep_reason) lines.push(`- next_step_reason: ${a.nextstep_reason}`);

  if (a.not_assessed.length > 0) {
    lines.push(`- not_assessed:`);
    for (const item of a.not_assessed) {
      lines.push(`  * ${item.raw_label} — ${unsupportedReasonDisplay(item)}`);
    }
  }

  if (a.comparable_history) {
    const h = a.comparable_history;
    lines.push(
      `- comparable_history: ${h.analyte_display} ` +
        `current=${h.current_value}${h.current_unit} (${h.current_date ?? 'no date'}) ` +
        `previous=${h.previous_value ?? 'n/a'}${h.previous_unit ?? ''} ` +
        `(${h.previous_date ?? 'no date'}) direction=${h.direction}`,
    );
  }

  return lines.join('\n');
}

export function buildHistoryContext(entries: LabHistoryEntry[]): string {
  if (entries.length === 0) {
    return 'No prior lab reports are stored in the user history.';
  }
  return entries
    .slice(0, 10) // cap for token budget
    .map(summarizeArtifactForLLM)
    .join('\n\n');
}
