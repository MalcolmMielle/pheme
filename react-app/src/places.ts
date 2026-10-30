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
 * Bucket key for "same place": coordinates to 4 decimal places (~11 m),
 * which covers reviews posted via place search (identical Nominatim
 * coordinates) and nearby map clicks.
 */
export function placeKey(lat: number, lng: number): string {
  return `${lat.toFixed(4)},${lng.toFixed(4)}`;
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
