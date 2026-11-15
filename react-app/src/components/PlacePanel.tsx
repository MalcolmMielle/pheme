import { formatRating } from "../api";
import { addressFromTags, humanizeTag } from "../places";
import ReviewCard from "./ReviewCard";
import Stars from "./Stars";
import type { Me, PlaceSelection, PoiCandidate, Review } from "../types";

interface PlacePanelProps {
  place: PlaceSelection;
  /** Existing reviews at this place (within the current map bounds). */
  reviews: Review[];
  /**
   * Ranked POIs near the selected point — when several places share the
   * clicked spot (one ~11 m bucket), the panel offers them for picking.
   */
  candidates?: PoiCandidate[];
  /**
   * Address of the clicked point (Nominatim display name without the POI
   * label) — fallback shown in a candidate row when that place has no
   * addr:* tags of its own.
   */
  baseAddress?: string;
  /** Called when the user picks one of the candidates as the place. */
  onSelectCandidate?: (c: PoiCandidate) => void;
  /**
   * Called with the candidate under the pointer (or keyboard focus) in the
   * list, or null when it leaves — the map marker moves with it.
   */
  onHoverCandidate?: (c: PoiCandidate | null) => void;
  /** The logged-in user, or null when logged out. */
  user: Me | null;
  /** True while the review form is open at the bottom of the sidebar. */
  formOpen: boolean;
  /**
   * Called with the place, plus the user's existing review there (if any) —
   * the form then opens in edit mode instead of add mode.
   */
  onRatePlace: (place: PlaceSelection, existingReview?: Review) => void;
  /** Delete handler for a review card (own review, or any review for admins). */
  onDeleteReview?: (review: Review) => void;
  /** Click on a card's author — opens that actor's profile page. */
  onSelectActor?: (review: Review) => void;
  onClose: () => void;
}

/**
 * Sidebar panel for a searched place: its info, the existing ratings at
 * the place, and a button to add your own rating — or to edit it when you
 * already reviewed this place. Closing it returns to the standard
 * review-list sidebar.
 */
