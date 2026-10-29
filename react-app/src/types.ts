/** Shared TypeScript types for the Federated Reviews SPA. */

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
  /** Session CSRF token — include it in form-encoded posts (e.g. logout). */
  csrf_token: string;
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
}

/** A place picked in the global map search — shown as a marker + popup. */
export interface SearchMarker {
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
