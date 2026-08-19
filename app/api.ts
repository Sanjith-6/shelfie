import { API_BASE_URL } from "./config";
import { LibraryEntry, LibraryResolution, ScanResponse } from "./types";

export function cropImageUrl(cropUrl: string): string {
  return `${API_BASE_URL}${cropUrl}`;
}

// Native gives us a local file URI; web's file input gives us the File
// object directly. Both funnel through this one function from here on.
export async function scanImage(source: string | File): Promise<ScanResponse> {
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

  const response = await fetch(`${API_BASE_URL}/api/scan`, {
    method: "POST",
    body: formData,
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.message ?? `Scan failed (${response.status}).`);
  }

  return response.json();
}

export type AddToLibraryInput = {
  catalog_book: number | null;
  title: string;
  author: string;
  raw_title: string;
  raw_author: string;
  confidence: number | null;
  resolution: LibraryResolution;
};

export async function addToLibrary(input: AddToLibraryInput): Promise<LibraryEntry> {
  const response = await fetch(`${API_BASE_URL}/api/library`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.message ?? `Couldn't save to library (${response.status}).`);
  }

  return response.json();
}

export async function getLibrary(): Promise<LibraryEntry[]> {
  const response = await fetch(`${API_BASE_URL}/api/library`);
  if (!response.ok) {
    throw new Error(`Couldn't load library (${response.status}).`);
  }
  return response.json();
}

export async function deleteLibraryEntry(id: number): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/library/${id}`, { method: "DELETE" });
  if (!response.ok) {
    throw new Error(`Couldn't undo (${response.status}).`);
  }
}
