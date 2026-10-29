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

import { stars } from "../api";
import type { Draft, FocusTarget, Review, SearchMarker } from "../types";

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

const iconCache = new Map<number, DivIcon>();

function markerIcon(rating: number): DivIcon {
  let icon = iconCache.get(rating);
  if (!icon) {
    const color = STAR_COLORS[rating] || "#2563eb";
    icon = L.divIcon({
      className: "custom-marker",
      html:
        `<div style="width:32px;height:32px;border-radius:50% 50% 50% 0;` +
        `background:${color};color:white;display:flex;align-items:center;` +
        `justify-content:center;font-weight:700;font-size:13px;` +
        `box-shadow:0 2px 6px rgba(0,0,0,.3);transform:rotate(-45deg);` +
        `border:2px solid white;">` +
        `<span style="transform:rotate(45deg)">${rating}</span></div>`,
      iconSize: [32, 32],
      iconAnchor: [16, 32],
      popupAnchor: [0, -32],
    });
    iconCache.set(rating, icon);
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
 * A single review marker. The position/icon/handlers props are memoized:
 * react-leaflet compares `position` by reference and would otherwise call
 * `setLatLng` on every render — which re-fires the marker's `move` event
 * and makes an open popup auto-pan the map back to itself.
 */
function ReviewMarker({
  review,
  onSelect,
}: {
  review: Review;
  onSelect: (review: Review) => void;
}) {
  const position = useMemo<[number, number]>(
    () => [review.latitude, review.longitude],
    [review.latitude, review.longitude],
  );
  const icon = markerIcon(review.rating);
  const handlers = useMemo<LeafletEventHandlerFnMap>(
    () => ({ click: () => onSelect(review) }),
    [onSelect, review],
  );
  // Memoized: react-leaflet calls popup.update() whenever the children
  // identity changes while the popup is open, and Leaflet's update()
  // auto-pans the map to keep the popup visible — which would drag the
  // map back whenever an unrelated re-render happens.
  const popup = useMemo(
    () => (
      <>
        <strong>{review.place_name || "Unnamed"}</strong>
        <br />
        <span className="popup-stars">{stars(review.rating)}</span>
        <br />
        {review.content.substring(0, 80)}…
        <br />
        <small>by {review.display_name || review.username}</small>
      </>
    ),
    [
      review.place_name,
      review.rating,
      review.content,
      review.display_name,
      review.username,
    ],
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
}

/** The Leaflet map: OSM tiles, coloured review markers, placement marker. */
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
}: MapViewProps) {
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

      {reviews.map((r) => (
        <ReviewMarker key={r.id} review={r} onSelect={onSelectReview} />
      ))}

      {draftPos && (
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
