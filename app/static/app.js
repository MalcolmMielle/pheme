/**
 * Federated Reviews — Frontend Application
 *
 * Handles:
 *  - Leaflet map with OpenStreetMap tiles
 *  - Nominatim geocoding for place search
 *  - Review markers with popups
 *  - Sidebar review list (synced to map bounds)
 *  - Review creation form with star rating
 *  - Review detail panel
 */

// ── State ───────────────────────────────────────────────────────────────

let selectedLat = null;
let selectedLng = null;
let selectedRating = 5;
let currentReviews = [];
let activeReviewId = null;
let mapMarker = null;
let searchTimer = null;

// ── Map ─────────────────────────────────────────────────────────────────

const map = L.map("map", {
  center: [37.7749, -122.4194],
  zoom: 13,
  zoomControl: true,
});

L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  attribution:
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  maxZoom: 19,
}).addTo(map);

// ── Review markers ──────────────────────────────────────────────────────

const markerGroup = L.layerGroup().addTo(map);

const starColors = {
  1: "#ef4444", 2: "#f97316", 3: "#eab308", 4: "#84cc16", 5: "#22c55e",
};

function renderMarkers(reviews) {
  markerGroup.clearLayers();
  reviews.forEach((r) => {
    const color = starColors[r.rating] || "#2563eb";
    const icon = L.divIcon({
      className: "custom-marker",
      html: `<div style="
        width:32px;height:32px;border-radius:50% 50% 50% 0;
        background:${color};color:white;display:flex;align-items:center;
        justify-content:center;font-weight:700;font-size:13px;
        box-shadow:0 2px 6px rgba(0,0,0,.3);transform:rotate(-45deg);
        border:2px solid white;
      "><span style="transform:rotate(45deg)">${r.rating}</span></div>`,
      iconSize: [32, 32],
      iconAnchor: [16, 32],
      popupAnchor: [0, -32],
    });

    const stars = "★".repeat(r.rating) + "☆".repeat(5 - r.rating);
    const marker = L.marker([r.latitude, r.longitude], { icon })
      .bindPopup(
        `<strong>${escHtml(r.place_name || "Unnamed")}</strong><br>
         <span class="popup-stars">${stars}</span><br>
         ${escHtml(r.content.substring(0, 80))}…<br>
         <small>by ${escHtml(r.display_name || r.username)}</small>`
      )
      .on("click", () => selectReview(r));
    markerGroup.addLayer(marker);
  });
}

// ── Sidebar ─────────────────────────────────────────────────────────────

function renderSidebar(reviews) {
  const list = document.getElementById("review-list");
  const countEl = document.getElementById("review-count");
  countEl.textContent = `${reviews.length} review${reviews.length !== 1 ? "s" : ""}`;

  list.innerHTML = reviews
    .map(
      (r) => `
    <div class="review-card ${r.id === activeReviewId ? "active" : ""}"
         data-id="${r.id}"
         onclick="selectReviewById(${r.id})">
      <div class="place">${escHtml(r.place_name || "Unnamed place")}</div>
      <div class="stars">${"★".repeat(r.rating)}${"☆".repeat(5 - r.rating)}</div>
      <div class="snippet">${escHtml(r.content)}</div>
      <div class="meta-line">
        <span>${escHtml(r.display_name || r.username)}</span>
        <span>📍 ${r.latitude.toFixed(3)}, ${r.longitude.toFixed(3)}</span>
      </div>
    </div>`
    )
    .join("");
}

function selectReviewById(id) {
  const r = currentReviews.find((rv) => rv.id === id);
  if (r) selectReview(r);
}

