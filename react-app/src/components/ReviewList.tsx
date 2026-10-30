import { stars } from "../api";
import type { Review } from "../types";

interface ReviewListProps {
  reviews: Review[];
  onSelect: (review: Review) => void;
}

/** Sidebar review cards, synced to the visible map bounds. */
export default function ReviewList({ reviews, onSelect }: ReviewListProps) {
  return (
    <div className="review-list">
      {reviews.map((r) => (
        <div key={r.id} className="review-card" onClick={() => onSelect(r)}>
          <div className="place">{r.place_name || "Unnamed place"}</div>
          <div className="stars">{stars(r.rating)}</div>
          <div className="snippet">{r.content}</div>
          <div className="meta-line">
            <span>{r.display_name || r.username}</span>
            <span>
              📍 {r.latitude.toFixed(3)}, {r.longitude.toFixed(3)}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}
