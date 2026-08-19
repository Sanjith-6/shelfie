import { useEffect, useRef, useState } from "react";
import * as ImagePicker from "expo-image-picker";
import { StatusBar } from "expo-status-bar";
import {
  ActivityIndicator,
  Button,
  FlatList,
  Image,
  Platform,
  SafeAreaView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import { cropImageUrl, scanImage } from "./api";
import { buildScanSession, reconciliation, undoAutoAdd } from "./session";
import { ScanSession, SpineStatus } from "./types";

type ScreenState =
  | { phase: "idle" }
  | { phase: "uploading" }
  | { phase: "processing" } // scan done, running the auto-add calls
  | { phase: "error"; message: string }
  | { phase: "session"; session: ScanSession };

const STATUS_LABELS: Record<SpineStatus, string> = {
  auto: "Added",
  review: "Needs review",
  unmatched: "Unmatched",
  failed: "Failed",
};

const STATUS_COLORS: Record<SpineStatus, string> = {
  auto: "#2e7d32",
  review: "#ef6c00",
  unmatched: "#616161",
  failed: "#c62828",
};

export default function App() {
  const [state, setState] = useState<ScreenState>({ phase: "idle" });
  const [undoError, setUndoError] = useState<string | null>(null);
  const webFileInputRef = useRef<HTMLInputElement | null>(null);

  async function uploadImage(source: string | File) {
    setState({ phase: "uploading" });
    setUndoError(null);

    try {
      const scan = await scanImage(source);
      setState({ phase: "processing" });
      const session = await buildScanSession(scan);
      setState({ phase: "session", session });
    } catch (err) {
      setState({
        phase: "error",
        message:
          err instanceof Error
            ? err.message
            : "Couldn't reach the server. Check that Django is running and API_BASE_URL in config.ts matches your machine's LAN IP.",
      });
    }
  }

  async function handleUndo(spineId: string) {
    if (state.phase !== "session") return;
    try {
      const updated = await undoAutoAdd(state.session, spineId);
      setState({ phase: "session", session: updated });
      setUndoError(null);
    } catch (err) {
      setUndoError(err instanceof Error ? err.message : "Couldn't undo - try again.");
    }
  }

  // Web-only: a real DOM file input. expo-image-picker technically works on
  // web, but Expo's own docs say cancellation isn't reliably reported across
  // browsers - a plain input sidesteps that instead of working around it.
  useEffect(() => {
    if (Platform.OS !== "web") return;

    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.style.display = "none";
    input.addEventListener("change", () => {
      const file = input.files?.[0];
      input.value = ""; // otherwise picking the same file twice fires nothing
      if (file) uploadImage(file);
    });
    document.body.appendChild(input);
    webFileInputRef.current = input;

    return () => {
      document.body.removeChild(input);
    };
  }, []);

  function pickPhotoWeb() {
    webFileInputRef.current?.click();
  }

  async function takePhoto() {
    const permission = await ImagePicker.requestCameraPermissionsAsync();
    if (!permission.granted) {
      setState({ phase: "error", message: "Camera permission is required." });
      return;
    }
    const result = await ImagePicker.launchCameraAsync({ mediaTypes: ["images"], quality: 0.8 });
    if (!result.canceled && result.assets.length > 0) {
      uploadImage(result.assets[0].uri);
    }
  }

  async function pickFromLibrary() {
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      setState({ phase: "error", message: "Photo library permission is required." });
      return;
    }
    const result = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 0.8 });
    if (!result.canceled && result.assets.length > 0) {
      uploadImage(result.assets[0].uri);
    }
  }

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar style="auto" />
      <Text style={styles.heading}>Shelfie</Text>

      <View style={styles.buttonRow}>
        {Platform.OS === "web" ? (
          // No camera on a laptop - a "Take Photo" button here would just
          // open the same file dialog, which is worse than not having it.
          <Button title="Choose Photo" onPress={pickPhotoWeb} disabled={isBusy(state)} />
        ) : (
          <>
            <Button title="Take Photo" onPress={takePhoto} disabled={isBusy(state)} />
            <Button title="Choose Photo" onPress={pickFromLibrary} disabled={isBusy(state)} />
          </>
        )}
      </View>

      {state.phase === "uploading" && (
        <View style={styles.centered}>
          <ActivityIndicator size="large" />
          <Text>Scanning shelf...</Text>
        </View>
      )}

      {state.phase === "processing" && (
        <View style={styles.centered}>
          <ActivityIndicator size="large" />
          <Text>Adding confident matches to your library...</Text>
        </View>
      )}

      {state.phase === "error" && (
        <View style={styles.centered}>
          <Text style={styles.errorText}>{state.message}</Text>
        </View>
      )}

      {state.phase === "session" && state.session.scan.detected_count === 0 && (
        <View style={styles.centered}>
          <Text>No books detected in this photo.</Text>
          <Text style={styles.hint}>Try a clearer photo, taken straight-on and closer to the shelf.</Text>
        </View>
      )}

      {state.phase === "session" && state.session.scan.detected_count > 0 && (
        <SessionSummary session={state.session} undoError={undoError} onUndo={handleUndo} />
      )}
    </SafeAreaView>
  );
}

function isBusy(state: ScreenState) {
  return state.phase === "uploading" || state.phase === "processing";
}

function SessionSummary({
  session,
  undoError,
  onUndo,
}: {
  session: ScanSession;
  undoError: string | null;
  onUndo: (spineId: string) => void;
}) {
  const counts = reconciliation(session);
  const addedSpines = session.scan.spines.filter((s) => session.autoOutcomes[s.spine_id]?.status === "added");
  const pendingItems = session.queue.filter((q) => q.outcome === null);

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
                  <Button title="Undo" onPress={() => onUndo(spine.spine_id)} />
                </View>
              ))}
            </>
          )}

          {pendingItems.length > 0 && (
            <>
              <Text style={styles.sectionHeading}>Needs your attention ({pendingItems.length})</Text>
              <Text style={styles.hint}>Review screen coming next - these are listed here for now.</Text>
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
        </View>
      }
    />
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#fff",
    paddingTop: 20,
  },
  heading: {
    fontSize: 24,
    fontWeight: "bold",
    textAlign: "center",
    marginBottom: 12,
  },
  buttonRow: {
    flexDirection: "row",
    justifyContent: "space-around",
    marginBottom: 16,
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
    paddingHorizontal: 12,
  },
  errorText: {
    color: "#c62828",
    textAlign: "center",
  },
  list: {
    flex: 1,
    paddingHorizontal: 12,
  },
  spineRow: {
    flexDirection: "row",
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
