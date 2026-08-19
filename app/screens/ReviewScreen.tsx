import { useEffect, useState } from "react";
import { Alert, Button, FlatList, Image, Platform, StyleSheet, Text, TextInput, View } from "react-native";

import { cropImageUrl } from "../api";
import {
  discardAllPending,
  discardSpine,
  reconciliation,
  resolveManually,
  resolveWithCandidate,
  undoAutoAdd,
} from "../session";
import { STATUS_COLORS, STATUS_LABELS } from "../statusLabels";
import { QueueItem, ScanSession } from "../types";

export default function ReviewScreen({
  session,
  onSessionChange,
}: {
  session: ScanSession | null;
  onSessionChange: (session: ScanSession) => void;
}) {
  const [undoError, setUndoError] = useState<string | null>(null);

  if (!session) {
    return (
      <View style={styles.centered}>
        <Text style={styles.hint}>Nothing to review yet - scan a shelf to get started.</Text>
      </View>
    );
  }

  const counts = reconciliation(session);
  const addedSpines = session.scan.spines.filter((s) => session.autoOutcomes[s.spine_id]?.status === "added");
  const pendingItems = session.queue.filter((q) => q.outcome === null);
  const currentItem = pendingItems[0];

  async function handleUndo(spineId: string) {
    if (!session) return;
    try {
      onSessionChange(await undoAutoAdd(session, spineId));
      setUndoError(null);
    } catch (err) {
      setUndoError(err instanceof Error ? err.message : "Couldn't undo - try again.");
    }
  }

  function handleDiscardAll() {
    if (!session) return;
    const doIt = () => onSessionChange(discardAllPending(session));

    if (Platform.OS === "web") {
      if (window.confirm(`Discard all ${pendingItems.length} remaining spines? This can't be undone.`)) doIt();
      return;
    }
    Alert.alert(
      "Discard all remaining?",
      `This discards all ${pendingItems.length} remaining spines. This can't be undone.`,
      [
        { text: "Cancel", style: "cancel" },
        { text: "Discard all", style: "destructive", onPress: doIt },
      ],
    );
  }

  return (
    <FlatList
      style={styles.list}
      data={[]}
      keyExtractor={() => "unused"}
      renderItem={null}
      ListHeaderComponent={
        <View>
          <Text style={styles.reconciliation}>
            {counts.resolved} of {counts.total} resolved - {counts.pending} pending
          </Text>

          {currentItem ? (
            <>
              <ReviewCard
                key={currentItem.spine.spine_id}
                session={session}
                item={currentItem}
                remaining={pendingItems.length}
                totalQueue={session.queue.length}
                onSessionChange={onSessionChange}
              />
              <View style={styles.discardAllRow}>
                <Button
                  title={`Discard all remaining (${pendingItems.length})`}
                  color="#c62828"
                  onPress={handleDiscardAll}
                />
              </View>
            </>
          ) : (
            <Text style={styles.hint}>Nothing left to review from this scan.</Text>
          )}

          {undoError && <Text style={styles.errorText}>{undoError}</Text>}

          {addedSpines.length > 0 && (
            <>
              <Text style={styles.sectionHeading}>Added to library ({addedSpines.length})</Text>
              {addedSpines.map((spine) => (
                <View key={spine.spine_id} style={styles.spineRow}>
                  <Image source={{ uri: cropImageUrl(spine.crop_url) }} style={styles.crop} />
                  <View style={styles.spineInfo}>
                    <Text style={styles.spineTitle}>{spine.raw_read.title ?? "(unreadable)"}</Text>
                    <Text style={styles.spineAuthor}>{spine.raw_read.author ?? ""}</Text>
                    <Text style={[styles.badge, { color: STATUS_COLORS.auto }]}>{STATUS_LABELS.auto}</Text>
                  </View>
                  <Button title="Undo" onPress={() => handleUndo(spine.spine_id)} />
                </View>
              ))}
            </>
          )}
        </View>
      }
    />
  );
}

