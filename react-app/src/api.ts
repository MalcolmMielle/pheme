/** API helpers — all endpoints are same-origin (Vite proxies them in dev). */

import type { MapBounds, Me, NominatimResult, Review } from "./types";

/** Current session user, or null when logged out (401). */
export async function fetchMe(): Promise<Me | null> {
  const resp = await fetch("/api/me", {
    headers: { Accept: "application/json" },
  });
  if (resp.status === 401) return null;
  if (!resp.ok) throw new Error(`GET /api/me failed: ${resp.status}`);
  return resp.json();
}

/** Reviews within the given map bounds. */
export async function fetchReviews(bounds: MapBounds): Promise<Review[]> {
  const params = new URLSearchParams({
    min_lat: String(bounds.getSouth()),
    max_lat: String(bounds.getNorth()),
    min_lng: String(bounds.getWest()),
    max_lng: String(bounds.getEast()),
  });
  const resp = await fetch(`/api/reviews?${params}`, {
    headers: { Accept: "application/json" },
  });
  if (!resp.ok) throw new Error(`GET /api/reviews failed: ${resp.status}`);
  return resp.json();
}

export interface CreateReviewPayload {
  content: string;
  rating: number;
  latitude: number;
  longitude: number;
  place_name: string;
  place_address: string;
}

/**
 * POST a new review. Resolves with the raw Response so the caller can
 * distinguish 401 (logged out → redirect to /login) from other errors.
 */
export async function createReview(
  payload: CreateReviewPayload,
): Promise<Response> {
  return fetch("/api/reviews", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify(payload),
  });
}

/** Place search via the server's Nominatim proxy (avoids exposing user IPs).
 *  Callers debounce — Nominatim usage policy. */
export async function searchPlaces(query: string): Promise<NominatimResult[]> {
  const resp = await fetch(`/api/geocode?q=${encodeURIComponent(query)}&limit=5`);
  if (!resp.ok) return [];
  return resp.json();
}

/** Reverse geocode via the server's Nominatim proxy — display name or null. */
export async function reverseGeocode(
  lat: number,
  lng: number,
): Promise<string | null> {
  const resp = await fetch(`/api/reverse-geocode?lat=${lat}&lon=${lng}`);
  if (!resp.ok) return null;
  const data = await resp.json();
  return typeof data.display_name === "string" ? data.display_name : null;
}

/** "★★★☆☆" for a 1–5 rating. */
export function stars(rating: number): string {
  return "★".repeat(rating) + "☆".repeat(5 - rating);
}

/** "4.5" for 4.5, "5" for 5 — label shown inside markers / next to averages. */
export function formatRating(rating: number): string {
  const rounded = Math.round(rating * 10) / 10;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
}
