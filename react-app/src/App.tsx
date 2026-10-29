import { useEffect, useState } from "react";

import { fetchMe } from "./api";
import MapPage from "./components/MapPage";
import type { Me } from "./types";

export default function App() {
  const [user, setUser] = useState<Me | null>(null);
  const [userLoaded, setUserLoaded] = useState(false);

  useEffect(() => {
    fetchMe()
      .then(setUser)
      .catch((err) => console.error("Failed to load current user", err))
      .finally(() => setUserLoaded(true));
  }, []);

  return <MapPage user={user} userLoaded={userLoaded} />;
}
