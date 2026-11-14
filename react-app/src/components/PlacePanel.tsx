import { formatRating } from "../api";
import ReviewCard from "./ReviewCard";
import Stars from "./Stars";
import type { Me, PlaceSelection, Review } from "../types";

interface PlacePanelProps {
  place: PlaceSelection;
  /** Existing reviews at this place (within the current map bounds). */
  reviews: Review[];
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
  user,
  formOpen,
  onRatePlace,
  onDeleteReview,
  onClose,
}: PlacePanelProps) {
  const avg =
    reviews.length > 0
      ? reviews.reduce((sum, r) => sum + r.rating, 0) / reviews.length
      : null;
  /** The logged-in user's own review at this place, if they have one. */
  const myReview = user ? reviews.find((r) => r.actor_id === user.id) : undefined;
  return (
    <div className="place-panel">
      <div className="panel-header">
        <h2>{place.name}</h2>
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
        <p className="address">{place.address}</p>
        {avg != null ? (
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
        )}
        {!formOpen && (
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
