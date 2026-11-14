import ReviewCard from "./ReviewCard";
import type { Me, Review } from "../types";

interface ReviewListProps {
  reviews: Review[];
  onSelect: (review: Review) => void;
  /** The logged-in user — their own reviews and (for admins) all reviews get
   *  a delete button. Null when logged out. */
  user: Me | null;
  /** Delete handler for a card's review (confirm happens in the parent). */
  onDeleteReview?: (review: Review) => void;
  /** Shown when the list is empty (e.g. the "following" scope has no matches). */
  emptyMessage?: string;
  /** True while a load is in flight — skeleton cards when the list is empty. */
  loading?: boolean;
}

/** Sidebar review cards, synced to the visible map bounds. */
export default function ReviewList({
  reviews,
  onSelect,
  user,
  onDeleteReview,
  emptyMessage,
  loading = false,
}: ReviewListProps) {
  if (loading && reviews.length === 0) {
    return (
      <div className="review-list" aria-busy="true" aria-label="Loading reviews">
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="review-card skeleton">
            <div className="sk sk-avatar" />
            <div className="sk-body">
              <div className="sk sk-line w60" />
              <div className="sk sk-line w40" />
              <div className="sk sk-line w90" />
            </div>
          </div>
        ))}
      </div>
    );
  }
  return (
    <div className="review-list">
      {reviews.length === 0 && (
        <div className="empty-state">
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
            <circle cx="12" cy="10" r="2.6" />
          </svg>
          <p>
            {emptyMessage ??
              "No reviews in this area yet — pan the map or search for a place."}
          </p>
        </div>
      )}
      {reviews.map((r) => (
        <ReviewCard
          key={r.id}
          review={r}
          onSelect={onSelect}
          canDelete={!!user && (user.is_admin || r.actor_id === user.id)}
          onDelete={onDeleteReview}
        />
      ))}
    </div>
  );
}
