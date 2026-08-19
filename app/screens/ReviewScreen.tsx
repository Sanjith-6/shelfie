import { useState } from "react";
import { Button, FlatList, Image, StyleSheet, Text, View } from "react-native";

import { cropImageUrl } from "../api";
import { reconciliation, undoAutoAdd } from "../session";
import { STATUS_COLORS, STATUS_LABELS } from "../statusLabels";
import { ScanSession } from "../types";

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

  async function handleUndo(spineId: string) {
    if (!session) return;
    try {
      onSessionChange(await undoAutoAdd(session, spineId));
      setUndoError(null);
    } catch (err) {
      setUndoError(err instanceof Error ? err.message : "Couldn't undo - try again.");
    }
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

          {pendingItems.length > 0 && (
            <>
              <Text style={styles.sectionHeading}>Needs your attention ({pendingItems.length})</Text>
              <Text style={styles.hint}>Review cards coming next - listed here for now.</Text>
              {pendingItems.map(({ spine }) => (
                <View key={spine.spine_id} style={styles.spineRow}>
                  <Image source={{ uri: cropImageUrl(spine.crop_url) }} style={styles.crop} />
                  <View style={styles.spineInfo}>
                    <Text style={styles.spineTitle}>{spine.raw_read.title ?? "(unreadable)"}</Text>
                    <Text style={styles.spineAuthor}>{spine.raw_read.author ?? ""}</Text>
                    <Text style={[styles.badge, { color: STATUS_COLORS[spine.status] }]}>
                      {STATUS_LABELS[spine.status]}
                    </Text>
                    {spine.error && <Text style={styles.errorText}>{spine.error}</Text>}
                  </View>
                </View>
              ))}
            </>
          )}

          {addedSpines.length === 0 && pendingItems.length === 0 && (
            <Text style={styles.hint}>Everything from this scan has been resolved.</Text>
          )}
        </View>
      }
    />
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
    marginTop: 4,
    fontSize: 13,
    fontWeight: "600",
  },
});
