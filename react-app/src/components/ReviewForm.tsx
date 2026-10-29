import { useState } from "react";

import NominatimSearch from "./NominatimSearch";
import StarRating from "./StarRating";
import type { Draft, NominatimResult } from "../types";

interface ReviewFormProps {
  draft: Draft;
  onDraftChange: (patch: Partial<Draft>) => void;
  onPlaceSelected: (result: NominatimResult) => void;
  onSubmit: (
    content: string,
    rating: number,
  ) => Promise<{ ok: boolean; error?: string }>;
  onClose: () => void;
}

/**
 * Review creation panel: Nominatim place search, address auto-fill,
 * star rating, content. The map click / draggable placement marker is
 * handled by MapPage + MapView through the draft.
 */
export default function ReviewForm({
  draft,
  onDraftChange,
  onPlaceSelected,
  onSubmit,
  onClose,
}: ReviewFormProps) {
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
      setError("Please search for and select a place first.");
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
        <h2>Write a Review</h2>
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
        <label htmlFor="place-name">Search for a place</label>
        <NominatimSearch
          wrapperClass="search-wrapper"
          inputClass="place-name"
          inputId="place-name"
          placeholder="e.g. Blue Bottle Coffee, San Francisco"
          value={draft.placeName}
          onChange={(placeName) => onDraftChange({ placeName })}
          onSelect={onPlaceSelected}
        />

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
          placeholder="Auto-filled from search"
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
