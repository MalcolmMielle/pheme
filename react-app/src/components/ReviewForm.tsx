import { useState } from "react";

import StarRating from "./StarRating";
import type { Draft } from "../types";

interface ReviewFormProps {
  draft: Draft;
  onSubmit: (
    content: string,
    rating: number,
  ) => Promise<{ ok: boolean; error?: string }>;
  onClose: () => void;
}

/**
 * Review creation panel for a fixed place (opened from the place panel /
 * place marker — the location cannot be changed here): read-only place
 * info, star rating, content.
 */
export default function ReviewForm({ draft, onSubmit, onClose }: ReviewFormProps) {
  const [content, setContent] = useState("");
  const [rating, setRating] = useState(5);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const lat = draft.lat;
  const lng = draft.lng;
  const hasLocation = lat != null && lng != null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!hasLocation) {
      setError("No place selected.");
      return;
    }
    if (!content.trim()) {
      setError("Please write a short review.");
      return;
    }
    setSubmitting(true);
    setError(null);
    const result = await onSubmit(content, rating);
    setSubmitting(false);
    if (result.ok) {
      setContent("");
      setRating(5);
    } else if (result.error) {
      setError(result.error);
    }
  };

  return (
    <div className="panel review-panel">
      <div className="panel-header">
        <h2>{draft.placeName || "Write a Review"}</h2>
        <button
          type="button"
          className="icon-btn"
          onClick={onClose}
          aria-label="Close"
        >
          ✕
        </button>
      </div>
      <form className="review-form" onSubmit={handleSubmit}>
        {hasLocation && (
          <div className="selected-location">
            📍 {draft.label || `${lat.toFixed(4)}, ${lng.toFixed(4)}`}
          </div>
        )}

        <label htmlFor="place-address">Address</label>
        <input
          type="text"
          id="place-address"
          className="place-address"
          placeholder="Place address"
          readOnly
          value={draft.placeAddress}
        />

        <label>Rating</label>
        <StarRating value={rating} onChange={setRating} />

        <label htmlFor="review-content">Your review</label>
        <textarea
          id="review-content"
          rows={4}
          placeholder="What did you think?"
          value={content}
          onChange={(e) => setContent(e.target.value)}
        />

        {error && <div className="form-error">{error}</div>}

        <button type="submit" className="btn-primary" disabled={submitting}>
          {submitting ? "Posting…" : "Post Review"}
        </button>
      </form>
    </div>
  );
}
