import { actorServer, formatDate, formatRating, stars } from "../api";
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
              <span className="stars">{stars(Math.round(avg))}</span>{" "}
              <small>
                {formatRating(avg)} avg · {reviews.length} review
                {reviews.length !== 1 ? "s" : ""}
              </small>
            </div>
            <div className="review-list">
              {reviews.map((r) => {
                const server = actorServer(r.actor_uri);
                return (
                  <div key={r.id} className="review-card review-card-static">
                    <div className="stars">{stars(r.rating)}</div>
                    <div className="snippet">{r.content}</div>
                    <div className="meta-line">
                      <span>
                        {r.display_name || r.username}
                        {server && <span className="server"> @{server}</span>}
                      </span>
                      <span className="date">{formatDate(r.created_at)}</span>
                      <span>
                        📍 {r.latitude.toFixed(3)}, {r.longitude.toFixed(3)}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        ) : (
          <p className="place-empty">
            No reviews yet — be the first to rate this place.
          </p>
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
