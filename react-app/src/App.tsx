import { useEffect, useState } from "react";
import { flushSync } from "react-dom";

import { fetchMe } from "./api";
import MapPage from "./components/MapPage";
import ProfilePage from "./components/ProfilePage";
import type { Me } from "./types";

type View = "map" | "profile";

function viewFromPath(): View {
  return window.location.pathname === "/profile" ? "profile" : "map";
}

/**
 * Swap the view inside a hero view-transition when the browser supports it
 * and the user hasn't asked for reduced motion; otherwise swap instantly.
 * The shared elements (avatar + username, see styles.css) morph between the
 * sidebar user chip and the profile identity card.
 *
 * The state update must be flushed synchronously inside the callback:
 * startViewTransition captures the new snapshot right after the callback
 * returns, and React 18 would otherwise batch the setState until after the
 * event dispatch — Firefox then captures old == new and no animation runs.
 */
function transitionTo(update: () => void): void {
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduced || typeof document.startViewTransition !== "function") {
    update();
    return;
  }
  document.startViewTransition(() => flushSync(update));
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
    const onPopState = () => transitionTo(() => setView(viewFromPath()));
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const openProfile = () => {
    window.history.pushState({}, "", "/profile");
    transitionTo(() => setView("profile"));
  };
  const backToMap = () => {
    window.history.pushState({}, "", "/");
    transitionTo(() => setView("map"));
  };

  if (view === "profile" && userLoaded && user) {
    return <ProfilePage user={user} onBack={backToMap} />;
  }
  return <MapPage user={user} userLoaded={userLoaded} onOpenProfile={openProfile} />;
}
