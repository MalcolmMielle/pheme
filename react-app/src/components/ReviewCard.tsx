import {
  actorServer,
  avatarColor,
  formatDate,
  formatRelative,
  formatRating,
} from "../api";
import Stars from "./Stars";
import type { Review } from "../types";

interface ReviewCardProps {
  review: Review;
  /** Click handler — makes the card selectable (sidebar list). */
  onSelect?: (review: Review) => void;
  /** Show the place name line (hidden in the place panel, where it's the title). */
  showPlace?: boolean;
  /** Show the numeric rating next to the stars (sidebar list only). */
  showRatingNum?: boolean;
  /** Show the coordinate line (place panel only). */
  showCoords?: boolean;
  /** Show a delete button on the card (own review, or any review for admins). */
  canDelete?: boolean;
  /** Delete handler for this card's review. */
  onDelete?: (review: Review) => void;
}

/** One review card — shared by the sidebar review list and the place panel. */
export default function ReviewCard({
  review: r,
  onSelect,
  showPlace = true,
  showRatingNum = true,
  showCoords = false,
  canDelete = false,
  onDelete,
}: ReviewCardProps) {
  const server = actorServer(r.actor_uri);
  const who = r.display_name || r.username;
  return (
    <div
      className={`review-card${onSelect ? "" : " review-card-static"}`}
      onClick={onSelect ? () => onSelect(r) : undefined}
    >
      <span
        className="avatar review-avatar"
        style={{ background: avatarColor(who) }}
        aria-hidden="true"
      >
        {who.charAt(0)}
      </span>
      <div className="review-card-main">
        {showPlace && <span className="place">{r.place_name || "Unnamed place"}</span>}
        {showRatingNum ? (
          <div className="rating-row">
            <Stars value={r.rating} size={12} />
            <span className="rating-num">{formatRating(r.rating)}</span>
          </div>
        ) : (
          <Stars value={r.rating} size={12} />
        )}
        <div className="snippet">{r.content}</div>
        <div className="meta-line">
          <span className="who">
            {who}
            {server && <span className="server"> @{server}</span>}
          </span>
          <span className="date" title={formatDate(r.created_at)}>
            {formatRelative(r.created_at)}
          </span>
          {showCoords && (
            <span className="coords">
              📍 {r.latitude.toFixed(3)}, {r.longitude.toFixed(3)}
            </span>
          )}
          {canDelete && onDelete && (
            <button
              type="button"
              className="review-delete-btn"
              title="Delete review"
              aria-label="Delete review"
              onClick={(e) => {
                // The card itself is clickable (select) — don't trigger it.
                e.stopPropagation();
                onDelete(r);
              }}
            >
              <svg
                viewBox="0 0 24 24"
                width="14"
                height="14"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M3 6h18" />
                <path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2" />
                <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
                <path d="M10 11v6M14 11v6" />
              </svg>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
