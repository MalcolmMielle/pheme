import { useEffect, useState } from "react";

/** Track a CSS media query — re-renders when it starts/stops matching. */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    window.matchMedia(query).matches,
  );
  useEffect(() => {
    const mq = window.matchMedia(query);
    const onChange = () => setMatches(mq.matches);
    onChange();
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}
