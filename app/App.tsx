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

import { API_BASE_URL } from "./config";

type RawRead = { title: string | null; author: string | null };

type Candidate = {
  catalog_id: number;
  title: string;
  author: string;
  score: number;
  reasons: string[];
};

type SpineStatus = "auto" | "review" | "unmatched" | "failed";

type Spine = {
  spine_id: string;
  bbox: [number, number, number, number];
  crop_url: string;
  raw_read: RawRead;
  status: SpineStatus;
  candidates: Candidate[];
  error: string | null;
};

type ScanResponse = {
  scan_id: string;
  timings_ms: { detect: number; vlm: number; match: number; total: number };
  detected_count: number;
  spines: Spine[];
  warnings: string[];
};

type ScreenState =
  | { phase: "idle" }
  | { phase: "uploading" }
  | { phase: "error"; message: string }
  | { phase: "results"; scan: ScanResponse };

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
  const webFileInputRef = useRef<HTMLInputElement | null>(null);

  // Native gives us a local file URI; web's file input gives us the File
  // object directly. Both funnel through this one function from here on.
  async function uploadImage(source: string | File) {
    setState({ phase: "uploading" });

    const formData = new FormData();
    if (typeof source === "string") {
      // React Native's fetch wants this object shape for a file field, not
      // a Blob - the URI is a local file path the native layer streams from.
      formData.append("image", {
        uri: source,
        name: "shelf.jpg",
        type: "image/jpeg",
      } as unknown as Blob);
    } else {
      formData.append("image", source, source.name || "shelf.jpg");
    }

    try {
      const response = await fetch(`${API_BASE_URL}/api/scan`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const body = await response.json().catch(() => null);
        setState({
          phase: "error",
          message: body?.message ?? `Scan failed (${response.status}).`,
        });
        return;
      }

      const scan: ScanResponse = await response.json();
      setState({ phase: "results", scan });
    } catch {
      setState({
        phase: "error",
        message: "Couldn't reach the server. Check that Django is running and API_BASE_URL in config.ts matches your machine's LAN IP.",
      });
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
          <Button title="Choose Photo" onPress={pickPhotoWeb} disabled={state.phase === "uploading"} />
        ) : (
          <>
            <Button title="Take Photo" onPress={takePhoto} disabled={state.phase === "uploading"} />
            <Button title="Choose Photo" onPress={pickFromLibrary} disabled={state.phase === "uploading"} />
          </>
        )}
      </View>

      {state.phase === "uploading" && (
        <View style={styles.centered}>
          <ActivityIndicator size="large" />
          <Text>Scanning shelf...</Text>
        </View>
      )}

      {state.phase === "error" && (
        <View style={styles.centered}>
          <Text style={styles.errorText}>{state.message}</Text>
        </View>
      )}

      {state.phase === "results" && state.scan.detected_count === 0 && (
        <View style={styles.centered}>
          <Text>No books detected in this photo.</Text>
          <Text style={styles.hint}>Try a clearer photo, taken straight-on and closer to the shelf.</Text>
        </View>
      )}

      {state.phase === "results" && state.scan.detected_count > 0 && (
        <FlatList
          style={styles.list}
          data={state.scan.spines}
          keyExtractor={(spine) => spine.spine_id}
          renderItem={({ item }) => (
            <View style={styles.spineRow}>
              <Image source={{ uri: `${API_BASE_URL}${item.crop_url}` }} style={styles.crop} />
              <View style={styles.spineInfo}>
                <Text style={styles.spineTitle}>{item.raw_read.title ?? "(unreadable)"}</Text>
                <Text style={styles.spineAuthor}>{item.raw_read.author ?? ""}</Text>
                <Text style={[styles.badge, { color: STATUS_COLORS[item.status] }]}>
                  {STATUS_LABELS[item.status]}
                </Text>
                {item.error && <Text style={styles.errorText}>{item.error}</Text>}
              </View>
            </View>
          )}
        />
      )}
    </SafeAreaView>
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
