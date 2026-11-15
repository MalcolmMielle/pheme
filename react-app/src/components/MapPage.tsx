import type { LatLngBounds } from "leaflet";
import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";

import {
  ApiError,
  createReview,
  deleteReview,
  errorFromResponse,
  fetchMeta,
  fetchReviews,
  reverseGeocode,
  updateReview,
} from "../api";
import { useBottomSheet } from "../hooks/useBottomSheet";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { reviewsAtPlace } from "../places";
import MapView from "./MapView";
import PlacePanel from "./PlacePanel";
import ReviewFilter from "./ReviewFilter";
import ReviewForm from "./ReviewForm";
import ReviewList from "./ReviewList";
import SearchBox from "./SearchBox";
import ThemeToggle from "./ThemeToggle";
import type {
  Draft,
  FocusTarget,
  Me,
  NominatimResult,
  PlaceSelection,
  PoiCandidate,
  Review,
  ReviewScope,
  SearchMarker,
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
  /** True while a review load is in flight (drives skeleton cards). */
  const [loading, setLoading] = useState(true);
  /** "all" = everything in bounds; "following" = own + followed; "local" = this server. */
  const [scope, setScope] = useState<ReviewScope>("all");
  /** Text of the sidebar filter input; `appliedFilter` is its debounced value
   *  that actually drives the query. */
  const [filterText, setFilterText] = useState("");
  const [appliedFilter, setAppliedFilter] = useState("");
  /** Minimum rating filter (stars), null = any. */
  const [minRating, setMinRating] = useState<number | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  /**
   * The review being edited, when the form was opened from a place the
   * logged-in user already reviewed — null for a brand-new review.
   */
  const [editingReview, setEditingReview] = useState<Review | null>(null);
  /**
   * Place picked via the global search: shown as a map marker and as the
   * place panel in the sidebar. Cleared when the search text is removed
   * or the panel is closed.
   */
  const [selectedPlace, setSelectedPlace] = useState<PlaceSelection | null>(null);
  /**
   * Distance-sorted POI candidates around the selected map point (from the
   * reverse geocode) — shown in the place panel so the user can pick the
   * exact place when several share one ~11 m bucket; the first (closest) is
   * auto-selected. ``poiBaseAddress`` is the Nominatim display name without
   * the POI label, used as the address when a candidate is picked.
   */
  const [poiCandidates, setPoiCandidates] = useState<PoiCandidate[]>([]);
  const [poiBaseAddress, setPoiBaseAddress] = useState("");
  /**
   * Candidate currently hovered (or focused) in the place panel's list —
   * the map marker moves to it, so the user sees where each candidate sits
   * before picking one.
   */
  const [hoveredCandidate, setHoveredCandidate] = useState<PoiCandidate | null>(
    null,
  );
  const [focus, setFocus] = useState<FocusTarget | null>(null);
  /**
   * A freshly picked point awaiting reverse geocoding — the effect below
   * fills in the name/address of the draft or selected place that still
   * matches these coordinates.
   */
  const [pendingGeocode, setPendingGeocode] = useState<{
    lat: number;
    lng: number;
    target: "draft" | "place";
  } | null>(null);
  /** Registration mode from /api/meta — hides the Register button when "closed". */
  const [registrationMode, setRegistrationMode] = useState("open");
  /** Error from a card-initiated delete (no form is open to show it in). */
  const [listError, setListError] = useState<string | null>(null);

  useEffect(() => {
    if (user) return;
    fetchMeta()
      .then((m) => setRegistrationMode(m.registration_mode))
      .catch(() => {});
  }, [user]);

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
   * mobile keeps it clear of the floating search bar and the account /
   * zoom / locate rows below it (they end at ~164 px) and the bottom sheet.
   */
  const makeFocus = useCallback(
    (lat: number, lng: number, zoom: number): FocusTarget =>
      isMobile
        ? { lat, lng, zoom, padLeft: 30, padTop: 174, padRight: 30, padBottom: 164 }
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

  // Debounce the filter text so we don't refetch on every keystroke.
  useEffect(() => {
    const t = setTimeout(() => setAppliedFilter(filterText), 300);
    return () => clearTimeout(t);
  }, [filterText]);

  const loadReviews = useCallback(
    async (bounds: LatLngBounds) => {
      lastBounds.current = bounds;
      // Cancel any in-flight load — only the response for the latest
      // bounds/scope/filter may update the map.
      reviewsAbort.current?.abort();
      const ctrl = new AbortController();
      reviewsAbort.current = ctrl;
      setLoading(true);
      try {
        setReviews(
          await fetchReviews(bounds, ctrl.signal, scope, {
            q: appliedFilter.trim() || undefined,
            minRating,
          }),
        );
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        if (err instanceof ApiError && err.status === 401) {
          // Session expired while filtering by "following" — re-login.
          window.location.href = "/login";
          return;
        }
        console.error("Failed to load reviews", err);
      } finally {
        if (reviewsAbort.current === ctrl) setLoading(false);
      }
    },
    [scope, appliedFilter, minRating],
  );

  /** Refetch at the current bounds when the scope or filters change. */
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
   * "add your review" / "edit your review"). When the logged-in user already
   * reviewed this place, `existingReview` is passed and the form opens in
   * edit mode for that review. The draft is pre-filled with the place and
   * locked, so map clicks can't move the location.
   */
  const openForm = useCallback(
    (place: PlaceSelection, existingReview?: Review) => {
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
      setEditingReview(existingReview ?? null);
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
    setEditingReview(null);
  }, []);

  const onDraftMove = useCallback((lat: number, lng: number) => {
    setDraft((d) =>
      d && !d.locked
        ? { ...d, lat, lng, label: `${lat.toFixed(4)}, ${lng.toFixed(4)}` }
        : d,
    );
  }, []);

  /**
   * Reverse-geocode the pending point and fill in the name/address of
   * whichever state (draft or selected place) still matches the coordinates.
   * One effect owns the async lookup; the coordinate guard covers the case
   * where the user picked a different spot before it resolved.
   */
  useEffect(() => {
    if (!pendingGeocode) return;
    const { lat, lng, target } = pendingGeocode;
    let cancelled = false;
    reverseGeocode(lat, lng)
      .then((result) => {
        if (cancelled || !result) return;
        const displayName = result.display_name;
        const name = displayName.split(",")[0];
        const top = result.candidates?.[0];
        if (target === "draft") {
          setDraft((d) => {
            if (!d || d.locked || d.lat !== lat || d.lng !== lng) return d;
            // Snap the placement pin to the nearest reviewable place too, so
            // a review started from a map click lands in the same bucket as
            // the place panel / search pick of that POI.
            if (top) {
              return {
                ...d,
                lat: top.lat,
                lng: top.lon,
                placeName: top.name,
                placeAddress: displayName,
              };
            }
            return { ...d, placeName: name, placeAddress: displayName };
          });
        } else {
          setPoiCandidates(result.candidates ?? []);
          setPoiBaseAddress(result.address ?? displayName);
          setSelectedPlace((p) => {
            if (!p || p.lat !== lat || p.lng !== lng) return p;
            // When the candidate list appears, auto-select the first (closest)
            // element: the marker moves to it and the panel names that exact
            // place. For a road this snaps to its canonical (centroid) point,
            // so every review of the same road lands in the same bucket.
            if (top) {
              return {
                ...p,
                lat: top.lat,
                lng: top.lon,
                name: top.name,
                // Label-included display ("Indian Zayeka, Life School
                // Lausanne, 8, …") — same format as a search pick's address.
                address: displayName,
              };
            }
            return { ...p, name, address: displayName };
          });
        }
      })
      .catch((err) => console.error("Reverse geocode failed", err));
    return () => {
      cancelled = true;
    };
  }, [pendingGeocode]);

  /**
   * Map click while the form is open: drop the draggable placement marker
   * and reverse-geocode to fill the place name / address fields. Ignored
   * when the draft is locked to a specific place.
   */
  const onMapClick = useCallback((lat: number, lng: number) => {
    const label = `${lat.toFixed(4)}, ${lng.toFixed(4)}`;
    setDraft((d) =>
      d?.locked
        ? d
        : { lat, lng, placeName: "", placeAddress: "", label, locked: false },
    );
    setPendingGeocode({ lat, lng, target: "draft" });
  }, []);

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
      setPoiCandidates([]);
      setPoiBaseAddress("");
      // Reverse-geocode the search pick too, so it snaps to the same
      // reviewable candidate a map click at that spot would pick — the same
      // POI then always lands in the same place bucket (no duplicate
      // reviews whether you arrive by search or by click).
      setPendingGeocode({ lat, lng, target: "place" });
      setFocus(makeFocus(lat, lng, 16));
    },
    [makeFocus],
  );

  /**
   * Pick one of the candidate POIs at the selected spot: the place panel
   * (and any review started from it) then names that exact place, with the
   * street address behind it. The position snaps to the candidate's exact
   * marker coordinates, so every pick of the same POI lands in the same
   * place bucket — a duplicate review is impossible (409 from the server).
   */
  const onSelectCandidate = useCallback(
    (c: PoiCandidate) => {
      setSelectedPlace((p) =>
        p
          ? {
              ...p,
              lat: c.lat,
              lng: c.lon,
              name: c.name,
              address: `${c.name}, ${poiBaseAddress}`,
            }
          : p,
      );
    },
    [poiBaseAddress],
  );

  /**
   * Close the place panel (✕ button or cleared search text): back to the
   * standard sidebar, map marker removed — and the review form (which is
   * bound to that place) closes too.
   */
  const closePlacePanel = useCallback(() => {
    setSelectedPlace(null);
    setPoiCandidates([]);
    setPoiBaseAddress("");
    closeForm();
  }, [closeForm]);

  /**
   * Map click while no form is open: select the clicked spot as a place and
   * open the place panel, like a search pick. The panel opens immediately
   * with the coordinates — the real name/address are filled in when the
   * reverse geocode resolves. The spot is already in view, so the map
   * doesn't need to move.
   */
  const onMapSelect = useCallback((lat: number, lng: number) => {
    const coords = `${lat.toFixed(4)}, ${lng.toFixed(4)}`;
    setSelectedPlace({ lat, lng, name: coords, address: coords });
    setPoiCandidates([]);
    setPoiBaseAddress("");
    setPendingGeocode({ lat, lng, target: "place" });
  }, []);

  /** Submit the review form (create, or update when editing). Returns success
   *  or an error message. */
  const submitReview = useCallback(
    async (
      content: string,
      rating: number,
    ): Promise<{ ok: boolean; error?: string }> => {
      if (!draft || draft.lat == null || draft.lng == null) {
        return { ok: false, error: "Please search for and select a place first." };
      }
      // When editing, keep the review at its original place — the form's
      // location is only the picked place, not editable.
      const lat = editingReview?.latitude ?? draft.lat;
      const lng = editingReview?.longitude ?? draft.lng;
      const placeName = editingReview?.place_name ?? draft.placeName;
      const placeAddress = editingReview?.place_address ?? draft.placeAddress;
      let resp: Response;
      try {
        resp = editingReview
          ? await updateReview(editingReview.id, {
              content,
              rating,
              latitude: lat,
              longitude: lng,
              place_name: placeName,
              place_address: placeAddress,
            })
          : await createReview({
              content,
              rating,
              latitude: lat,
              longitude: lng,
              place_name: placeName,
              place_address: placeAddress,
            });
      } catch (err) {
        return {
          ok: false,
          error: `Error ${editingReview ? "updating" : "creating"} review: ${(err as Error).message}`,
        };
      }
      if (resp.status === 401) {
        // Logged out (or session expired) — send the user to the login page.
        window.location.href = "/login";
        return { ok: false };
      }
      if (!resp.ok) {
        return { ok: false, error: await errorFromResponse(resp) };
      }
      // Success — close the form and refresh the list at the current bounds.
      setFormOpen(false);
      setDraft(null);
      setEditingReview(null);
      if (lastBounds.current) await loadReviews(lastBounds.current);
      return { ok: true };
    },
    [draft, editingReview, loadReviews],
  );

  /** Delete the review being edited. Returns success or an error message. */
  const deleteEditingReview = useCallback(async (): Promise<{
    ok: boolean;
    error?: string;
  }> => {
    if (!editingReview) {
      return { ok: false, error: "No review is being edited." };
    }
    let resp: Response;
    try {
      resp = await deleteReview(editingReview.id);
    } catch (err) {
      return { ok: false, error: `Error deleting review: ${(err as Error).message}` };
    }
    if (resp.status === 401) {
      // Logged out (or session expired) — send the user to the login page.
      window.location.href = "/login";
      return { ok: false };
    }
    if (!resp.ok) {
      return { ok: false, error: await errorFromResponse(resp) };
    }
    // Success — close the form and refresh the list at the current bounds.
    setFormOpen(false);
    setDraft(null);
    setEditingReview(null);
    if (lastBounds.current) await loadReviews(lastBounds.current);
    return { ok: true };
  }, [editingReview, loadReviews]);

  /**
   * Delete a review from its card (own review, or any review as admin).
   * Confirms first, then deletes via the API and refreshes the list.
   */
  const handleDeleteReview = useCallback(
    async (review: Review) => {
      if (!user) return;
      const who = review.display_name || review.username;
      const question =
        review.actor_id === user.id
          ? "Delete your review? This cannot be undone."
          : `Delete ${who}'s review? This cannot be undone.`;
      if (!window.confirm(question)) return;
      setListError(null);
      let resp: Response;
      try {
        resp = await deleteReview(review.id);
      } catch (err) {
        setListError(`Error deleting review: ${(err as Error).message}`);
        return;
      }
      if (resp.status === 401) {
        // Logged out (or session expired) — send the user to the login page.
        window.location.href = "/login";
        return;
      }
      if (!resp.ok) {
        setListError(await errorFromResponse(resp));
        return;
      }
      // If the deleted review was open in the edit form, close the form.
      if (editingReview?.id === review.id) {
        setFormOpen(false);
        setDraft(null);
        setEditingReview(null);
      }
      if (lastBounds.current) await loadReviews(lastBounds.current);
    },
    [user, editingReview, loadReviews],
  );

  // The candidate under the pointer in the list, if it is still in the
  // current list (identity check — a stale hover from a previous list falls
  // back to the selected place).
  const hovered =
    hoveredCandidate && poiCandidates.some((c) => c === hoveredCandidate)
      ? hoveredCandidate
      : null;
  // The map marker: at the hovered candidate while the pointer is over the
  // candidate list, otherwise at the selected place.
  const mapMarker: SearchMarker | null = hovered
    ? {
        lat: hovered.lat,
        lng: hovered.lon,
        name: hovered.name,
        address: poiBaseAddress || selectedPlace?.address || "",
      }
    : selectedPlace;
  // The panel follows the hover too, so scrolling the candidate list updates
  // the name/address (and the marker) row by row; click a row to select it.
  const panelPlace: PlaceSelection | null = selectedPlace
    ? hovered
      ? {
          lat: hovered.lat,
          lng: hovered.lon,
          name: hovered.name,
          address: `${hovered.name}, ${poiBaseAddress || selectedPlace.address}`,
        }
      : selectedPlace
    : null;

  return (
    <div className="app">
      <MapView
        reviews={reviews}
        draft={draft}
        searchMarker={mapMarker}
        userId={user?.id ?? null}
        formOpen={formOpen}
        focus={focus}
        onBoundsChange={loadReviews}
        onMapClick={onMapClick}
        onMapSelect={onMapSelect}
        onDraftMove={onDraftMove}
        onSelectPlace={selectPlace}
        onRatePlace={openForm}
      />

      {/* Account button floats over the map's top-right corner — the sidebar
          header stays app-level (wordmark + theme/auth), and the profile
          page (with its Log out button) is one tap away. */}
      {user && (
        <button
          type="button"
          className="account-btn"
          title={`Profile — logged in as ${user.display_name || user.username}`}
          onClick={onOpenProfile}
        >
          <span className="avatar" aria-hidden="true">
            {(user.display_name || user.username).charAt(0)}
          </span>
        </button>
      )}

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
        {panelPlace ? (
          <PlacePanel
            place={panelPlace}
            reviews={reviewsAtPlace(reviews, panelPlace.lat, panelPlace.lng)}
            candidates={poiCandidates}
            onSelectCandidate={onSelectCandidate}
            onHoverCandidate={setHoveredCandidate}
            user={user}
            formOpen={formOpen}
            onRatePlace={openForm}
            onDeleteReview={handleDeleteReview}
            onClose={closePlacePanel}
          />
        ) : (
          <>
            <div className="sidebar-header">
              <h1 className="wordmark">
                <svg
                  className="wordmark-logo"
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                >
                  <defs>
                    <linearGradient id="wordmark-g" x1="0" y1="0" x2="1" y2="1">
                      <stop offset="0" stopColor="#5b5bd6" />
                      <stop offset="1" stopColor="#a855f7" />
                    </linearGradient>
                  </defs>
                  <path
                    fill="url(#wordmark-g)"
                    d="M12 1.8a7.2 7.2 0 0 0-7.2 7.2c0 5.4 7.2 13.2 7.2 13.2s7.2-7.8 7.2-13.2A7.2 7.2 0 0 0 12 1.8z"
                  />
                  <path
                    fill="#fff"
                    d="M12 6.1l1.25 2.53 2.79.4-2.02 1.97.48 2.78L12 12.65l-2.5 1.31.48-2.78-2.02-1.97 2.79-.4z"
                  />
                </svg>
                Pheme
              </h1>
              <div className="header-actions">
                {userLoaded && !user && (
                  <>
                    {registrationMode !== "closed" && (
                      <a href="/register" className="btn btn-sm btn-secondary">
                        Register
                      </a>
                    )}
                    <a href="/login" className="btn btn-sm btn-primary">
                      Sign in
                    </a>
                  </>
                )}
                <ThemeToggle />
              </div>
            </div>

            <ScopeToggle scope={scope} onChange={setScope} loggedIn={!!user} />

            <SearchBox onSelect={onSearchPlaceSelected} onClear={closePlacePanel} />

            <ReviewFilter
              text={filterText}
              onTextChange={setFilterText}
              minRating={minRating}
              onMinRatingChange={setMinRating}
            />

            {listError && <div className="form-error list-error">{listError}</div>}

            <ReviewList
              reviews={reviews}
              onSelect={selectReview}
              user={user}
              onDeleteReview={handleDeleteReview}
              loading={loading}
              emptyMessage={
                appliedFilter.trim() || minRating != null
                  ? "No reviews match your filters in this area."
                  : scope === "following"
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
          <ReviewForm
            initialReview={editingReview}
            onSubmit={submitReview}
            onDelete={deleteEditingReview}
            onClose={closeForm}
          />
        )}
      </aside>
    </div>
  );
}

/** Segmented scope control (All / Following / Local) with a sliding thumb. */
function ScopeToggle({
  scope,
  onChange,
  loggedIn,
}: {
  scope: ReviewScope;
  onChange: (scope: ReviewScope) => void;
  loggedIn: boolean;
}) {
  const options: { value: ReviewScope; label: string; title: string }[] = [
    { value: "all", label: "All", title: "All reviews in this area" },
    ...(loggedIn
      ? [
          {
            value: "following" as ReviewScope,
            label: "Following",
            title: "Only your reviews and reviews from people you follow",
          },
        ]
      : []),
    {
      value: "local",
      label: "Local",
      title: "Only reviews from users on this server",
    },
  ];
  const active = options.findIndex((o) => o.value === scope);
  return (
    <div
      className="scope-toggle"
      role="group"
      aria-label="Review scope"
      style={{ "--active": active, "--count": options.length } as CSSProperties}
    >
      <span className="scope-thumb" aria-hidden="true" />
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          className={scope === o.value ? "active" : ""}
          aria-pressed={scope === o.value}
          onClick={() => onChange(o.value)}
          title={o.title}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
