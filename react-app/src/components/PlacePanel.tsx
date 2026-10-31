import {
  actorServer,
  avatarColor,
  formatDate,
  formatRating,
  formatRelative,
} from "../api";
import Stars from "./Stars";
import type { PlaceSelection, Review } from "../types";

interface PlacePanelProps {
  place: PlaceSelection;
  /** Existing reviews at this place (within the current map bounds). */
  reviews: Review[];
  /** True while the review form is open at the bottom of the sidebar. */
  formOpen: boolean;
  onRatePlace: (place: PlaceSelection) => void;
  onClose: () => void;
}

/**
 * Sidebar panel for a searched place: its info, the existing ratings at
 * the place, and a button to add your own rating. Closing it returns to
 * the standard review-list sidebar.
 */
export default function PlacePanel({
  place,
  reviews,
  formOpen,
  onRatePlace,
  onClose,
}: PlacePanelProps) {
  const avg =
    reviews.length > 0
      ? reviews.reduce((sum, r) => sum + r.rating, 0) / reviews.length
      : null;
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
              {reviews.map((r) => {
                const server = actorServer(r.actor_uri);
                const who = r.display_name || r.username;
                return (
                  <div key={r.id} className="review-card review-card-static">
                    <span
                      className="avatar review-avatar"
                      style={{ background: avatarColor(who) }}
                      aria-hidden="true"
                    >
                      {who.charAt(0)}
                    </span>
                    <div className="review-card-main">
                      <Stars value={r.rating} size={12} />
                      <div className="snippet">{r.content}</div>
                      <div className="meta-line">
                        <span className="who">
                          {who}
                          {server && <span className="server"> @{server}</span>}
                        </span>
                        <span className="date" title={formatDate(r.created_at)}>
                          {formatRelative(r.created_at)}
                        </span>
                        <span className="coords">
                          📍 {r.latitude.toFixed(3)}, {r.longitude.toFixed(3)}
                        </span>
                      </div>
                    </div>
                  </div>
                );
              })}
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
            onClick={() => onRatePlace(place)}
          >
            ＋ Add a rating
          </button>
        )}
      </div>
    </div>
  );
}
