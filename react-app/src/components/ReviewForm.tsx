import { useState } from "react";

import type { Review } from "../types";
import StarRating from "./StarRating";

interface ReviewFormProps {
  /**
   * The review being edited (opened from a place the user already reviewed),
   * or null/undefined for a new review. The form pre-fills from it. The
   * component only mounts while the form is open, so the initial state below
   * is picked up on every open.
   */
  initialReview?: Review | null;
  onSubmit: (
    content: string,
    rating: number,
  ) => Promise<{ ok: boolean; error?: string }>;
  onClose: () => void;
}

/**
 * Review panel for a fixed place (opened from the place panel / place
 * marker — the location is chosen there and cannot change here): star
 * rating and content. In edit mode (initialReview set) it pre-fills the
 * existing review and the parent updates it instead of creating one.
 * The parent guards the location in onSubmit.
 */
export default function ReviewForm({
  initialReview,
  onSubmit,
  onClose,
}: ReviewFormProps) {
  const editing = initialReview != null;
  const [content, setContent] = useState(initialReview?.content ?? "");
  const [rating, setRating] = useState(initialReview?.rating ?? 5);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
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
    <div className="review-panel">
      <div className="panel-header">
        <h2>{editing ? "Edit your review" : "Write a Review"}</h2>
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

        <button type="submit" className="btn btn-primary" disabled={submitting}>
          {submitting
            ? editing
              ? "Saving…"
              : "Posting…"
            : editing
              ? "Save changes"
              : "Post Review"}
        </button>
      </form>
    </div>
  );
}
