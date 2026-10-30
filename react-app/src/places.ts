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

/**
 * Group reviews into places — one marker per place instead of one per
 * review.
 */
export function groupReviewsByPlace(reviews: Review[]): ReviewPlace[] {
  const groups = new Map<string, Review[]>();
  for (const r of reviews) {
    const key = placeKey(r.latitude, r.longitude);
    const list = groups.get(key);
    if (list) list.push(r);
    else groups.set(key, [r]);
  }
  return [...groups.entries()].map(([key, list]) => {
    const lat = list.reduce((sum, r) => sum + r.latitude, 0) / list.length;
    const lng = list.reduce((sum, r) => sum + r.longitude, 0) / list.length;
    const avgRating = list.reduce((sum, r) => sum + r.rating, 0) / list.length;
    // Most common non-empty place name in the group.
    const names = new Map<string, number>();
    for (const r of list) {
      const name = r.place_name.trim();
      if (name) names.set(name, (names.get(name) ?? 0) + 1);
    }
    const name = [...names.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? "";
    const address = list.find((r) => r.place_address)?.place_address ?? "";
    return { key, lat, lng, name, address, reviews: list, avgRating };
  });
}
