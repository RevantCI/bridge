import { writable, derived } from "svelte/store";
import type { ProjectInfo, QaFinding } from "./types/finding";

export const project = writable<ProjectInfo | null>(null);
export const currentChapter = writable<string>("1");
export const verseNums = writable<string[]>([]);
export const verseTexts = writable<Record<string, string>>({});
export const findingsByVerse = writable<Record<string, QaFinding[]>>({});
export const selectedVerse = writable<string | null>(null);
export const checkingProgress = writable<{ running: boolean; percent: number; label: string }>({
  running: false, percent: 0, label: "",
});

export const settingsOpen = writable(false);
export const exportOpen = writable(false);
export const showSource = writable(false);

export const selectedFindings = derived(
  [findingsByVerse, selectedVerse],
  ([$findingsByVerse, $selectedVerse]) => ($selectedVerse ? $findingsByVerse[$selectedVerse] ?? [] : [])
);

export const approvedCount = derived(
  [findingsByVerse, verseNums],
  ([$findingsByVerse, $verseNums]) =>
    $verseNums.filter((v) => ($findingsByVerse[v] ?? []).every((f) => f.status !== "open")).length
);