function ReviewCard({
  session,
  item,
  remaining,
  totalQueue,
  onSessionChange,
}: {
  session: ScanSession;
  item: QueueItem;
  remaining: number;
  totalQueue: number;
  onSessionChange: (session: ScanSession) => void;
}) {
  const spine = item.spine;
  const hasCandidates = spine.status !== "failed" && spine.candidates.length > 0;

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Manual entry defaults OPEN when there's no candidate to confirm - that's
  // the common case (88% unmatched in a real run), and it should be the
  // obvious next step, not a button tucked behind two disabled ones.
  const [manualMode, setManualMode] = useState(!hasCandidates);
  const [manualTitle, setManualTitle] = useState(spine.raw_read.title ?? "");
  const [manualAuthor, setManualAuthor] = useState(spine.raw_read.author ?? "");

  useEffect(() => {
    setManualMode(!hasCandidates);
    setManualTitle(spine.raw_read.title ?? "");
    setManualAuthor(spine.raw_read.author ?? "");
    setError(null);
    setBusy(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spine.spine_id]);

  async function run(action: () => Promise<ScanSession>) {
    setBusy(true);
    setError(null);
    try {
      onSessionChange(await action());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong - try again.");
    } finally {
      setBusy(false);
    }
  }

  if (spine.status === "failed") {
    return (
      <View style={styles.card}>
        <Image source={{ uri: cropImageUrl(spine.crop_url) }} style={styles.cardCrop} />
        <Text style={styles.cardProgress}>
          {remaining} of {totalQueue} remaining
        </Text>
        <Text style={[styles.badge, { color: STATUS_COLORS.failed }]}>{STATUS_LABELS.failed}</Text>
        <Text style={styles.cardError}>{spine.error ?? "This spine's read failed."}</Text>
        {error && <Text style={styles.errorText}>{error}</Text>}
        <Button
          title="Discard"
          onPress={() => run(() => Promise.resolve(discardSpine(session, spine.spine_id)))}
          disabled={busy}
        />
      </View>
    );
  }

  const candidates = spine.candidates.slice(0, 3);

  return (
    <View style={styles.card}>
      <Image source={{ uri: cropImageUrl(spine.crop_url) }} style={styles.cardCrop} />
      <Text style={styles.cardProgress}>
        {remaining} of {totalQueue} remaining
      </Text>
      <Text style={styles.cardTitle}>{spine.raw_read.title ?? "(unreadable)"}</Text>
      <Text style={styles.cardAuthor}>{spine.raw_read.author ?? ""}</Text>
      <Text style={[styles.badge, { color: STATUS_COLORS[spine.status] }]}>{STATUS_LABELS[spine.status]}</Text>
      {error && <Text style={styles.errorText}>{error}</Text>}

      {hasCandidates && !manualMode && (
        <View>
          <Text style={styles.sectionHeading}>Candidates</Text>
          {candidates.map((c, i) => (
            <View key={c.catalog_id} style={styles.candidateRow}>
              <View style={styles.candidateInfo}>
                <Text style={styles.candidateTitle}>{c.title}</Text>
                <Text style={styles.candidateAuthor}>{c.author}</Text>
                <Text style={styles.candidateScore}>score {c.score.toFixed(2)}</Text>
                <Text style={styles.candidateReasons}>{c.reasons.join("; ")}</Text>
              </View>
              <Button
                title={i === 0 ? "Confirm" : "Use this"}
                onPress={() =>
                  run(() => resolveWithCandidate(session, spine.spine_id, c, i === 0 ? "confirmed" : "corrected"))
                }
                disabled={busy}
              />
            </View>
          ))}
        </View>
      )}

      {!hasCandidates && !manualMode && <Text style={styles.hint}>No catalog match found for this spine.</Text>}

      {!manualMode && (
        <View style={styles.actionRow}>
          <Button title="Enter Manually" onPress={() => setManualMode(true)} disabled={busy} />
          <Button
            title="Discard"
            onPress={() => run(() => Promise.resolve(discardSpine(session, spine.spine_id)))}
            disabled={busy}
          />
        </View>
      )}

      {manualMode && (
        <View>
          <Text style={styles.sectionHeading}>Enter manually</Text>
          <TextInput style={styles.input} placeholder="Title" value={manualTitle} onChangeText={setManualTitle} />
          <TextInput style={styles.input} placeholder="Author" value={manualAuthor} onChangeText={setManualAuthor} />
          <View style={styles.actionRow}>
            <Button
              title="Save"
              onPress={() => run(() => resolveManually(session, spine.spine_id, manualTitle.trim(), manualAuthor.trim()))}
              disabled={busy || manualTitle.trim().length === 0}
            />
            {hasCandidates && <Button title="Back to candidates" onPress={() => setManualMode(false)} disabled={busy} />}
            <Button
              title="Discard"
              onPress={() => run(() => Promise.resolve(discardSpine(session, spine.spine_id)))}
              disabled={busy}
            />
          </View>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  list: {
    flex: 1,
    paddingHorizontal: 12,
  },
  centered: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 24,
  },
  hint: {
    color: "#666",
    textAlign: "center",
    marginVertical: 8,
  },
  errorText: {
    color: "#c62828",
    textAlign: "center",
  },
  reconciliation: {
    fontSize: 15,
    fontWeight: "600",
    textAlign: "center",
    marginVertical: 8,
  },
  sectionHeading: {
    fontSize: 17,
    fontWeight: "700",
    marginTop: 16,
    marginBottom: 4,
  },
  spineRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingVertical: 10,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: "#ddd",
  },
  crop: {
    width: 70,
    height: 100,
    backgroundColor: "#eee",
  },
  spineInfo: {
    flex: 1,
    justifyContent: "center",
  },
  spineTitle: {
    fontSize: 16,
    fontWeight: "600",
  },
  spineAuthor: {
    fontSize: 14,
    color: "#444",
  },
  badge: {
    marginTop: 2,
    fontSize: 13,
    fontWeight: "600",
  },
  card: {
    borderWidth: 1,
    borderColor: "#ccc",
    borderRadius: 8,
    padding: 12,
    marginTop: 8,
    alignItems: "center",
  },
  cardCrop: {
    width: 120,
    height: 170,
    backgroundColor: "#eee",
  },
  cardProgress: {
    fontSize: 12,
    color: "#666",
    marginTop: 8,
  },
  cardTitle: {
    fontSize: 18,
    fontWeight: "700",
    marginTop: 8,
    textAlign: "center",
  },
  cardAuthor: {
    fontSize: 15,
    color: "#444",
    textAlign: "center",
  },
  cardError: {
    color: "#c62828",
    textAlign: "center",
    marginTop: 8,
    marginBottom: 12,
  },
  candidateRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingVertical: 8,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: "#eee",
    width: "100%",
  },
  candidateInfo: {
    flex: 1,
  },
  candidateTitle: {
    fontSize: 15,
    fontWeight: "600",
  },
  candidateAuthor: {
    fontSize: 13,
    color: "#444",
  },
  candidateScore: {
    fontSize: 12,
    color: "#666",
  },
  candidateReasons: {
    fontSize: 11,
    color: "#888",
  },
  actionRow: {
    flexDirection: "row",
    gap: 8,
    marginTop: 12,
    flexWrap: "wrap",
    justifyContent: "center",
  },
  input: {
    borderWidth: 1,
    borderColor: "#ccc",
    borderRadius: 4,
    padding: 8,
    marginTop: 6,
    width: "100%",
  },
  discardAllRow: {
    alignItems: "center",
    marginTop: 12,
    marginBottom: 8,
  },
});
