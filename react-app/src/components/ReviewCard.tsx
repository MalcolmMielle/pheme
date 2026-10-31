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
}

/** One review card — shared by the sidebar review list and the place panel. */
export default function ReviewCard({
  review: r,
  onSelect,
  showPlace = true,
  showRatingNum = true,
  showCoords = false,
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
        </div>
      </div>
    </div>
  );
}
