import { useState } from "react";
import { StatusBar } from "expo-status-bar";
import { Button, SafeAreaView, StyleSheet, Text, View } from "react-native";

import LibraryScreen from "./screens/LibraryScreen";
import ReviewScreen from "./screens/ReviewScreen";
import ScanScreen from "./screens/ScanScreen";
import { ScanSession } from "./types";

type Screen = "scan" | "review" | "library";

export default function App() {
  const [screen, setScreen] = useState<Screen>("scan");
  const [session, setSession] = useState<ScanSession | null>(null);

  function handleScanComplete(newSession: ScanSession) {
    setSession(newSession);
    const hasPending = newSession.queue.some((item) => item.outcome === null);
    setScreen(hasPending ? "review" : "scan");
  }

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar style="auto" />
      <Text style={styles.heading}>Shelfie</Text>

      <View style={styles.tabBar}>
        <Button title="Scan" onPress={() => setScreen("scan")} />
        <Button title="Review" onPress={() => setScreen("review")} />
        <Button title="Library" onPress={() => setScreen("library")} />
      </View>

      <View style={styles.screen}>
        {screen === "scan" && <ScanScreen onScanComplete={handleScanComplete} />}
        {screen === "review" && <ReviewScreen session={session} onSessionChange={setSession} />}
        {screen === "library" && <LibraryScreen />}
      </View>
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
    marginBottom: 8,
  },
  tabBar: {
    flexDirection: "row",
    justifyContent: "space-around",
    marginBottom: 8,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: "#ddd",
    paddingBottom: 8,
  },
  screen: {
    flex: 1,
  },
});