function selectReview(review) {
  activeReviewId = review.id;
  renderSidebar(currentReviews);

  // Only move the map if we're not already looking at this spot.
  const center = map.getCenter();
  const dist = Math.abs(center.lat - review.latitude)
    + Math.abs(center.lng - review.longitude);
  if (dist > 0.001 || map.getZoom() < 14) {
    fitToPoint(review.latitude, review.longitude, 15);
  }

  const panel = document.getElementById("detail-panel");
  const body = document.getElementById("detail-body");
  document.getElementById("detail-title").textContent =
    review.place_name || "Review";

  const stars = "★".repeat(review.rating) + "☆".repeat(5 - review.rating);
  body.innerHTML = `
    <h2>${escHtml(review.place_name || "Unnamed place")}</h2>
    <p class="address">${escHtml(review.place_address || "")}</p>
    <div class="stars">${stars}</div>
    <p class="content">${escHtml(review.content)}</p>
    <p class="meta">
      by <strong>${escHtml(review.display_name || review.username)}</strong>
      &middot; ${review.created_at}
    </p>`;

  panel.classList.remove("panel-hidden");
  document.getElementById("review-panel").classList.add("panel-hidden");
}

// ── Load reviews ────────────────────────────────────────────────────────

async function loadReviews() {
  const bounds = map.getBounds();
  const params = new URLSearchParams({
    min_lat: bounds.getSouth(),
    max_lat: bounds.getNorth(),
    min_lng: bounds.getWest(),
    max_lng: bounds.getEast(),
  });
  try {
    const resp = await fetch(`/api/reviews?${params}`);
    currentReviews = await resp.json();
    renderMarkers(currentReviews);
    renderSidebar(currentReviews);
  } catch (err) {
    console.error("Failed to load reviews", err);
  }
}

map.on("moveend", loadReviews);
loadReviews();

// ── Place search (Nominatim) ────────────────────────────────────────────

const searchInput = document.getElementById("place-name");
const searchResults = document.getElementById("search-results");
const placeAddress = document.getElementById("place-address");
const selectedLoc = document.getElementById("selected-location");
const latInput = document.getElementById("review-lat");
const lngInput = document.getElementById("review-lng");

// ── Shared marker placement (used by search + map-click) ────────────────

function placeMarker(lat, lng, label, moveMap = false) {
  selectedLat = lat;
  selectedLng = lng;
  latInput.value = lat;
  lngInput.value = lng;

  selectedLoc.textContent = `📍 ${label || `${lat.toFixed(4)}, ${lng.toFixed(4)}`}`;
  selectedLoc.classList.add("visible");

  if (mapMarker) map.removeLayer(mapMarker);
  mapMarker = L.marker([lat, lng], { draggable: true }).addTo(map);
  mapMarker.on("dragend", () => {
    const pos = mapMarker.getLatLng();
    selectedLat = pos.lat;
    selectedLng = pos.lng;
    latInput.value = selectedLat;
    lngInput.value = selectedLng;
    selectedLoc.textContent = `📍 ${selectedLat.toFixed(4)}, ${selectedLng.toFixed(4)}`;
  });

  if (moveMap) {
    fitToPoint(lat, lng, 16);
  }
}

function fitToPoint(lat, lng, zoom) {
  // Use fitBounds with left padding so the point always lands in the
  // visible area, even with sidebar / panels open.
  const sidebarW = 380;
  const panelOpen = !reviewPanel.classList.contains("panel-hidden")
    || !detailPanel.classList.contains("panel-hidden");
  const panelW = panelOpen ? 400 : 0;

  const point = L.latLng(lat, lng);
  map.fitBounds(L.latLngBounds([point, point]), {
    maxZoom: zoom,
    paddingTopLeft: [sidebarW + panelW + 30, 30],
    paddingBottomRight: [30, 30],
  });
}

// ── Map click (only when review panel is open) ──────────────────────────

map.on("click", (e) => {
  if (reviewPanel.classList.contains("panel-hidden")) return;
  const lat = e.latlng.lat;
  const lng = e.latlng.lng;
  placeMarker(lat, lng, `${lat.toFixed(4)}, ${lng.toFixed(4)}`, false);
  // Reverse-geocode to fill the name/address fields
  reverseGeocode(lat, lng);
});

async function reverseGeocode(lat, lng) {
  try {
    const resp = await fetch(
      `https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lng}&format=json&accept-language=en`
    );
    const data = await resp.json();
    if (data.display_name) {
      searchInput.value = data.display_name.split(",")[0];
      placeAddress.value = data.display_name;
    }
  } catch (err) {
    console.error("Reverse geocode failed", err);
  }
}

