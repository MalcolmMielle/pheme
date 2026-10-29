import { stars } from "../api";
import type { Review } from "../types";

interface ReviewDetailProps {
  review: Review;
  onClose: () => void;
}

/** Slide-in review detail panel. */
export default function ReviewDetail({ review, onClose }: ReviewDetailProps) {
  return (
    <div className="panel detail-panel">
      <div className="panel-header">
        <h2>{review.place_name || "Review"}</h2>
        <button
          type="button"
          className="icon-btn"
          onClick={onClose}
          aria-label="Close"
        >
          ✕
        </button>
      </div>
      <div className="detail-body">
        <h2>{review.place_name || "Unnamed place"}</h2>
        <p className="address">{review.place_address || ""}</p>
        <div className="stars">{stars(review.rating)}</div>
        <p className="content">{review.content}</p>
        <p className="meta">
          by <strong>{review.display_name || review.username}</strong>
          &middot; {review.created_at}
        </p>
      </div>
    </div>
  );
}
