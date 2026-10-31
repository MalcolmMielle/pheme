import { useState } from "react";

import { STAR_PATH } from "./Stars";

interface StarRatingProps {
  value: number;
  onChange: (value: number) => void;
}

/** 1–5 star input (SVG stars) with hover preview. */
export default function StarRating({ value, onChange }: StarRatingProps) {
  const [hover, setHover] = useState<number | null>(null);
  const shown = hover ?? value;
  return (
    <div
      className="star-rating"
      role="radiogroup"
      aria-label="Rating"
      onMouseLeave={() => setHover(null)}
    >
      {[1, 2, 3, 4, 5].map((n) => (
        <button
          key={n}
          type="button"
          role="radio"
          aria-checked={n === value}
          className={`star${n <= shown ? " active" : ""}`}
          aria-label={`${n} star${n !== 1 ? "s" : ""}`}
          onClick={() => onChange(n)}
          onMouseEnter={() => setHover(n)}
        >
          <svg width="26" height="26" viewBox="0 0 24 24" aria-hidden="true">
            <path d={STAR_PATH} />
          </svg>
        </button>
      ))}
    </div>
  );
}