searchInput.addEventListener("input", () => {
  clearTimeout(searchTimer);
  const query = searchInput.value.trim();
  if (query.length < 3) {
    searchResults.classList.remove("visible");
    searchResults.innerHTML = "";
    return;
  }
  searchTimer = setTimeout(() => searchPlaces(query), 350);
});

searchInput.addEventListener("focus", () => {
  if (searchResults.children.length > 0) {
    searchResults.classList.add("visible");
  }
});

document.addEventListener("click", (e) => {
  if (!e.target.closest("#search-wrapper")) {
    searchResults.classList.remove("visible");
  }
  if (!e.target.closest("#map-search-wrapper")) {
    mapSearchResults.classList.remove("visible");
  }
});

async function searchPlaces(query) {
  try {
    const resp = await fetch(
      `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(query)}&format=json&limit=5&addressdetails=1&accept-language=en`
    );
    const results = await resp.json();
    renderSearchResults(results);
  } catch (err) {
    console.error("Nominatim search failed", err);
  }
}

function renderSearchResults(results) {
  searchResults.innerHTML = "";
  if (results.length === 0) {
    searchResults.classList.remove("visible");
    return;
  }
  results.forEach((r) => {
    const div = document.createElement("div");
    div.className = "search-item";
    const typeTag = r.type || r.category || "";
    div.innerHTML = `
      <div class="place">${escHtml(r.display_name.split(",")[0])}</div>
      <div class="addr">${escHtml(r.display_name)}</div>
      ${typeTag ? `<div class="type-tag">${escHtml(typeTag)}</div>` : ""}
    `;
    div.addEventListener("click", () => selectPlace(r));
    searchResults.appendChild(div);
  });
  searchResults.classList.add("visible");
}

function selectPlace(result) {
  const lat = parseFloat(result.lat);
  const lng = parseFloat(result.lon);
  const name = result.display_name.split(",")[0];
  const address = result.display_name;

  searchInput.value = name;
  placeAddress.value = address;
  searchResults.classList.remove("visible");

  placeMarker(lat, lng, name, true);
}

// ── Global map search (always visible in sidebar) ───────────────────────

const mapSearchInput = document.getElementById("map-search");
const mapSearchResults = document.getElementById("map-search-results");
let mapSearchTimer = null;
let mapSearchMarker = null;

mapSearchInput.addEventListener("input", () => {
  clearTimeout(mapSearchTimer);
  const query = mapSearchInput.value.trim();
  if (query.length < 3) {
    mapSearchResults.classList.remove("visible");
    mapSearchResults.innerHTML = "";
    return;
  }
  mapSearchTimer = setTimeout(() => searchMapPlaces(query), 350);
});

mapSearchInput.addEventListener("focus", () => {
  if (mapSearchResults.children.length > 0) {
    mapSearchResults.classList.add("visible");
  }
});

async function searchMapPlaces(query) {
  try {
    const resp = await fetch(
      `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(query)}&format=json&limit=5&addressdetails=1&accept-language=en`
    );
    const results = await resp.json();
    renderMapSearchResults(results);
  } catch (err) {
    console.error("Map search failed", err);
  }
}

function renderMapSearchResults(results) {
  mapSearchResults.innerHTML = "";
  if (results.length === 0) {
    mapSearchResults.classList.remove("visible");
    return;
  }
  results.forEach((r) => {
    const div = document.createElement("div");
    div.className = "search-item";
    const typeTag = r.type || "";
    div.innerHTML = `
      <div class="place">${escHtml(r.display_name.split(",")[0])}</div>
      <div class="addr">${escHtml(r.display_name)}</div>
      ${typeTag ? `<div class="type-tag">${escHtml(typeTag)}</div>` : ""}
    `;
    div.addEventListener("click", () => goToPlace(r));
    mapSearchResults.appendChild(div);
  });
  mapSearchResults.classList.add("visible");
}

