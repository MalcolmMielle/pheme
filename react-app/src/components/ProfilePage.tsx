import { useEffect, useState } from "react";

import {
  actorServer,
  avatarColor,
  errorFromResponse,
  fetchMyFollowing,
  unfollowActor,
} from "../api";
import AdminPanel from "./AdminPanel";
import FollowPanel from "./FollowPanel";
import LogoutButton from "./LogoutButton";
import ThemeToggle from "./ThemeToggle";
import type { FollowingEntry, Me } from "../types";

interface ProfilePageProps {
  user: Me;
  onBack: () => void;
}

/**
 * Profile page — the logged-in user's account card (name, handle, server),
 * the list of actors they follow across servers, the follow form, and
 * (for admins) the admin section. Data comes from /api/me and
 * /api/me/following; rendered at the /profile URL.
 */
export default function ProfilePage({ user, onBack }: ProfilePageProps) {
  const [following, setFollowing] = useState<FollowingEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** actor_uri currently being unfollowed (disables its button). */
  const [busyUri, setBusyUri] = useState<string | null>(null);

  useEffect(() => {
    fetchMyFollowing()
      .then((data) => {
        if (data === null) {
          // Session gone — go to the login page.
          window.location.href = "/login";
          return;
        }
        setFollowing(data);
      })
      .catch((err) => setError((err as Error).message));
  }, []);

  /** Unfollow a followed actor; removes it from the list on success. */
  const handleUnfollow = async (entry: FollowingEntry) => {
    setBusyUri(entry.actor_uri);
    setError(null);
    try {
      const resp = await unfollowActor(entry.actor_uri);
      if (resp.status === 401) {
        window.location.href = "/login";
        return;
      }
      if (!resp.ok) {
        setError(await errorFromResponse(resp));
        return;
      }
      setFollowing((prev) => prev?.filter((f) => f.actor_uri !== entry.actor_uri) ?? prev);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusyUri(null);
    }
  };

  const server = actorServer(user.actor_uri);
  const handle = server ? `${user.username}@${server}` : user.username;
  const displayName = user.display_name || user.username;

  return (
    <div className="profile-page">
      <header className="profile-header">
        <button type="button" className="btn btn-sm btn-ghost" onClick={onBack}>
          ← Map
        </button>
        <h1>Profile</h1>
        <ThemeToggle />
        <LogoutButton label="Log out" />
      </header>

      <div className="profile-content">
        <section className="profile-card">
          <div className="profile-banner" aria-hidden="true" />
          <div className="profile-id">
            <span className="avatar profile-avatar" aria-hidden="true">
              {displayName.charAt(0)}
            </span>
            <div className="profile-id-text">
              <div className="profile-name">{displayName}</div>
              <div className="profile-handle">@{handle}</div>
            </div>
            {user.is_admin && <span className="admin-badge">admin</span>}
          </div>
        </section>

        <section className="profile-section">
          <h2 className="profile-section-title">
            Following{" "}
            <span className="review-count">
              {following === null ? "…" : following.length}
            </span>
          </h2>

          {error && <div className="form-error">{error}</div>}

          {following === null && !error ? (
            <p className="profile-empty">Loading…</p>
          ) : following && following.length === 0 ? (
            <p className="profile-empty">
              You&apos;re not following anyone yet. Use the follow form below to
              subscribe to a user on another server — their new reviews will
              appear on your map.
            </p>
          ) : (
            <div className="following-list">
              {following?.map((f) => {
                const fserver = actorServer(f.actor_uri);
                return (
                  <div className="following-item" key={f.actor_uri}>
                    <span
                      className="avatar following-avatar"
                      style={{
                        background: avatarColor(f.display_name || f.username),
                      }}
                      aria-hidden="true"
                    >
                      {(f.display_name || f.username).charAt(0)}
                    </span>
                    <span className="following-name">
                      {f.display_name || f.username}
                      <span className="following-username">
                        @{f.username}
                        {fserver && <span className="following-server"> @{fserver}</span>}
                      </span>
                    </span>
                    <button
                      type="button"
                      className="btn btn-sm btn-ghost following-unfollow"
                      disabled={busyUri === f.actor_uri}
                      onClick={() => handleUnfollow(f)}
                    >
                      {busyUri === f.actor_uri ? "…" : "Unfollow"}
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </section>

        <section className="profile-section">
          <h2 className="profile-section-title">Follow a user</h2>
          <FollowPanel />
        </section>

        {user.is_admin && (
          <section className="profile-section">
            <AdminPanel currentUser={user} />
          </section>
        )}
      </div>
    </div>
  );
}
