import { useCallback, useEffect, useState } from "react";
import { Button, FlatList, RefreshControl, StyleSheet, Text, View } from "react-native";

import { deleteLibraryEntry, getLibrary } from "../api";
import { LibraryEntry, LibraryResolution } from "../types";

const RESOLUTION_LABELS: Record<LibraryResolution, string> = {
  auto: "Auto",
  confirmed: "Confirmed",
  corrected: "Corrected",
  manual: "Manual",
};

type State =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "loaded"; entries: LibraryEntry[] };

export default function LibraryScreen() {
  const [state, setState] = useState<State>({ phase: "loading" });
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const entries = await getLibrary();
      setState({ phase: "loaded", entries });
    } catch (err) {
      setState({ phase: "error", message: err instanceof Error ? err.message : "Couldn't load your library." });
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleRefresh() {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  }

  async function handleUndo(entry: LibraryEntry) {
    if (state.phase !== "loaded") return;
    try {
      await deleteLibraryEntry(entry.id);
      setState({ phase: "loaded", entries: state.entries.filter((e) => e.id !== entry.id) });
    } catch (err) {
      setState({ phase: "error", message: err instanceof Error ? err.message : "Couldn't undo - try again." });
    }
  }

  if (state.phase === "loading") {
    return (
      <View style={styles.centered}>
        <Text>Loading your library...</Text>
      </View>
    );
  }

  if (state.phase === "error") {
    return (
      <View style={styles.centered}>
        <Text style={styles.errorText}>{state.message}</Text>
        <Button title="Try again" onPress={load} />
      </View>
    );
  }

  if (state.entries.length === 0) {
    return (
      <View style={styles.centered}>
        <Text style={styles.hint}>Your library is empty. Scan a shelf to get started.</Text>
      </View>
    );
  }

  return (
    <FlatList
      style={styles.list}
      data={state.entries}
      keyExtractor={(entry) => String(entry.id)}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={handleRefresh} />}
      renderItem={({ item }) => (
        <View style={styles.row}>
          <View style={styles.info}>
            <Text style={styles.title}>{item.title}</Text>
            <Text style={styles.author}>{item.author}</Text>
            <Text style={styles.resolution}>{RESOLUTION_LABELS[item.resolution]}</Text>
          </View>
          {item.resolution === "auto" && <Button title="Undo" onPress={() => handleUndo(item)} />}
        </View>
      )}
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
    gap: 8,
  },
  hint: {
    color: "#666",
    textAlign: "center",
  },
  errorText: {
    color: "#c62828",
    textAlign: "center",
  },
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingVertical: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: "#ddd",
  },
  info: {
    flex: 1,
  },
  title: {
    fontSize: 16,
    fontWeight: "600",
  },
  author: {
    fontSize: 14,
    color: "#444",
  },
  resolution: {
    marginTop: 4,
    fontSize: 12,
    color: "#666",
    textTransform: "uppercase",
  },
});
