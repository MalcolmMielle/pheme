import { useEffect, useState } from "react";

import { fetchMe } from "./api";
import MapPage from "./components/MapPage";
import ProfilePage from "./components/ProfilePage";
import type { Me } from "./types";

type View = "map" | "profile";

function viewFromPath(): View {
  return window.location.pathname === "/profile" ? "profile" : "map";
}

export default function App() {
  const [user, setUser] = useState<Me | null>(null);
  const [userLoaded, setUserLoaded] = useState(false);
  const [view, setView] = useState<View>(viewFromPath);

  useEffect(() => {
    fetchMe()
      .then(setUser)
      .catch((err) => console.error("Failed to load current user", err))
      .finally(() => setUserLoaded(true));
  }, []);

  // Keep the view in sync with the URL (browser back/forward, direct load).
  useEffect(() => {
    const onPopState = () => setView(viewFromPath());
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const openProfile = () => {
    window.history.pushState({}, "", "/profile");
    setView("profile");
  };
  const backToMap = () => {
    window.history.pushState({}, "", "/");
    setView("map");
  };

  if (view === "profile" && userLoaded && user) {
    return <ProfilePage user={user} onBack={backToMap} />;
  }
  return <MapPage user={user} userLoaded={userLoaded} onOpenProfile={openProfile} />;
}
