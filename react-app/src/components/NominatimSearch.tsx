import { useEffect, useRef, useState } from "react";

import { searchPlaces } from "../api";
import type { NominatimResult } from "../types";

interface NominatimSearchProps {
  value: string;
  onChange: (value: string) => void;
  onSelect: (result: NominatimResult) => void;
  placeholder?: string;
  wrapperClass: string;
  inputClass: string;
  inputId?: string;
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
  wrapperClass,
  inputClass,
  inputId,
}: NominatimSearchProps) {
  const [results, setResults] = useState<NominatimResult[]>([]);
  const [open, setOpen] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wrapper = useRef<HTMLDivElement>(null);

  // Close the dropdown on outside clicks.
  useEffect(() => {
    const onDocClick = (e: MouseEvent) => {
      if (!wrapper.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

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
      return;
    }
    timer.current = setTimeout(async () => {
      try {
        const found = await searchPlaces(query);
        setResults(found);
        setOpen(found.length > 0);
      } catch (err) {
        console.error("Nominatim search failed", err);
      }
    }, 350);
  };

  const handleSelect = (r: NominatimResult) => {
    setOpen(false);
    setResults([]);
    onSelect(r);
  };

  return (
    <div className={wrapperClass} ref={wrapper}>
      <input
        type="text"
        id={inputId}
        className={inputClass}
        placeholder={placeholder}
        autoComplete="off"
        value={value}
        onChange={(e) => handleChange(e.target.value)}
        onFocus={() => {
          if (results.length > 0) setOpen(true);
        }}
      />
      {open && results.length > 0 && (
        <div className="search-dropdown">
          {results.map((r, i) => {
            const typeTag = r.type || r.category || "";
            return (
              <div
                key={`${r.lat},${r.lon},${i}`}
                className="search-item"
                onClick={() => handleSelect(r)}
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
