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

/**
 * CSRF helpers — the server uses starlette-csrf (double-submit cookie): every
 * unsafe request that carries the session cookie must send an `X-CSRFToken`
 * header matching the `csrftoken` cookie. The cookie is readable by JS.
 */
function csrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

function csrfHeaders(): Record<string, string> {
  return { "X-CSRFToken": csrfToken() };
}

/**
 * fetch wrapper for unsafe requests: on a 403 CSRF failure (e.g. the
 * csrftoken cookie was signed with an old SECRET_KEY after a server
 * restart), drop the stale cookie, fetch a fresh one, and retry once.
 * Non-CSRF 403s (e.g. not an admin) are returned unchanged.
 */
async function fetchWithCsrf(input: string, init: RequestInit): Promise<Response> {
  const resp = await fetch(input, init);
  if (resp.status !== 403) return resp;
  const body = await resp.text();
  if (!body.includes("CSRF")) {
    return new Response(body, {
      status: resp.status,
      statusText: resp.statusText,
      headers: resp.headers,
    });
  }
  document.cookie = "csrftoken=; max-age=0; path=/";
  await fetch("/api/meta", { headers: { Accept: "application/json" } });
  const headers = new Headers(init.headers);
  headers.set("X-CSRFToken", csrfToken());
  return fetch(input, { ...init, headers });
}

/** Log out (POST /logout with the CSRF header), then go back to the map. */
export async function logout(): Promise<void> {
  await fetchWithCsrf("/logout", {
    method: "POST",
    headers: { ...csrfHeaders(), Accept: "application/json" },
  });
  window.location.href = "/";
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
  return fetchWithCsrf("/api/reviews", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      ...csrfHeaders(),
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

/** Public server metadata, from `GET /api/meta`. */
export interface ServerMeta {
  registration_mode: string;
}

/** Server metadata (registration mode) — used to hide the Register button. */
export async function fetchMeta(): Promise<ServerMeta> {
  const resp = await fetch("/api/meta", {
    headers: { Accept: "application/json" },
  });
  if (!resp.ok) throw new Error(`GET /api/meta failed: ${resp.status}`);
  return resp.json();
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
 * Form-encoded POST with the X-CSRFToken header (starlette-csrf
 * double-submit) — required for every unsafe request made while logged in.
 * Resolves with the raw Response so callers can read the status.
 */
function formPost(path: string, fields: Record<string, string>): Promise<Response> {
  return fetchWithCsrf(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      Accept: "application/json",
      ...csrfHeaders(),
    },
    body: new URLSearchParams(fields),
  });
}

/**
 * Follow an actor on another server by handle (user@domain, resolved via
 * the remote server's WebFinger) or by full actor URI. Sends a signed
 * Follow activity to the remote inbox; the remote server auto-accepts.
 */
export function followActor(target: string): Promise<Response> {
  return formPost("/api/follow", { target });
}

/**
 * Unfollow an actor by URI or handle. Removes the local follow and sends
 * a signed Undo activity to the remote inbox (best effort).
 */
export function unfollowActor(target: string): Promise<Response> {
  return formPost("/api/unfollow", { target });
}

export interface NewUserPayload {
  username: string;
  displayName: string;
  password: string;
  /** Create the account directly as an admin. */
  isAdmin: boolean;
}

/** Create a local account (admin only); isAdmin makes it an admin account. */
export function createUser(payload: NewUserPayload): Promise<Response> {
  return formPost("/api/admin/users", {
    username: payload.username,
    display_name: payload.displayName,
    password: payload.password,
    is_admin: payload.isAdmin ? "true" : "false",
  });
}

/** Promote (makeAdmin=true) or demote a local account (admin only). */
export function setUserAdmin(
  userId: number,
  makeAdmin: boolean,
): Promise<Response> {
  return formPost(
    `/api/admin/users/${userId}/${makeAdmin ? "promote" : "demote"}`,
    {},
  );
}

/** Suspend (suspended=true) or unsuspend a local account (admin only). */
export function setUserSuspended(
  userId: number,
  suspended: boolean,
): Promise<Response> {
  return formPost(
    `/api/admin/users/${userId}/${suspended ? "suspend" : "unsuspend"}`,
    {},
  );
}

/** Delete a local account and its local content (admin only). */
export function deleteUser(userId: number): Promise<Response> {
  return fetchWithCsrf(`/api/admin/users/${userId}`, {
    method: "DELETE",
    headers: { ...csrfHeaders(), Accept: "application/json" },
  });
}

/** One invite code, from `GET /api/admin/invites` (admin only). */
export interface Invite {
  id: number;
  code: string;
  created_by: string | null;
  used_by: string | null;
  used_at: string | null;
  created_at: string;
  expires_at: string | null;
  /** Shareable registration URL with the code pre-filled. */
  register_url: string;
}

export interface AdminInviteList {
  invites: Invite[];
  registration_mode: string;
}

/** List invite codes (admin only). */
export async function fetchAdminInvites(): Promise<AdminInviteList> {
  const resp = await fetch("/api/admin/invites", {
    headers: { Accept: "application/json" },
  });
  if (!resp.ok) throw new Error(`GET /api/admin/invites failed: ${resp.status}`);
  return resp.json();
}

/** Create a one-time invite code (admin only); expiresInDays null = never. */
export function createInvite(expiresInDays: number | null): Promise<Response> {
  return formPost(
    "/api/admin/invites",
    expiresInDays === null ? {} : { expires_in_days: String(expiresInDays) },
  );
}

/** Revoke an unused invite code (admin only). */
export function deleteInvite(inviteId: number): Promise<Response> {
  return fetchWithCsrf(`/api/admin/invites/${inviteId}`, {
    method: "DELETE",
    headers: { ...csrfHeaders(), Accept: "application/json" },
  });
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

/**
 * Format a review's created_at for display. The API returns SQLite UTC
 * text ("2026-08-02 21:45:00") — no timezone marker — so it is parsed as
 * UTC. Falls back to the raw string if it can't be parsed.
 */
export function formatDate(value: string): string {
  const normalized = value.includes("T") ? value : `${value.replace(" ", "T")}Z`;
  const d = new Date(normalized);
  if (Number.isNaN(d.getTime())) return value;
  const date = d.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
  const time = d.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
  return `${date}, ${time}`;
}
