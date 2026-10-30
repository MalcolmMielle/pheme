import L from "leaflet";
import type {
  DivIcon,
  LeafletEvent,
  LeafletEventHandlerFnMap,
  LeafletMouseEvent,
  Marker as LeafletMarker,
} from "leaflet";
import { useEffect, useMemo, useRef } from "react";
import {
  MapContainer,
  Marker,
  Popup,
  TileLayer,
  useMap,
  useMapEvents,
} from "react-leaflet";
import "leaflet/dist/leaflet.css";

import { formatRating, stars } from "../api";
import { groupReviewsByPlace } from "../places";
import type { ReviewPlace } from "../places";
import type {
  Draft,
  FocusTarget,
  PlaceSelection,
  Review,
  SearchMarker,
} from "../types";

const DEFAULT_CENTER: [number, number] = [37.7749, -122.4194];
const DEFAULT_ZOOM = 13;

/** Teardrop marker color by rating (ported from app.js). */
const STAR_COLORS: Record<number, string> = {
  1: "#ef4444",
  2: "#f97316",
  3: "#eab308",
  4: "#84cc16",
  5: "#22c55e",
};

const iconCache = new Map<string, DivIcon>();

/**
 * Teardrop marker colored by (possibly fractional) average rating — the
 * color comes from the nearest whole star, the label shows the average.
 */
function markerIcon(avgRating: number): DivIcon {
  const label = formatRating(avgRating);
  let icon = iconCache.get(label);
  if (!icon) {
    const star = Math.min(5, Math.max(1, Math.round(avgRating)));
    const color = STAR_COLORS[star] || "#2563eb";
    icon = L.divIcon({
      className: "custom-marker",
      html:
        `<div style="width:32px;height:32px;border-radius:50% 50% 50% 0;` +
        `background:${color};color:white;display:flex;align-items:center;` +
        `justify-content:center;font-weight:700;font-size:13px;` +
        `box-shadow:0 2px 6px rgba(0,0,0,.3);transform:rotate(-45deg);` +
        `border:2px solid white;">` +
        `<span style="transform:rotate(45deg)">${label}</span></div>`,
      iconSize: [32, 32],
      iconAnchor: [16, 32],
      popupAnchor: [0, -32],
    });
    iconCache.set(label, icon);
  }
  return icon;
}

interface MapControllerProps {
  formOpen: boolean;
  focus: FocusTarget | null;
  onBoundsChange: (bounds: L.LatLngBounds) => void;
  onMapClick: (lat: number, lng: number) => void;
}

/**
 * Wires Leaflet events to React: bounds reload on moveend, map click to
 * place a review (only while the form is open), and focus targets.
 */
function MapController({
  formOpen,
  focus,
  onBoundsChange,
  onMapClick,
}: MapControllerProps) {
  const map = useMap();

  // Keep the latest props in a ref so the (stable) Leaflet handlers never
  // go stale.
  const latest = useRef({ formOpen, onBoundsChange, onMapClick });
  useEffect(() => {
    latest.current = { formOpen, onBoundsChange, onMapClick };
  });

  const events = useMemo<LeafletEventHandlerFnMap>(
    () => ({
      moveend: () => latest.current.onBoundsChange(map.getBounds()),
      click: (e: LeafletEvent) => {
        const mouse = e as LeafletMouseEvent;
        // Ignore clicks on markers/popups — they have their own handlers.
        const target = mouse.originalEvent?.target as HTMLElement | undefined;
        if (target?.closest(".leaflet-marker-icon, .leaflet-popup")) return;
        if (latest.current.formOpen) {
          latest.current.onMapClick(mouse.latlng.lat, mouse.latlng.lng);
        }
      },
    }),
    [map],
  );
  useMapEvents(events);

  // Initial load (the old app called loadReviews() once at startup).
  useEffect(() => {
    latest.current.onBoundsChange(map.getBounds());
  }, [map]);

  // Focus a point (review selected / place picked), padding so the point
  // lands in the visible area even with the sidebar / a panel open.
  useEffect(() => {
    if (!focus) return;
    const center = map.getCenter();
    const dist =
      Math.abs(center.lat - focus.lat) + Math.abs(center.lng - focus.lng);
    // Only move the map if we're not already looking at this spot.
    if (dist > 0.001 || map.getZoom() < 14) {
      const point = L.latLng(focus.lat, focus.lng);
      map.fitBounds(L.latLngBounds([point, point]), {
        maxZoom: focus.zoom,
        paddingTopLeft: [focus.padLeft, focus.padTop],
        paddingBottomRight: [focus.padRight, focus.padBottom],
      });
    }
  }, [focus, map]);

  return null;
}

/**
 * One marker per place, colored by the average rating of all its reviews.
 * The popup lists every review at the place — clicking one opens its
 * detail; clicking the marker itself opens the latest review (reviews
 * arrive sorted by created_at DESC). The position/icon/handlers props are
 * memoized: react-leaflet compares `position` by reference and would
 * otherwise call `setLatLng` on every render — which re-fires the
 * marker's `move` event and makes an open popup auto-pan the map back to
 * itself.
 */
