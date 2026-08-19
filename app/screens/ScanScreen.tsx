import { useEffect, useRef, useState } from "react";
import * as ImagePicker from "expo-image-picker";
import { ActivityIndicator, Button, Platform, StyleSheet, Text, View } from "react-native";

import { scanImage } from "../api";
import { buildScanSession } from "../session";
import { ScanSession } from "../types";

type LocalState = { phase: "idle" } | { phase: "uploading" } | { phase: "processing" } | { phase: "error"; message: string };

export default function ScanScreen({ onScanComplete }: { onScanComplete: (session: ScanSession) => void }) {
  const [state, setState] = useState<LocalState>({ phase: "idle" });
  const webFileInputRef = useRef<HTMLInputElement | null>(null);

  async function uploadImage(source: string | File) {
    setState({ phase: "uploading" });

    try {
      const scan = await scanImage(source);
      setState({ phase: "processing" });
      const session = await buildScanSession(scan);
      setState({ phase: "idle" });
      onScanComplete(session);
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

  const busy = state.phase === "uploading" || state.phase === "processing";

  return (
    <View style={styles.container}>
      <Text style={styles.heading}>Scan a shelf</Text>

      <View style={styles.buttonRow}>
        {Platform.OS === "web" ? (
          // No camera on a laptop - a "Take Photo" button here would just
          // open the same file dialog, which is worse than not having it.
          <Button title="Choose Photo" onPress={pickPhotoWeb} disabled={busy} />
        ) : (
          <>
            <Button title="Take Photo" onPress={takePhoto} disabled={busy} />
            <Button title="Choose Photo" onPress={pickFromLibrary} disabled={busy} />
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

      {state.phase === "idle" && (
        <View style={styles.centered}>
          <Text style={styles.hint}>Take or choose a photo of a bookshelf to scan it.</Text>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    paddingTop: 12,
  },
  heading: {
    fontSize: 20,
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
});
