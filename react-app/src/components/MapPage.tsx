import type { LatLngBounds } from "leaflet";
import { useCallback, useRef, useState } from "react";

import { createReview, fetchReviews, reverseGeocode } from "../api";
import { useBottomSheet } from "../hooks/useBottomSheet";
import { useMediaQuery } from "../hooks/useMediaQuery";
import MapView from "./MapView";
import ReviewDetail from "./ReviewDetail";
import ReviewForm from "./ReviewForm";
import ReviewList from "./ReviewList";
import SearchBox from "./SearchBox";
import type {
  Draft,
  FocusTarget,
  Me,
  NominatimResult,
  Review,
  SearchMarker,
} from "../types";

const SIDEBAR_W = 380;
const PANEL_W = 400;

interface MapPageProps {
  user: Me | null;
  userLoaded: boolean;
}

/**
 * The map page — layout, state and data flow for the whole app.
 * Ported from app/static/app.js.
 */
export default function MapPage({ user, userLoaded }: MapPageProps) {
  const [reviews, setReviews] = useState<Review[]>([]);
  const [activeReview, setActiveReview] = useState<Review | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [searchMarker, setSearchMarker] = useState<SearchMarker | null>(null);
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

  /**
   * Padding for map focus: desktop keeps the point clear of the sidebar
   * and any open panel; mobile keeps it clear of the floating search bar
   * and the bottom sheet.
   */
  const makeFocus = useCallback(
    (lat: number, lng: number, zoom: number, panelOpen: boolean): FocusTarget =>
      isMobile
        ? { lat, lng, zoom, padLeft: 30, padTop: 84, padRight: 30, padBottom: 164 }
        : {
            lat,
            lng,
            zoom,
            padLeft: SIDEBAR_W + (panelOpen ? PANEL_W : 0) + 30,
            padTop: 30,
            padRight: 30,
            padBottom: 30,
          },
    [isMobile],
  );

  /** Live height while the mobile bottom sheet is being dragged. */
  const sheetBase = sheet === "expanded" ? "85dvh" : "var(--sheet-peek)";
  const sheetStyle =
    dragDy != null
      ? {
          height: `max(64px, min(calc(${sheetBase} - ${dragDy}px), 92dvh))`,
          transition: "none",
        }
      : undefined;

  const loadReviews = useCallback(async (bounds: LatLngBounds) => {
    lastBounds.current = bounds;
    try {
      setReviews(await fetchReviews(bounds));
    } catch (err) {
      console.error("Failed to load reviews", err);
    }
  }, []);

  const selectReview = useCallback(
    (review: Review) => {
      setActiveReview(review);
      setFormOpen(false);
      setFocus(makeFocus(review.latitude, review.longitude, 15, true));
    },
    [makeFocus],
  );

  const closeDetail = useCallback(() => setActiveReview(null), []);

  const openForm = useCallback(() => {
    if (!user) {
      // Same as the old UI: the FAB sends logged-out users to /login.
      window.location.href = "/login";
      return;
    }
    setActiveReview(null);
    setDraft({ lat: null, lng: null, placeName: "", placeAddress: "", label: "" });
    setFormOpen(true);
  }, [user]);

  const closeForm = useCallback(() => {
    setFormOpen(false);
    setDraft(null);
  }, []);

  const onDraftChange = useCallback((patch: Partial<Draft>) => {
    setDraft((d) => (d ? { ...d, ...patch } : d));
  }, []);

  const onDraftMove = useCallback((lat: number, lng: number) => {
    setDraft((d) =>
      d ? { ...d, lat, lng, label: `${lat.toFixed(4)}, ${lng.toFixed(4)}` } : d,
    );
  }, []);

  /**
   * Map click while the form is open: drop the draggable placement marker
   * and reverse-geocode to fill the place name / address fields.
   */
  const onMapClick = useCallback((lat: number, lng: number) => {
    const label = `${lat.toFixed(4)}, ${lng.toFixed(4)}`;
    setDraft({ lat, lng, placeName: "", placeAddress: "", label });
    reverseGeocode(lat, lng)
      .then((displayName) => {
        if (!displayName) return;
        setDraft((d) =>
          d && d.lat === lat && d.lng === lng
            ? {
                ...d,
                placeName: displayName.split(",")[0],
                placeAddress: displayName,
              }
            : d,
        );
      })
      .catch((err) => console.error("Reverse geocode failed", err));
  }, []);

  /** Place picked in the review form's search: fill the draft, move the map. */
  const onPlaceSelected = useCallback((result: NominatimResult) => {
    const lat = parseFloat(result.lat);
    const lng = parseFloat(result.lon);
    const name = result.display_name.split(",")[0];
    setDraft((d) => ({
      ...(d ?? { lat: null, lng: null, placeName: "", placeAddress: "", label: "" }),
      lat,
      lng,
      placeName: name,
      placeAddress: result.display_name,
      label: name,
    }));
    setFocus(makeFocus(lat, lng, 16, true));
  }, [makeFocus]);

  /** Place picked in the global map search: marker + popup, move the map. */
  const onSearchPlaceSelected = useCallback(
    (result: NominatimResult) => {
      const lat = parseFloat(result.lat);
      const lng = parseFloat(result.lon);
      setSearchMarker({
        lat,
        lng,
        name: result.display_name.split(",")[0],
        address: result.display_name,
      });
      setFocus(makeFocus(lat, lng, 16, formOpen || activeReview !== null));
    },
    [makeFocus, formOpen, activeReview],
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
        searchMarker={searchMarker}
        formOpen={formOpen}
        focus={focus}
        onBoundsChange={loadReviews}
        onMapClick={onMapClick}
        onDraftMove={onDraftMove}
        onSelectReview={selectReview}
      />

      <aside className="sidebar" data-sheet={sheet} style={sheetStyle}>
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
        <div className="sidebar-header">
          <h1>🗺️ FedReviews</h1>
          <span className="review-count">
            {reviews.length} review{reviews.length !== 1 ? "s" : ""}
          </span>
        </div>

        {userLoaded && (
          <div className="sidebar-user">
            {user ? (
              <>
                <span title={`Logged in as ${user.display_name || user.username}`}>
                  👤 {user.display_name || user.username}
                </span>
                <form method="post" action="/logout">
                  <input
                    type="hidden"
                    name="csrf_token"
                    value={user.csrf_token}
                  />
                  <button type="submit" className="link-btn">
                    Logout
                  </button>
                </form>
              </>
            ) : (
              <>
                <a href="/login" className="link-btn">
                  Sign in
                </a>
                <a href="/register" className="link-btn">
                  Register
                </a>
              </>
            )}
          </div>
        )}

        <SearchBox onSelect={onSearchPlaceSelected} />

        <ReviewList
          reviews={reviews}
          activeId={activeReview?.id ?? null}
          onSelect={selectReview}
        />

        <button type="button" className="fab" title="Add a review" onClick={openForm}>
          ＋
        </button>
      </aside>

      {formOpen && draft && (
        <ReviewForm
          draft={draft}
          onDraftChange={onDraftChange}
          onPlaceSelected={onPlaceSelected}
          onSubmit={submitReview}
          onClose={closeForm}
        />
      )}

      {activeReview && <ReviewDetail review={activeReview} onClose={closeDetail} />}
    </div>
  );
}
