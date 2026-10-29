import { useState } from "react";

interface StarRatingProps {
  value: number;
  onChange: (value: number) => void;
}

/** 1–5 star input with hover preview (ported from app.js). */
export default function StarRating({ value, onChange }: StarRatingProps) {
  const [hover, setHover] = useState<number | null>(null);
  const shown = hover ?? value;
  return (
    <div className="star-rating" onMouseLeave={() => setHover(null)}>
      {[1, 2, 3, 4, 5].map((n) => (
        <button
          key={n}
          type="button"
          className={`star${n <= shown ? " active" : ""}`}
          aria-label={`${n} star${n !== 1 ? "s" : ""}`}
          onClick={() => onChange(n)}
          onMouseEnter={() => setHover(n)}
        >
          {n <= shown ? "★" : "☆"}
        </button>
      ))}
    </div>
  );
}
