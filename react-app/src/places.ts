/** Place grouping helpers — shared by the map markers and the place panel. */

import type { Review } from "./types";

/** A place on the map: all reviews that share (nearly) the same coordinates. */
export interface ReviewPlace {
  key: string;
  lat: number;
  lng: number;
  name: string;
  address: string;
  reviews: Review[];
  avgRating: number;
}

/**
 * Place-bucket precision (decimal places of lat/lng). Defaults to 4 (~11 m)
 * and is set from the server's /api/meta (`place_decimals`, the server's
 * PLACE_DECIMALS runtime parameter) at startup — see configurePlaceDecimals.
 */
let placeDecimals = 4;

/** Set the place-bucket precision from the server's /api/meta. */
export function configurePlaceDecimals(decimals: number): void {
  if (Number.isInteger(decimals) && decimals >= 1 && decimals <= 8) {
    placeDecimals = decimals;
  }
}

/**
 * Bucket key for "same place": coordinates to `placeDecimals` decimal
 * places, which covers reviews posted via place search (identical
 * Nominatim coordinates) and nearby map clicks.
 */
export function placeKey(lat: number, lng: number): string {
  return `${lat.toFixed(placeDecimals)},${lng.toFixed(placeDecimals)}`;
}

/**
 * Display label for an OSM tag value — mirrors the server's _humanize_label:
 * "motorcycle_parking" → "Motorcycle parking", "saddle" → "Pass".
 */
export function humanizeTag(value: string): string {
  if (value === "saddle") return "Pass";
  const s = value.replace(/_/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/**
 * Short address line from a place's OSM addr:* tags —
 * "8 Rue de la Mouline, 1007 Lausanne". Falls back to `fallback` (the
 * reverse-geocoded address of the clicked point) when the place has no
 * addr:* tags of its own.
 */
export function addressFromTags(
  tags: Record<string, string> | undefined,
  fallback = "",
): string {
  if (!tags) return fallback;
  const street = [tags["addr:housenumber"], tags["addr:street"]]
    .filter(Boolean)
    .join(" ");
  const city = [
    tags["addr:postcode"],
    tags["addr:city"] ?? tags["addr:town"] ?? tags["addr:village"],
  ]
    .filter(Boolean)
    .join(" ");
  return [street, city].filter(Boolean).join(", ") || fallback;
}

/**
 * Nominatim-style structured address (house_number, road, postcode, city)
 * from a place's OSM addr:* tags — used as the panel's `addressDetails` when
 * the place has an address of its own (instead of the clicked point's).
 * Undefined when there are no addr:* tags.
 */
export function addressDetailsFromTags(
  tags: Record<string, string> | undefined,
): Record<string, string> | undefined {
  if (!tags) return undefined;
  const out: Record<string, string> = {};
  if (tags["addr:housenumber"]) out.house_number = tags["addr:housenumber"];
  if (tags["addr:street"]) out.road = tags["addr:street"];
  if (tags["addr:postcode"]) out.postcode = tags["addr:postcode"];
  const city = tags["addr:city"] ?? tags["addr:town"] ?? tags["addr:village"];
  if (city) out.city = city;
  return Object.keys(out).length > 0 ? out : undefined;
}

/** All reviews at the same place as the given point. */
export function reviewsAtPlace(
  reviews: Review[],
  lat: number,
  lng: number,
): Review[] {
  const key = placeKey(lat, lng);
  return reviews.filter((r) => placeKey(r.latitude, r.longitude) === key);
}

/** Running totals while grouping reviews into a place. */
interface PlaceGroup {
  reviews: Review[];
  latSum: number;
  lngSum: number;
  ratingSum: number;
  /** Non-empty place name → how many reviews in the group use it. */
  names: Map<string, number>;
  address: string;
}

/**
 * Group reviews into places — one marker per place instead of one per
 * review.
 */
export function groupReviewsByPlace(reviews: Review[]): ReviewPlace[] {
  const groups = new Map<string, PlaceGroup>();
  for (const r of reviews) {
    const key = placeKey(r.latitude, r.longitude);
    let g = groups.get(key);
    if (!g) {
      g = {
        reviews: [],
        latSum: 0,
        lngSum: 0,
        ratingSum: 0,
        names: new Map(),
        address: "",
      };
      groups.set(key, g);
    }
    g.reviews.push(r);
    g.latSum += r.latitude;
    g.lngSum += r.longitude;
    g.ratingSum += r.rating;
    const name = r.place_name.trim();
    if (name) g.names.set(name, (g.names.get(name) ?? 0) + 1);
    if (!g.address && r.place_address) g.address = r.place_address;
  }
  return [...groups.entries()].map(([key, g]) => {
    const n = g.reviews.length;
    // Most common non-empty place name in the group.
    const name = [...g.names.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? "";
    return {
      key,
      lat: g.latSum / n,
      lng: g.lngSum / n,
      name,
      address: g.address,
      reviews: g.reviews,
      avgRating: g.ratingSum / n,
    };
  });
}
