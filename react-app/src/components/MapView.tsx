import L from "leaflet";
import markerIcon2xUrl from "leaflet/dist/images/marker-icon-2x.png?url";
import markerIconUrl from "leaflet/dist/images/marker-icon.png?url";
import markerShadowUrl from "leaflet/dist/images/marker-shadow.png?url";
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

import { formatRating, ratingColor } from "../api";
import { groupReviewsByPlace, placeKey, type ReviewPlace } from "../places";
import Stars from "./Stars";
import type {
  Draft,
  FocusTarget,
  PlaceSelection,
  Review,
  SearchMarker,
} from "../types";

// Vite inlines leaflet.css's marker-icon.png as a data URI, so Leaflet's
// runtime path auto-detection (_detectIconPath) finds neither a
// "marker-icon.png" suffix nor a leaflet.css <link> and falls back to the
// relative "marker-icon.png" — which the SPA catch-all answers with
// index.html, so default-icon markers (map click, draft pin) render as
// broken images. Point the default icon at the bundled assets explicitly.
L.Icon.Default.mergeOptions({
  iconUrl: markerIconUrl,
  iconRetinaUrl: markerIcon2xUrl,
  shadowUrl: markerShadowUrl,
});

const DEFAULT_CENTER: [number, number] = [37.7749, -122.4194];
const DEFAULT_ZOOM = 13;
/** Only re-focus the map if the target is further away than this (degrees). */
const FOCUS_EPSILON = 0.001;
/** Always zoom in to at least this level when focusing a target. */
const FOCUS_MIN_ZOOM = 14;

const iconCache = new Map<string, DivIcon>();

/**
 * Teardrop marker colored by (possibly fractional) average rating — the
 * color comes from the nearest whole star, the label shows the average.
 * The inner `marker-pin` div carries the pop-in animation (Leaflet owns the
 * outer element's transform for positioning).
 */
function markerIcon(avgRating: number): DivIcon {
  const label = formatRating(avgRating);
  const color = ratingColor(avgRating);
  // Key by color AND label: the label keeps one decimal ("4.5") while the
  // color uses the nearest whole star, so 4.49 and 4.51 share a label but
  // get different colors.
  const key = `${color}:${label}`;
  let icon = iconCache.get(key);
  if (!icon) {
    icon = L.divIcon({
      className: "custom-marker",
      html:
        `<div class="marker-pin" style="width:32px;height:32px;border-radius:50% 50% 50% 0;` +
        `background:${color};color:white;display:flex;align-items:center;` +
        `justify-content:center;font-weight:700;font-size:13px;` +
        `box-shadow:0 2px 6px rgba(0,0,0,.3);transform:rotate(-45deg);` +
        `border:2px solid white;">` +
        `<span style="transform:rotate(45deg)">${label}</span></div>`,
      iconSize: [32, 32],
      iconAnchor: [16, 32],
      popupAnchor: [0, -32],
    });
    iconCache.set(key, icon);
  }
  return icon;
}

interface MapControllerProps {
  formOpen: boolean;
  focus: FocusTarget | null;
  onBoundsChange: (bounds: L.LatLngBounds) => void;
  onMapClick: (lat: number, lng: number) => void;
  onMapSelect: (lat: number, lng: number) => void;
}

/**
 * Wires Leaflet events to React: bounds reload on moveend, map click to
 * place a review pin (while the form is open) or to select the clicked
 * spot as a place (otherwise), and focus targets.
 */