function PlaceMarker({
  place,
  onSelect,
  onRatePlace,
}: {
  place: ReviewPlace;
  onSelect: (review: Review) => void;
  onRatePlace: (place: PlaceSelection) => void;
}) {
  const position = useMemo<[number, number]>(
    () => [place.lat, place.lng],
    [place.lat, place.lng],
  );
  const icon = markerIcon(place.avgRating);
  const handlers = useMemo<LeafletEventHandlerFnMap>(
    () => ({ click: () => onSelect(place.reviews[0]) }),
    [onSelect, place],
  );
  // Memoized: react-leaflet calls popup.update() whenever the children
  // identity changes while the popup is open, and Leaflet's update()
  // auto-pans the map to keep the popup visible — which would drag the
  // map back whenever an unrelated re-render happens.
  const popup = useMemo(
    () => (
      <>
        <strong>{place.name || "Unnamed place"}</strong>
        <br />
        <span className="popup-stars">{stars(Math.round(place.avgRating))}</span>{" "}
        <small>
          {formatRating(place.avgRating)} avg · {place.reviews.length} review
          {place.reviews.length !== 1 ? "s" : ""}
        </small>
        <ul className="popup-review-list">
          {place.reviews.map((r) => (
            <li key={r.id}>
              <button
                type="button"
                className="popup-review-btn"
                onClick={() => onSelect(r)}
              >
                <span className="popup-stars">{stars(r.rating)}</span>{" "}
                {r.content.substring(0, 60)}
                {r.content.length > 60 ? "…" : ""}
                <br />
                <small>by {r.display_name || r.username}</small>
              </button>
            </li>
          ))}
        </ul>
        <button
          type="button"
          className="popup-rate-btn"
          onClick={() =>
            onRatePlace({
              lat: place.lat,
              lng: place.lng,
              name: place.name,
              address: place.address,
            })
          }
        >
          ＋ Add your review
        </button>
      </>
    ),
    [place, onSelect, onRatePlace],
  );
  return (
    <Marker position={position} icon={icon} eventHandlers={handlers}>
      <Popup>{popup}</Popup>
    </Marker>
  );
}

/** A place picked in the global map search — marker with an open popup. */
function SearchMarkerView({ marker }: { marker: SearchMarker }) {
  const ref = useRef<LeafletMarker | null>(null);
  const position = useMemo<[number, number]>(
    () => [marker.lat, marker.lng],
    [marker.lat, marker.lng],
  );
  useEffect(() => {
    ref.current?.openPopup();
  }, [marker]);
  // Memoized children — see ReviewMarker for why.
  const popup = useMemo(
    () => (
      <>
        <strong>{marker.name}</strong>
        <br />
        {marker.address}
      </>
    ),
    [marker.name, marker.address],
  );
  return (
    <Marker ref={ref} position={position}>
      <Popup>{popup}</Popup>
    </Marker>
  );
}

interface MapViewProps {
  reviews: Review[];
  draft: Draft | null;
  searchMarker: SearchMarker | null;
  formOpen: boolean;
  focus: FocusTarget | null;
  onBoundsChange: (bounds: L.LatLngBounds) => void;
  onMapClick: (lat: number, lng: number) => void;
  onDraftMove: (lat: number, lng: number) => void;
  onSelectReview: (review: Review) => void;
  onRatePlace: (place: PlaceSelection) => void;
}

/** The Leaflet map: OSM tiles, one avg-colored marker per place, placement marker. */
export default function MapView({
  reviews,
  draft,
  searchMarker,
  formOpen,
  focus,
  onBoundsChange,
  onMapClick,
  onDraftMove,
  onSelectReview,
  onRatePlace,
}: MapViewProps) {
  // One marker per place, colored by the place's average rating.
  const places = useMemo(() => groupReviewsByPlace(reviews), [reviews]);

  // Memoized so the draggable marker isn't snapped back mid-drag.
  const draftPos = useMemo<[number, number] | null>(
    () =>
      draft?.lat != null && draft?.lng != null ? [draft.lat, draft.lng] : null,
    [draft?.lat, draft?.lng],
  );
  const draftHandlers = useMemo<LeafletEventHandlerFnMap>(
    () => ({
      dragend: (e: LeafletEvent) => {
        const ll = (e.target as LeafletMarker).getLatLng();
        onDraftMove(ll.lat, ll.lng);
      },
    }),
    [onDraftMove],
  );

  return (
    <MapContainer
      className="map"
      center={DEFAULT_CENTER}
      zoom={DEFAULT_ZOOM}
      zoomControl
    >
      <TileLayer
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        maxZoom={19}
      />
      <MapController
        formOpen={formOpen}
        focus={focus}
        onBoundsChange={onBoundsChange}
        onMapClick={onMapClick}
      />

      {places.map((p) => (
        <PlaceMarker
          key={p.key}
          place={p}
          onSelect={onSelectReview}
          onRatePlace={onRatePlace}
        />
      ))}

      {/* Placement pin only for a free draft — a place-bound draft is
          locked and already marked by the place / search marker. */}
      {draftPos && !draft?.locked && (
        <Marker position={draftPos} draggable eventHandlers={draftHandlers} />
      )}

      {searchMarker && (
        <SearchMarkerView
          key={`${searchMarker.lat},${searchMarker.lng}`}
          marker={searchMarker}
        />
      )}
    </MapContainer>
  );
}
