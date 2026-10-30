import { useState } from "react";

import NominatimSearch from "./NominatimSearch";
import type { NominatimResult } from "../types";

interface SearchBoxProps {
  onSelect: (result: NominatimResult) => void;
  /** Fired when the search text is cleared — the picked place is forgotten. */
  onClear?: () => void;
}

/** Global map search (always visible at the top of the sidebar). */
export default function SearchBox({ onSelect, onClear }: SearchBoxProps) {
  const [value, setValue] = useState("");
  return (
    <NominatimSearch
      wrapperClass="map-search-wrapper"
      inputClass="map-search"
      placeholder="Search for a place…"
      value={value}
      onChange={(v) => {
        setValue(v);
        if (!v.trim()) onClear?.();
      }}
      onSelect={(r) => {
        setValue(r.display_name.split(",")[0]);
        onSelect(r);
      }}
    />
  );
}
