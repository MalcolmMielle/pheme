interface StarsProps {
  /** Rating to display; rounded to the nearest whole star. */
  value: number;
  /** Star edge length in px. */
  size?: number;
}

/** Shared star SVG path — used by Stars (display) and StarRating (input). */
export const STAR_PATH =
  "M12 2.6l2.83 5.9 6.47.84-4.75 4.5 1.2 6.4L12 17.1l-5.75 3.14 1.2-6.4-4.75-4.5 6.47-.84z";

/** Five SVG stars, filled up to the (rounded) rating. */
export default function Stars({ value, size = 14 }: StarsProps) {
  const filled = Math.min(5, Math.max(0, Math.round(value)));
  return (
    <span className="stars" role="img" aria-label={`${value} out of 5 stars`}>
      {[1, 2, 3, 4, 5].map((n) => (
        <svg
          key={n}
          width={size}
          height={size}
          viewBox="0 0 24 24"
          className={n <= filled ? "star-on" : "star-off"}
          aria-hidden="true"
        >
          <path d={STAR_PATH} />
        </svg>
      ))}
    </span>
  );
}
