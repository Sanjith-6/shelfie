import { SpineStatus } from "./types";

export const STATUS_LABELS: Record<SpineStatus, string> = {
  auto: "Added",
  review: "Needs review",
  unmatched: "Unmatched",
  failed: "Failed",
};

export const STATUS_COLORS: Record<SpineStatus, string> = {
  auto: "#2e7d32",
  review: "#ef6c00",
  unmatched: "#616161",
  failed: "#c62828",
};
