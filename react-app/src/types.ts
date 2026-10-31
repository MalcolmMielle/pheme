/** Shared TypeScript types for the Federated Reviews SPA. */

/** Review list scope: everything, own + followed actors, or local server only. */
export type ReviewScope = "all" | "following" | "local";

/** A review as returned by `GET /api/reviews`. */
export interface Review {
  id: number;
  actor_id: number;
  ap_id: string;
  content: string;
  rating: number;
  latitude: number;
  longitude: number;
  place_name: string;
  place_address: string;
  created_at: string;
  username: string;
  display_name: string;
  actor_uri: string;
}

/** The logged-in user, from `GET /api/me`. */
export interface Me {
  id: number;
  username: string;
  display_name: string;
  /** True for admin accounts — the SPA shows the admin panel to them. */
  is_admin: boolean;
  /** This server's actor URI for the user, e.g. "http://localhost:8000/actor/alice". */
  actor_uri: string;
}

/** One entry of the logged-in user's following list, from `GET /api/me/following`. */
export interface FollowingEntry {
  actor_uri: string;
  username: string;
  display_name: string;
}

/** A local account as listed by `GET /api/admin/users` (admin only). */
export interface AdminUser {
  id: number;
  username: string;
  display_name: string;
  is_admin: boolean;
  /** Suspended accounts can't log in and their sessions are invalidated. */
  is_suspended: boolean;
  created_at: string;
}

/** A Nominatim search / reverse-geocode result. */
export interface NominatimResult {
  lat: string;
  lon: string;
  display_name: string;
  type?: string;
  category?: string;
}

/** Where a new review is being placed (review-form state). */
export interface Draft {
  lat: number | null;
  lng: number | null;
  placeName: string;
  placeAddress: string;
  /** Label for the "selected location" chip: place name or coordinates. */
  label: string;
  /**
   * True when the draft is bound to a picked place — map clicks and pin
   * dragging must not move it. False for a blank form, where the location
   * is chosen by clicking the map.
   */
  locked: boolean;
}

/** A place picked in the global map search — shown as a marker + popup. */
export interface SearchMarker {
  lat: number;
  lng: number;
  name: string;
  address: string;
}

/**
 * A place (from the global search or a map place marker) used to pre-fill
 * the review form, so the user doesn't have to search for it again.
 */
export interface PlaceSelection {
  lat: number;
  lng: number;
  name: string;
  address: string;
}

/**
 * MapPage asks the map to focus this point, with padding so the point lands
 * in the visible area (desktop: beside the sidebar/panel; mobile: above the
 * bottom sheet and below the floating search bar).
 */
export interface FocusTarget {
  lat: number;
  lng: number;
  zoom: number;
  padLeft: number;
  padTop: number;
  padRight: number;
  padBottom: number;
}

/** Structural subset of Leaflet's LatLngBounds (avoids importing Leaflet here). */
export interface MapBounds {
  getSouth(): number;
  getNorth(): number;
  getWest(): number;
  getEast(): number;
}
