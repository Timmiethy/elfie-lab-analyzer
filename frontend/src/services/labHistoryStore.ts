import type { PatientArtifact } from '../types';

const HISTORY_KEY = 'elfie.labHistory';
const MAX_ITEMS = 20;

type HistoryEntry = {
  id: string;
  savedAt: string;
  artifact: PatientArtifact;
};

function readHistory(): HistoryEntry[] {
  if (typeof window === 'undefined') {
    return [];
  }

  try {
    const raw = window.localStorage.getItem(HISTORY_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed as HistoryEntry[];
  } catch {
    return [];
  }
}

function writeHistory(entries: HistoryEntry[]): void {
  if (typeof window === 'undefined') {
    return;
  }
  window.localStorage.setItem(HISTORY_KEY, JSON.stringify(entries));
}

export function addLabReportToHistory(artifact: PatientArtifact): void {
  const nextEntry: HistoryEntry = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
    savedAt: new Date().toISOString(),
    artifact,
  };

  const existing = readHistory();
  const deduped = existing.filter((item) => item.id !== nextEntry.id);
  writeHistory([nextEntry, ...deduped].slice(0, MAX_ITEMS));
}
