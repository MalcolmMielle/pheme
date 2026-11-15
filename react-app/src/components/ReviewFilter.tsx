import { STAR_PATH } from "./Stars";

interface ReviewFilterProps {
  /** Current text of the filter input (the parent debounces applying it). */
  text: string;
  onTextChange: (v: string) => void;
  /** Minimum rating in stars, or null = any rating. */
  minRating: number | null;
  onMinRatingChange: (r: number | null) => void;
}

const RATING_OPTIONS: { value: number | null; label: string }[] = [
  { value: null, label: "Any" },
  { value: 2, label: "2+" },
  { value: 3, label: "3+" },
  { value: 4, label: "4+" },
  { value: 5, label: "5" },
];

/**
 * Sidebar filter bar, under the scope toggle: a review-text filter plus
 * minimum-rating chips. Narrows the loaded review list (and the map
 * markers, which are grouped from the same list) at the current bounds.
 * Distinct from the search box, which jumps to a place/review.
 */
export default function ReviewFilter({
  text,
  onTextChange,
  minRating,
  onMinRatingChange,
}: ReviewFilterProps) {
  return (
    <div className="review-filter">
      <div className="filter-input-wrap">
        <span className="search-icon" aria-hidden="true" />
        <input
          type="text"
          className="filter-input"
          placeholder="Filter reviews by text…"
          autoComplete="off"
          aria-label="Filter reviews by text"
          value={text}
          onChange={(e) => onTextChange(e.target.value)}
        />
        {text && (
          <button
            type="button"
            className="filter-clear"
            aria-label="Clear text filter"
            onClick={() => onTextChange("")}
          >
            ✕
          </button>
        )}
      </div>
      <div className="filter-ratings" role="group" aria-label="Minimum rating">
        {RATING_OPTIONS.map((o) => (
          <button
            key={String(o.value)}
            type="button"
            className={`filter-chip${minRating === o.value ? " active" : ""}`}
            aria-pressed={minRating === o.value}
            title={
              o.value === null ? "Any rating" : `${o.value} star${o.value > 1 ? "s" : ""} and up`
            }
            onClick={() => onMinRatingChange(o.value)}
          >
            {o.value !== null && (
              <svg
                viewBox="0 0 24 24"
                width="11"
                height="11"
                className="chip-star"
                aria-hidden="true"
              >
                <path d={STAR_PATH} />
              </svg>
            )}
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}
