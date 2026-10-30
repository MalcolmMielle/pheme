import { useEffect, useRef, useState } from "react";

import { searchPlaces } from "../api";
import type { NominatimResult } from "../types";

interface NominatimSearchProps {
  value: string;
  onChange: (value: string) => void;
  onSelect: (result: NominatimResult) => void;
  placeholder?: string;
}

/**
 * Debounced Nominatim place search with a dropdown.
 * The 350 ms debounce respects Nominatim's usage policy.
 */
export default function NominatimSearch({
  value,
  onChange,
  onSelect,
  placeholder,
}: NominatimSearchProps) {
  const [results, setResults] = useState<NominatimResult[]>([]);
  const [open, setOpen] = useState(false);
  /** Index of the keyboard-highlighted item, -1 = none. */
  const [active, setActive] = useState(-1);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wrapper = useRef<HTMLDivElement>(null);
  const list = useRef<HTMLDivElement>(null);

  // Close the dropdown on outside clicks.
  useEffect(() => {
    const onDocClick = (e: MouseEvent) => {
      if (!wrapper.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  // Keep the keyboard-highlighted item scrolled into view.
  useEffect(() => {
    if (active >= 0) {
      list.current?.children[active]?.scrollIntoView({ block: "nearest" });
    }
  }, [active]);

  // Cancel a pending debounce on unmount.
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const handleChange = (v: string) => {
    onChange(v);
    if (timer.current) clearTimeout(timer.current);
    const query = v.trim();
    if (query.length < 3) {
      setResults([]);
      setOpen(false);
      setActive(-1);
      return;
    }
    timer.current = setTimeout(async () => {
      try {
        const found = await searchPlaces(query);
        setResults(found);
        setOpen(found.length > 0);
        setActive(found.length > 0 ? 0 : -1);
      } catch (err) {
        console.error("Nominatim search failed", err);
      }
    }, 350);
  };

  const handleSelect = (r: NominatimResult) => {
    setOpen(false);
    setResults([]);
    setActive(-1);
    onSelect(r);
  };

  // Arrow keys move the highlight, Enter picks it, Escape closes.
  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Escape") {
      setOpen(false);
      return;
    }
    if (!open || results.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      handleSelect(results[active >= 0 ? active : 0]);
    }
  };

  return (
    <div className="map-search-wrapper" ref={wrapper}>
      <input
        type="text"
        className="map-search"
        placeholder={placeholder}
        autoComplete="off"
        role="combobox"
        aria-expanded={open}
        aria-controls="map-search-results"
        aria-activedescendant={
          active >= 0 ? `map-search-item-${active}` : undefined
        }
        value={value}
        onChange={(e) => handleChange(e.target.value)}
        onKeyDown={handleKeyDown}
        onFocus={() => {
          if (results.length > 0) setOpen(true);
        }}
      />
      {open && results.length > 0 && (
        <div
          className="search-dropdown"
          role="listbox"
          id="map-search-results"
          ref={list}
        >
          {results.map((r, i) => {
            const typeTag = r.type || r.category || "";
            return (
              <div
                key={`${r.lat},${r.lon},${i}`}
                id={`map-search-item-${i}`}
                role="option"
                aria-selected={i === active}
                className={`search-item${i === active ? " active" : ""}`}
                onClick={() => handleSelect(r)}
                onMouseEnter={() => setActive(i)}
              >
                <div className="place">{r.display_name.split(",")[0]}</div>
                <div className="addr">{r.display_name}</div>
                {typeTag && <div className="type-tag">{typeTag}</div>}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
