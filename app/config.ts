import { Platform } from "react-native";

// Only used on a physical device, where "localhost" would mean the phone
// itself, not this computer. This machine's IP has changed several times
// during development (once because it was tethered to a phone hotspot) -
// re-check it before each device-testing session rather than trusting this
// value:
//   Windows (PowerShell): (Get-NetIPAddress -InterfaceAlias "Wi-Fi" -AddressFamily IPv4).IPAddress
//   mac/Linux:            ipconfig getifaddr en0   (or `ifconfig`)
const LAN_IP = "172.20.10.3";

// The browser (`w`) always talks to localhost directly - it's running on
// this same machine, so there's no network hop and no IP to keep in sync.
export const API_BASE_URL =
  Platform.OS === "web" ? "http://localhost:8000" : `http://${LAN_IP}:8000`;
