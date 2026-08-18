// Django runs on this machine's LAN IP, not localhost - on a physical
// phone, "localhost" would mean the phone itself, not this computer. Find
// your own IP with `ipconfig` (Windows) or `ifconfig`/`ipconfig getifaddr en0`
// (mac/Linux) and update this when it changes (e.g. a different network).
export const API_BASE_URL = "http://10.0.0.87:8000";