function MapController({
  formOpen,
  focus,
  onBoundsChange,
  onMapClick,
  onMapSelect,
}: MapControllerProps) {
  const map = useMap();

  // Keep the latest props in a ref so the (stable) Leaflet handlers never
  // go stale.
  const latest = useRef({ formOpen, onBoundsChange, onMapClick, onMapSelect });
  useEffect(() => {
    latest.current = { formOpen, onBoundsChange, onMapClick, onMapSelect };
  });

  const events = useMemo<LeafletEventHandlerFnMap>(
    () => ({
      moveend: () => latest.current.onBoundsChange(map.getBounds()),
      click: (e: LeafletEvent) => {
        const mouse = e as LeafletMouseEvent;
        // Ignore clicks on markers/popups — they have their own handlers.
        const target = mouse.originalEvent?.target as HTMLElement | undefined;
        if (target?.closest(".leaflet-marker-icon, .leaflet-popup")) return;
        const { formOpen, onMapClick, onMapSelect } = latest.current;
        if (formOpen) {
          onMapClick(mouse.latlng.lat, mouse.latlng.lng);
        } else {
          onMapSelect(mouse.latlng.lat, mouse.latlng.lng);
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
    if (dist > FOCUS_EPSILON || map.getZoom() < FOCUS_MIN_ZOOM) {
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
 * Clicking the marker opens the place panel (left sidebar) — the popup
 * just shows the place's name and average. The position/icon/handlers
 * props are memoized: react-leaflet compares `position` by reference and
 * would otherwise call `setLatLng` on every render — which re-fires the
 * marker's `move` event and makes an open popup auto-pan the map back to
 * itself.
 */
function PlaceMarker({
  place,
  formOpen,
  onSelectPlace,
  onRatePlace,
}: {
  place: ReviewPlace;
  /** True while the review form is open — hide the popup's rate button. */
  formOpen: boolean;
  onSelectPlace: (place: PlaceSelection) => void;
  onRatePlace: (place: PlaceSelection) => void;
}) {
  const position = useMemo<[number, number]>(
    () => [place.lat, place.lng],
    [place.lat, place.lng],
  );
  const icon = markerIcon(place.avgRating);
  // Pass a review's coordinates (same place bucket as the group) so the
  // place panel finds this place's reviews and no extra marker is drawn.
  const handlers = useMemo<LeafletEventHandlerFnMap>(
    () => ({
      click: () =>
        onSelectPlace({
          lat: place.reviews[0].latitude,
          lng: place.reviews[0].longitude,
          name: place.name,
          address: place.address,
        }),
    }),
    [onSelectPlace, place],
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
        <Stars value={place.avgRating} size={13} />{" "}
        <small>
          {formatRating(place.avgRating)} avg · {place.reviews.length} review
          {place.reviews.length !== 1 ? "s" : ""}
        </small>
        {!formOpen && (
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
        )}
      </>
    ),
    [place, formOpen, onRatePlace],
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
  // Memoized children — see PlaceMarker for why.
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
  onMapSelect: (lat: number, lng: number) => void;
  onDraftMove: (lat: number, lng: number) => void;
  onSelectPlace: (place: PlaceSelection) => void;
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
  onMapSelect,
  onDraftMove,
  onSelectPlace,
  onRatePlace,
}: MapViewProps) {
  // One marker per place, colored by the place's average rating.
  const places = useMemo(() => groupReviewsByPlace(reviews), [reviews]);

  // The selected place's own marker is enough when it coincides with a
  // reviewed place — don't draw a second marker on top.
  const showSearchMarker =
    searchMarker != null &&
    !places.some((p) => p.key === placeKey(searchMarker.lat, searchMarker.lng));

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
        onMapSelect={onMapSelect}
      />

      {places.map((p) => (
        <PlaceMarker
          key={p.key}
          place={p}
          formOpen={formOpen}
          onSelectPlace={onSelectPlace}
          onRatePlace={onRatePlace}
        />
      ))}

      {/* Placement pin only for a free draft — a place-bound draft is
          locked and already marked by the place / search marker. */}
      {draftPos && !draft?.locked && (
        <Marker position={draftPos} draggable eventHandlers={draftHandlers} />
      )}

      {showSearchMarker && searchMarker && (
        <SearchMarkerView
          key={`${searchMarker.lat},${searchMarker.lng}`}
          marker={searchMarker}
        />
      )}
    </MapContainer>
  );
}