function goToPlace(result) {
  const lat = parseFloat(result.lat);
  const lng = parseFloat(result.lon);
  const name = result.display_name.split(",")[0];

  mapSearchInput.value = name;
  mapSearchResults.classList.remove("visible");

  if (mapSearchMarker) map.removeLayer(mapSearchMarker);
  mapSearchMarker = L.marker([lat, lng]).addTo(map);
  mapSearchMarker.bindPopup(`<strong>${escHtml(name)}</strong><br>${escHtml(result.display_name)}`).openPopup();

  fitToPoint(lat, lng, 16);
}

// ── Review form ─────────────────────────────────────────────────────────

const btnAdd = document.getElementById("btn-add-review");
const reviewPanel = document.getElementById("review-panel");
const detailPanel = document.getElementById("detail-panel");
const btnClosePanel = document.getElementById("btn-close-panel");
const btnCloseDetail = document.getElementById("btn-close-detail");

function resetReviewForm() {
  selectedLat = null;
  selectedLng = null;
  latInput.value = "";
  lngInput.value = "";
  searchInput.value = "";
  placeAddress.value = "";
  selectedLoc.classList.remove("visible");
  selectedLoc.textContent = "";
  searchResults.innerHTML = "";
  searchResults.classList.remove("visible");
  if (mapMarker) {
    map.removeLayer(mapMarker);
    mapMarker = null;
  }
}

btnAdd.addEventListener("click", () => {
  detailPanel.classList.add("panel-hidden");
  reviewPanel.classList.remove("panel-hidden");
  resetReviewForm();
});

btnClosePanel.addEventListener("click", () => {
  reviewPanel.classList.add("panel-hidden");
  if (mapMarker) {
    map.removeLayer(mapMarker);
    mapMarker = null;
  }
});

btnCloseDetail.addEventListener("click", () => {
  detailPanel.classList.add("panel-hidden");
  activeReviewId = null;
  renderSidebar(currentReviews);
});

// Star rating
document.querySelectorAll(".star").forEach((star) => {
  star.addEventListener("click", () => {
    selectedRating = parseInt(star.dataset.rating);
    document.getElementById("review-rating").value = selectedRating;
    updateStars();
  });
  star.addEventListener("mouseenter", () => {
    const val = parseInt(star.dataset.rating);
    document.querySelectorAll(".star").forEach((s) => {
      s.textContent = parseInt(s.dataset.rating) <= val ? "★" : "☆";
    });
  });
  star.addEventListener("mouseleave", updateStars);
});

function updateStars() {
  document.querySelectorAll(".star").forEach((s) => {
    const val = parseInt(s.dataset.rating);
    s.textContent = val <= selectedRating ? "★" : "☆";
    s.classList.toggle("active", val <= selectedRating);
  });
}
updateStars();

// Form submit
document.getElementById("review-form").addEventListener("submit", async (e) => {
  e.preventDefault();

  if (!selectedLat || !selectedLng) {
    alert("Please search for and select a place first.");
    return;
  }

  const formData = new FormData(e.target);
  try {
    const resp = await fetch("/api/reviews", {
      method: "POST",
      body: formData,
    });
    if (!resp.ok) {
      const errText = await resp.text();
      console.error("Server error", resp.status, errText);
      alert("Server error: " + resp.status + " — " + errText.substring(0, 200));
      return;
    }
    const data = await resp.json();
    if (data.status === "ok") {
      reviewPanel.classList.add("panel-hidden");
      if (mapMarker) {
        map.removeLayer(mapMarker);
        mapMarker = null;
      }
      e.target.reset();
      selectedRating = 5;
      updateStars();
      resetReviewForm();
      await loadReviews();
    } else {
      console.error("Unexpected response", data);
      alert("Failed to create review: " + JSON.stringify(data));
    }
  } catch (err) {
    console.error("Failed to create review", err);
    alert("Error creating review: " + err.message);
  }
});

// ── Utils ───────────────────────────────────────────────────────────────

function escHtml(str) {
  if (!str) return "";
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}
