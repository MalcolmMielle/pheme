/** API helpers — all endpoints are same-origin (Vite proxies them in dev). */

import type {
  AdminUser,
  FollowingEntry,
  MapBounds,
  Me,
  NominatimResult,
  Review,
  ReviewScope,
} from "./types";

/** Error from an API call, carrying the HTTP status (e.g. 401 → re-login). */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

/** Current session user, or null when logged out (401). */
export async function fetchMe(): Promise<Me | null> {
  const resp = await fetch("/api/me", {
    headers: { Accept: "application/json" },
  });
  if (resp.status === 401) return null;
  if (!resp.ok) throw new Error(`GET /api/me failed: ${resp.status}`);
  return resp.json();
}

/** The logged-in user's accepted follows, or null when logged out (401). */
export async function fetchMyFollowing(): Promise<FollowingEntry[] | null> {
  const resp = await fetch("/api/me/following", {
    headers: { Accept: "application/json" },
  });
  if (resp.status === 401) return null;
  if (!resp.ok) throw new Error(`GET /api/me/following failed: ${resp.status}`);
  const data = await resp.json();
  return data.following;
}

/** Reviews within the given map bounds. Pass a signal to cancel the request.
 *  scope "following" asks the server for own + followed actors' reviews
 *  (401 when logged out). */
export async function fetchReviews(
  bounds: MapBounds,
  signal?: AbortSignal,
  scope: ReviewScope = "all",
): Promise<Review[]> {
  const params = new URLSearchParams({
    min_lat: String(bounds.getSouth()),
    max_lat: String(bounds.getNorth()),
    min_lng: String(bounds.getWest()),
    max_lng: String(bounds.getEast()),
  });
  if (scope !== "all") params.set("scope", scope);
  const resp = await fetch(`/api/reviews?${params}`, {
    headers: { Accept: "application/json" },
    signal,
  });
  if (!resp.ok) throw new ApiError(resp.status, `GET /api/reviews failed: ${resp.status}`);
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

/** ── admin endpoints (admin session required) ───────────────────────── */

export interface AdminUserList {
  users: AdminUser[];
  admin_count: number;
}

/** Local accounts with their admin flag. Throws on 401/403. */
export async function fetchAdminUsers(): Promise<AdminUserList> {
  const resp = await fetch("/api/admin/users", {
    headers: { Accept: "application/json" },
  });
  if (!resp.ok) throw new Error(`GET /api/admin/users failed: ${resp.status}`);
  return resp.json();
}

/**
 * Form-encoded POST with the session CSRF token — the CSRF middleware
 * only validates form posts, so these actions go through here.
 * Resolves with the raw Response so callers can read the status.
 */
function formPost(
  path: string,
  fields: Record<string, string>,
  csrfToken: string,
): Promise<Response> {
  return fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      Accept: "application/json",
    },
    body: new URLSearchParams({ ...fields, csrf_token: csrfToken }),
  });
}

/**
 * Follow an actor on another server by handle (user@domain, resolved via
 * the remote server's WebFinger) or by full actor URI. Sends a signed
 * Follow activity to the remote inbox; the remote server auto-accepts.
 */
export function followActor(
  target: string,
  csrfToken: string,
): Promise<Response> {
  return formPost("/api/follow", { target }, csrfToken);
}

/**
 * Unfollow an actor by URI or handle. Removes the local follow and sends
 * a signed Undo activity to the remote inbox (best effort).
 */
export function unfollowActor(
  target: string,
  csrfToken: string,
): Promise<Response> {
  return formPost("/api/unfollow", { target }, csrfToken);
}

export interface NewUserPayload {
  username: string;
  displayName: string;
  password: string;
  /** Create the account directly as an admin. */
  isAdmin: boolean;
}

/** Create a local account (admin only); isAdmin makes it an admin account. */
export function createUser(
  payload: NewUserPayload,
  csrfToken: string,
): Promise<Response> {
  return formPost(
    "/api/admin/users",
    {
      username: payload.username,
      display_name: payload.displayName,
      password: payload.password,
      is_admin: payload.isAdmin ? "true" : "false",
    },
    csrfToken,
  );
}

/** Promote (makeAdmin=true) or demote a local account (admin only). */
export function setUserAdmin(
  userId: number,
  makeAdmin: boolean,
  csrfToken: string,
): Promise<Response> {
  return formPost(
    `/api/admin/users/${userId}/${makeAdmin ? "promote" : "demote"}`,
    {},
    csrfToken,
  );
}

/** "★★★☆☆" for a 1–5 rating. */
export function stars(rating: number): string {
  return "★".repeat(rating) + "☆".repeat(5 - rating);
}

/**
 * The server an actor is from, derived from their actor URI's host
 * ("https://remote.example/users/alice" → "remote.example").
 * Empty string if the URI can't be parsed.
 */
export function actorServer(actorUri: string): string {
  try {
    return new URL(actorUri).host;
  } catch {
    return "";
  }
}

/** "4.5" for 4.5, "5" for 5 — label shown inside markers / next to averages. */
export function formatRating(rating: number): string {
  const rounded = Math.round(rating * 10) / 10;
  return Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
}
