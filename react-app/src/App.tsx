import { useEffect, useState } from "react";
import { flushSync } from "react-dom";

import { fetchMe, fetchMeta } from "./api";
import MapPage from "./components/MapPage";
import ProfilePage from "./components/ProfilePage";
import UserProfilePage from "./components/UserProfilePage";
import { configurePlaceDecimals } from "./places";
import type { Me } from "./types";

type View = "map" | "profile" | "user";

function viewFromPath(): View {
  const path = window.location.pathname;
  if (path === "/profile") return "profile";
  if (/^\/u\/\d+/.test(path)) return "user";
  return "map";
}

/** The actor id of a /u/<id> path, or null when the path isn't one. */
function actorIdFromPath(): number | null {
  const m = window.location.pathname.match(/^\/u\/(\d+)/);
  return m ? Number(m[1]) : null;
}

/**
 * Swap the view inside a hero view-transition when the browser supports it
 * and the user hasn't asked for reduced motion; otherwise swap instantly.
 * The shared elements (avatar + username, see styles.css) morph between the
 * floating account button and the own-profile identity card.
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
    // Match the server's place-bucket precision (PLACE_DECIMALS) so the
    // SPA groups coordinates into places exactly like the server does.
    fetchMeta()
      .then((meta) => configurePlaceDecimals(meta.place_decimals))
      .catch((err) => console.error("Failed to load server meta", err));
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
  /** Open another actor's public profile page (/u/<id>). */
  const openUserProfile = (actorId: number) => {
    window.history.pushState({}, "", `/u/${actorId}`);
    transitionTo(() => setView("user"));
  };
  const backToMap = () => {
    window.history.pushState({}, "", "/");
    transitionTo(() => setView("map"));
  };

  if (view === "user") {
    const actorId = actorIdFromPath();
    if (actorId != null) {
      return <UserProfilePage actorId={actorId} user={user} onBack={backToMap} />;
    }
  }
  if (view === "profile" && userLoaded && user) {
    return <ProfilePage user={user} onBack={backToMap} />;
  }
  return (
    <MapPage
      user={user}
      userLoaded={userLoaded}
      onOpenProfile={openProfile}
      onOpenUserProfile={openUserProfile}
    />
  );
}
