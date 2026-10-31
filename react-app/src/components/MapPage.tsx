import type { LatLngBounds } from "leaflet";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, createReview, fetchReviews, reverseGeocode } from "../api";
import { useBottomSheet } from "../hooks/useBottomSheet";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { reviewsAtPlace } from "../places";
import MapView from "./MapView";
import PlacePanel from "./PlacePanel";
import ReviewForm from "./ReviewForm";
import ReviewList from "./ReviewList";
import SearchBox from "./SearchBox";
import type {
  Draft,
  FocusTarget,
  Me,
  NominatimResult,
  PlaceSelection,
  Review,
  ReviewScope,
} from "../types";

const SIDEBAR_W = 380;

interface MapPageProps {
  user: Me | null;
  userLoaded: boolean;
  onOpenProfile: () => void;
}

/**
 * The map page — layout, state and data flow for the whole app.
 * Ported from app/static/app.js.
 */
export default function MapPage({ user, userLoaded, onOpenProfile }: MapPageProps) {
  const [reviews, setReviews] = useState<Review[]>([]);
  /** "all" = everything in bounds; "following" = own + followed; "local" = this server. */
  const [scope, setScope] = useState<ReviewScope>("all");
  const [formOpen, setFormOpen] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  /**
   * Place picked via the global search: shown as a map marker and as the
   * place panel in the sidebar. Cleared when the search text is removed
   * or the panel is closed.
   */
  const [selectedPlace, setSelectedPlace] = useState<PlaceSelection | null>(null);
  const [focus, setFocus] = useState<FocusTarget | null>(null);

  const isMobile = useMediaQuery("(max-width: 768px)");
  const {
    sheet,
    dragDy,
    onPointerDown: onSheetPointerDown,
    onPointerMove: onSheetPointerMove,
    onPointerUp: onSheetPointerUp,
    onPointerCancel: onSheetPointerCancel,
    onHandleClick: onSheetHandleClick,
  } = useBottomSheet();

  const lastBounds = useRef<LatLngBounds | null>(null);
  /** Aborts the in-flight review load when the bounds change again. */
  const reviewsAbort = useRef<AbortController | null>(null);

  /**
   * Padding for map focus: desktop keeps the point clear of the sidebar;
   * mobile keeps it clear of the floating search bar and the bottom sheet.
   */
  const makeFocus = useCallback(
    (lat: number, lng: number, zoom: number): FocusTarget =>
      isMobile
        ? { lat, lng, zoom, padLeft: 30, padTop: 84, padRight: 30, padBottom: 164 }
        : {
          lat,
          lng,
          zoom,
          padLeft: SIDEBAR_W + 30,
          padTop: 30,
          padRight: 30,
          padBottom: 30,
        },
    [isMobile],
  );

  /**
   * Sheet state as shown — an open review form lives at the bottom of the
   * sheet, so the sheet is forced expanded on mobile to give it room.
   */
  const shownSheet = formOpen ? "expanded" : sheet;

  /** Live height while the mobile bottom sheet is being dragged. */
  const sheetBase = shownSheet === "expanded" ? "85dvh" : "var(--sheet-peek)";
  const sheetStyle =
    dragDy != null
      ? {
        height: `max(64px, min(calc(${sheetBase} - ${dragDy}px), 92dvh))`,
        transition: "none",
      }
      : undefined;

  const loadReviews = useCallback(
    async (bounds: LatLngBounds) => {
      lastBounds.current = bounds;
      // Cancel any in-flight load — only the response for the latest
      // bounds/scope may update the map.
      reviewsAbort.current?.abort();
      const ctrl = new AbortController();
      reviewsAbort.current = ctrl;
      try {
        setReviews(await fetchReviews(bounds, ctrl.signal, scope));
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        if (err instanceof ApiError && err.status === 401) {
          // Session expired while filtering by "following" — re-login.
          window.location.href = "/login";
          return;
        }
        console.error("Failed to load reviews", err);
      }
    },
    [scope],
  );

  /** Refetch at the current bounds when the scope changes. */
  useEffect(() => {
    if (lastBounds.current) void loadReviews(lastBounds.current);
  }, [loadReviews]);

  /** Select a place (map marker, map click, search): open the place panel. */
  const selectPlace = useCallback(
    (place: PlaceSelection) => {
      setSelectedPlace(place);
      setFocus(makeFocus(place.lat, place.lng, 16));
    },
    [makeFocus],
  );

  /** A review card was clicked — open the panel of its place. */
  const selectReview = useCallback(
    (review: Review) => {
      selectPlace({
        lat: review.latitude,
        lng: review.longitude,
        name: review.place_name,
        address: review.place_address,
      });
    },
    [selectPlace],
  );

  /**
   * Open the review form for a specific place (place panel / place marker
   * "add your review"). The draft is pre-filled with the place and locked,
   * so map clicks can't move the location.
   */
  const openForm = useCallback(
    (place: PlaceSelection) => {
      if (!user) {
        // Logged out — send to /login.
        window.location.href = "/login";
        return;
      }
      setDraft({
        lat: place.lat,
        lng: place.lng,
        placeName: place.name,
        placeAddress: place.address,
        label: place.name,
        locked: true,
      });
      // The form sits inside the sidebar, so only the sidebar width needs
      // padding.
      setFocus(makeFocus(place.lat, place.lng, 16));
      setFormOpen(true);
    },
    [user, makeFocus],
  );

  const closeForm = useCallback(() => {
    setFormOpen(false);
    setDraft(null);
  }, []);

  const onDraftMove = useCallback((lat: number, lng: number) => {
    setDraft((d) =>
      d && !d.locked
        ? { ...d, lat, lng, label: `${lat.toFixed(4)}, ${lng.toFixed(4)}` }
        : d,
    );
  }, []);

  /**
   * Reverse-geocode a point and hand the display name to `apply`, which is
   * responsible for updating whichever state still matches the coordinates.
   */
  const applyReverseGeocode = useCallback(
    (lat: number, lng: number, apply: (displayName: string) => void) => {
      reverseGeocode(lat, lng)
        .then((displayName) => {
          if (displayName) apply(displayName);
        })
        .catch((err) => console.error("Reverse geocode failed", err));
    },
    [],
  );

  /**
   * Map click while the form is open: drop the draggable placement marker
   * and reverse-geocode to fill the place name / address fields. Ignored
   * when the draft is locked to a specific place.
   */
  const onMapClick = useCallback(
    (lat: number, lng: number) => {
      const label = `${lat.toFixed(4)}, ${lng.toFixed(4)}`;
      setDraft((d) =>
        d?.locked
          ? d
          : { lat, lng, placeName: "", placeAddress: "", label, locked: false },
      );
      applyReverseGeocode(lat, lng, (displayName) =>
        setDraft((d) =>
          d && !d.locked && d.lat === lat && d.lng === lng
            ? {
              ...d,
              placeName: displayName.split(",")[0],
              placeAddress: displayName,
            }
            : d,
        ),
      );
    },
    [applyReverseGeocode],
  );

  /**
   * Place picked in the global map search: drop the map marker, open the
   * place panel in the sidebar, and move the map to the place.
   */
  const onSearchPlaceSelected = useCallback(
    (result: NominatimResult) => {
      const lat = parseFloat(result.lat);
      const lng = parseFloat(result.lon);
      setSelectedPlace({
        lat,
        lng,
        name: result.display_name.split(",")[0],
        address: result.display_name,
      });
      setFocus(makeFocus(lat, lng, 16));
    },
    [makeFocus],
  );

  /**
   * Close the place panel (✕ button or cleared search text): back to the
   * standard sidebar, map marker removed — and the review form (which is
   * bound to that place) closes too.
   */
  const closePlacePanel = useCallback(() => {
    setSelectedPlace(null);
    closeForm();
  }, [closeForm]);

  /**
   * Map click while no form is open: select the clicked spot as a place and
   * open the place panel, like a search pick. The panel opens immediately
   * with the coordinates — the real name/address are filled in when the
   * reverse geocode resolves. The spot is already in view, so the map
   * doesn't need to move.
   */
  const onMapSelect = useCallback(
    (lat: number, lng: number) => {
      const coords = `${lat.toFixed(4)}, ${lng.toFixed(4)}`;
      setSelectedPlace({ lat, lng, name: coords, address: coords });
      applyReverseGeocode(lat, lng, (displayName) =>
        setSelectedPlace((p) =>
          p && p.lat === lat && p.lng === lng
            ? { ...p, name: displayName.split(",")[0], address: displayName }
            : p,
        ),
      );
    },
    [applyReverseGeocode],
  );

  /** Submit the review form. Returns success or an error message. */
  const submitReview = useCallback(
    async (
      content: string,
      rating: number,
    ): Promise<{ ok: boolean; error?: string }> => {
      if (!draft || draft.lat == null || draft.lng == null) {
        return { ok: false, error: "Please search for and select a place first." };
      }
      let resp: Response;
      try {
        resp = await createReview({
          content,
          rating,
          latitude: draft.lat,
          longitude: draft.lng,
          place_name: draft.placeName,
          place_address: draft.placeAddress,
        });
      } catch (err) {
        return {
          ok: false,
          error: `Error creating review: ${(err as Error).message}`,
        };
      }
      if (resp.status === 401) {
        // Logged out (or session expired) — send the user to the login page.
        window.location.href = "/login";
        return { ok: false };
      }
      if (!resp.ok) {
        const data = await resp.json().catch(() => null);
        const detail =
          data && typeof data.detail === "string"
            ? data.detail
            : `Server error: ${resp.status}`;
        return { ok: false, error: detail };
      }
      // Success — close the form and refresh the list at the current bounds.
      setFormOpen(false);
      setDraft(null);
      if (lastBounds.current) await loadReviews(lastBounds.current);
      return { ok: true };
    },
    [draft, loadReviews],
  );

  return (
    <div className="app">
      <MapView
        reviews={reviews}
        draft={draft}
        searchMarker={selectedPlace}
        formOpen={formOpen}
        focus={focus}
        onBoundsChange={loadReviews}
        onMapClick={onMapClick}
        onMapSelect={onMapSelect}
        onDraftMove={onDraftMove}
        onSelectPlace={selectPlace}
        onRatePlace={openForm}
      />

      <aside className="sidebar" data-sheet={shownSheet} style={sheetStyle}>
        <button
          type="button"
          className="sheet-handle"
          aria-label="Review list — drag or tap to resize"
          onPointerDown={onSheetPointerDown}
          onPointerMove={onSheetPointerMove}
          onPointerUp={onSheetPointerUp}
          onPointerCancel={onSheetPointerCancel}
          onClick={onSheetHandleClick}
        >
          <span className="sheet-handle-bar" />
        </button>
        {selectedPlace ? (
          <PlacePanel
            place={selectedPlace}
            reviews={reviewsAtPlace(
              reviews,
              selectedPlace.lat,
              selectedPlace.lng,
            )}
            formOpen={formOpen}
            onRatePlace={openForm}
            onClose={closePlacePanel}
          />
        ) : (
          <>
            <div className="sidebar-header">
              <h1>🗺️ Federated Reviews</h1>
              <span className="review-count">
                {reviews.length} review{reviews.length !== 1 ? "s" : ""}
              </span>
            </div>

            {userLoaded && (
              <div
                className={`sidebar-user${user ? "" : " sidebar-user-anon"}`}
              >
                {user ? (
                  <>
                    <button
                      type="button"
                      className="user-chip"
                      title={`Profile — logged in as ${user.display_name || user.username}`}
                      onClick={onOpenProfile}
                    >
                      <span className="avatar" aria-hidden="true">
                        {(user.display_name || user.username).charAt(0)}
                      </span>
                      <span className="user-name">
                        {user.display_name || user.username}
                      </span>
                    </button>
                    <div className="user-actions">
                      <form method="post" action="/logout">
                        <input
                          type="hidden"
                          name="csrf_token"
                          value={user.csrf_token}
                        />
                        <button type="submit" className="btn btn-sm btn-ghost">
                          <svg
                            width="14"
                            height="14"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2.2"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            aria-hidden="true"
                          >
                            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                            <polyline points="16 17 21 12 16 7" />
                            <line x1="21" y1="12" x2="9" y2="12" />
                          </svg>
                          Logout
                        </button>
                      </form>
                    </div>
                  </>
                ) : (
                  <div className="user-actions">
                    <a href="/register" className="btn btn-sm btn-secondary">
                      Register
                    </a>
                    <a href="/login" className="btn btn-sm btn-primary">
                      Sign in
                    </a>
                  </div>
                )}
              </div>
            )}

            <SearchBox onSelect={onSearchPlaceSelected} onClear={closePlacePanel} />

            <div className="scope-toggle" role="group" aria-label="Review scope">
              <button
                type="button"
                className={scope === "all" ? "active" : ""}
                onClick={() => setScope("all")}
                title="All reviews in this area"
              >
                All
              </button>
              {user && (
                <button
                  type="button"
                  className={scope === "following" ? "active" : ""}
                  onClick={() => setScope("following")}
                  title="Only your reviews and reviews from people you follow"
                >
                  Following
                </button>
              )}
              <button
                type="button"
                className={scope === "local" ? "active" : ""}
                onClick={() => setScope("local")}
                title="Only reviews from users on this server"
              >
                Local
              </button>
            </div>

            <ReviewList
              reviews={reviews}
              onSelect={selectReview}
              emptyMessage={
                scope === "following"
                  ? "No reviews from you or people you follow in this area."
                  : scope === "local"
                    ? "No local reviews in this area."
                    : undefined
              }
            />
          </>
        )}

        {/* The review form is the bottom part of the left panel, not a
            separate side panel. */}
        {formOpen && draft && (
          <ReviewForm onSubmit={submitReview} onClose={closeForm} />
        )}
      </aside>
    </div>
  );
}
