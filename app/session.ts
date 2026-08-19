import { addToLibrary, deleteLibraryEntry } from "./api";
import { QueueItem, ScanResponse, ScanSession } from "./types";

// Called once right after a scan completes. "auto" spines get added to the
// library immediately - a failed add (network error) still needs a real
// decision from the user, so it falls through into the queue instead of
// vanishing; nothing that was detected is allowed to disappear silently.
export async function buildScanSession(scan: ScanResponse): Promise<ScanSession> {
  const session: ScanSession = { scan, autoOutcomes: {}, queue: [] };

  for (const spine of scan.spines) {
    if (spine.status !== "auto") {
      session.queue.push({ spine, outcome: null });
      continue;
    }

    const top = spine.candidates[0];
    if (!top) {
      // Shouldn't happen - the matcher only returns "auto" with a
      // confident top candidate - but never trust that blindly here either.
      session.queue.push({ spine, outcome: null });
      continue;
    }

    try {
      const entry = await addToLibrary({
        catalog_book: top.catalog_id,
        title: top.title,
        author: top.author,
        raw_title: spine.raw_read.title ?? "",
        raw_author: spine.raw_read.author ?? "",
        confidence: top.score,
        resolution: "auto",
      });
      session.autoOutcomes[spine.spine_id] = { status: "added", entryId: entry.id };
    } catch (err) {
      session.autoOutcomes[spine.spine_id] = {
        status: "failed",
        message: err instanceof Error ? err.message : "Couldn't add to library.",
      };
      session.queue.push({ spine, outcome: null });
    }
  }

  return session;
}

// Undo deletes the library entry and drops the spine back into the queue -
// it must reach a new terminal state via a real decision, not sit removed
// from the library but still counted as "added" in the reconciliation.
export async function undoAutoAdd(session: ScanSession, spineId: string): Promise<ScanSession> {
  const outcome = session.autoOutcomes[spineId];
  if (!outcome || outcome.status !== "added") return session;

  await deleteLibraryEntry(outcome.entryId);

  const spine = session.scan.spines.find((s) => s.spine_id === spineId);
  if (!spine) return session;

  const { [spineId]: _removed, ...remainingOutcomes } = session.autoOutcomes;
  return {
    ...session,
    autoOutcomes: remainingOutcomes,
    queue: [...session.queue, { spine, outcome: null }],
  };
}

export function setQueueOutcome(session: ScanSession, spineId: string, outcome: QueueItem["outcome"]): ScanSession {
  return {
    ...session,
    queue: session.queue.map((item) => (item.spine.spine_id === spineId ? { ...item, outcome } : item)),
  };
}

export type Reconciliation = {
  total: number;
  added: number;
  confirmed: number;
  corrected: number;
  manual: number;
  discarded: number;
  pending: number;
  resolved: number;
};

export function reconciliation(session: ScanSession): Reconciliation {
  const added = Object.values(session.autoOutcomes).filter((o) => o.status === "added").length;
  const confirmed = session.queue.filter((q) => q.outcome === "confirmed").length;
  const corrected = session.queue.filter((q) => q.outcome === "corrected").length;
  const manual = session.queue.filter((q) => q.outcome === "manual").length;
  const discarded = session.queue.filter((q) => q.outcome === "discarded").length;
  const pending = session.queue.filter((q) => q.outcome === null).length;

  return {
    total: session.scan.detected_count,
    added,
    confirmed,
    corrected,
    manual,
    discarded,
    pending,
    resolved: added + confirmed + corrected + manual + discarded,
  };
}