export default function PlacePanel({
  place,
  reviews,
  candidates,
  baseAddress,
  onSelectCandidate,
  onHoverCandidate,
  user,
  formOpen,
  onRatePlace,
  onDeleteReview,
  onSelectActor,
  onClose,
}: PlacePanelProps) {
  const avg =
    reviews.length > 0
      ? reviews.reduce((sum, r) => sum + r.rating, 0) / reviews.length
      : null;
  /** The logged-in user's own review at this place, if they have one. */
  const myReview = user ? reviews.find((r) => r.actor_id === user.id) : undefined;
  /**
   * Address as short lines from Nominatim's structured address (street,
   * postcode + city, country) — falls back to the plain display string when
   * no structured address is available.
   */
  const details = place.addressDetails;
  const addressLines = details
    ? [
        [details.house_number, details.road].filter(Boolean).join(" "),
        [
          details.postcode,
          details.city ??
            details.town ??
            details.village ??
            details.municipality ??
            details.county,
        ]
          .filter(Boolean)
          .join(" "),
        details.country ?? "",
      ].filter((line) => line.length > 0)
    : [];
  /** Whitelisted OSM tags of the place, rendered as info rows. */
  const tags = place.tags ?? {};
  const website = tags["website"] ?? tags["contact:website"] ?? tags["url"];
  const websiteHref = website
    ? /^https?:\/\//i.test(website)
      ? website
      : `https://${website}`
    : undefined;
  const phone = tags["phone"] ?? tags["contact:phone"];
  const cuisine = tags["cuisine"]
    ?.split(";")
    .map((c) => humanizeTag(c.trim()))
    .filter(Boolean)
    .join(", ");
  const hours = tags["opening_hours"];
  const wheelchair = tags["wheelchair"];
  const ele = tags["ele"];
  const hasInfo = !!(website || phone || cuisine || hours || wheelchair || ele);
  /**
   * True while the candidate picker is shown: only the list is displayed
   * (no address/info/reviews/rate button on top) — the user must pick one
   * of the places first. Picking a row closes the list, and the panel
   * becomes the full place view.
   */
  const picking = !!(candidates && candidates.length > 1 && onSelectCandidate);
  return (
    <div className="place-panel">
      <div className="panel-header">
        <div className="panel-header-title">
          <h2>{place.name}</h2>
          {!picking && place.category && (
            <p className="place-category">{place.category}</p>
          )}
        </div>
        <button
          type="button"
          className="icon-btn"
          onClick={onClose}
          aria-label="Close place panel"
        >
          ✕
        </button>
      </div>
      <div className="place-panel-body">
        {!picking &&
          (addressLines.length > 0 ? (
            <p className="address">{addressLines.join("\n")}</p>
          ) : (
            <p className="address">{place.address}</p>
          ))}
        {!picking && hasInfo && (
          <ul className="place-info">
            {website && (
              <li>
                <span className="place-info-label">Website</span>
                <a href={websiteHref} target="_blank" rel="noopener noreferrer">
                  {website}
                </a>
              </li>
            )}
            {phone && (
              <li>
                <span className="place-info-label">Phone</span>
                <a href={`tel:${phone.replace(/\s/g, "")}`}>{phone}</a>
              </li>
            )}
            {cuisine && (
              <li>
                <span className="place-info-label">Cuisine</span>
                <span className="place-info-value">{cuisine}</span>
              </li>
            )}
            {hours && (
              <li>
                <span className="place-info-label">Hours</span>
                <span className="place-info-value">{hours}</span>
              </li>
            )}
            {wheelchair && (
              <li>
                <span className="place-info-label">Wheelchair</span>
                <span className="place-info-value">{humanizeTag(wheelchair)}</span>
              </li>
            )}
            {ele && (
              <li>
                <span className="place-info-label">Elevation</span>
                <span className="place-info-value">{ele} m</span>
              </li>
            )}
          </ul>
        )}
        {picking && (
          <div
            className="poi-candidates"
            // Reset the hover only when the pointer leaves the whole list —
            // moving between rows (or across the gaps) keeps the last row.
            onMouseLeave={() => onHoverCandidate?.(null)}
            onBlur={(e) => {
              if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
                onHoverCandidate?.(null);
              }
            }}
          >
            <p className="poi-candidates-label">Several places here — pick one:</p>
            {candidates.map((c) => {
              // Each row shows the place's own address (its addr:* tags),
              // falling back to the clicked point's address.
              const addr = addressFromTags(c.tags, baseAddress);
              return (
                <button
                  key={`${c.lat},${c.lon},${c.name}`}
                  type="button"
                  className={`poi-candidate${
                    c.lat === place.lat && c.lon === place.lng ? " selected" : ""
                  }`}
                  onClick={() => onSelectCandidate(c)}
                  onMouseEnter={() => onHoverCandidate?.(c)}
                  onFocus={() => onHoverCandidate?.(c)}
                >
                  <span className="poi-candidate-text">
                    <span className="poi-candidate-name">{c.name}</span>
                    {addr && <small className="poi-candidate-address">{addr}</small>}
                  </span>
                  <small>
                    {[
                      c.value ? humanizeTag(c.value) : "",
                      `${Math.round(c.distance_m)} m`,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </small>
                </button>
              );
            })}
          </div>
        )}
        {!picking &&
          (avg != null ? (
            <>
              <div className="place-panel-avg">
                <Stars value={avg} size={16} />{" "}
                <small>
                  {formatRating(avg)} avg · {reviews.length} review
                  {reviews.length !== 1 ? "s" : ""}
                </small>
              </div>
              <div className="review-list">
                {reviews.map((r) => (
                  <ReviewCard
                    key={r.id}
                    review={r}
                    showPlace={false}
                    showRatingNum={false}
                    showCoords
                    canDelete={!!user && (user.is_admin || r.actor_id === user.id)}
                    onDelete={onDeleteReview}
                    onSelectActor={onSelectActor}
                  />
                ))}
              </div>
            </>
          ) : (
            <div className="empty-state place-empty">
            <svg
              width="32"
              height="32"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinecap="round"
              strokeLinejoin="round"
              aria-hidden="true"
            >
              <path d="M12 21s7-6.1 7-11a7 7 0 1 0-14 0c0 4.9 7 11 7 11z" />
              <path d="M12 12.5v-5M9.5 10 12 7.5 14.5 10" />
            </svg>
            <p>No reviews yet — be the first to rate this place.</p>
            </div>
          ))}
        {!formOpen && !picking && (
          <button
            type="button"
            className="btn btn-primary place-rate-btn"
            onClick={() => onRatePlace(place, myReview)}
          >
            {myReview ? "✎ Edit your review" : "＋ Add a rating"}
          </button>
        )}
      </div>
    </div>
  );
}
