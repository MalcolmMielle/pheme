import { useEffect, useState } from "react";

import {
  actorServer,
  avatarColor,
  errorFromResponse,
  fetchMyFollowing,
  fetchUserProfile,
  unfollowActor,
} from "../api";
import AdminPanel from "./AdminPanel";
import FollowPanel from "./FollowPanel";
import LogoutButton from "./LogoutButton";
import ReviewCard from "./ReviewCard";
import ThemeToggle from "./ThemeToggle";
import type { FollowingEntry, Me, UserProfile } from "../types";

interface ProfilePageProps {
  user: Me;
  onBack: () => void;
}

/**
 * Profile page — the logged-in user's account page, rendered at /profile.
 * The "Profile" tab shows what anyone else's profile (/u/<id>) shows —
 * identity card + own reviews — plus one merged Following section (the list
 * and the follow form together). Admins additionally get an "Admin" tab with
 * the admin section. Data comes from /api/me, /api/me/following and
 * /api/users/{id}.
 */
export default function ProfilePage({ user, onBack }: ProfilePageProps) {
  const [following, setFollowing] = useState<FollowingEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** actor_uri currently being unfollowed (disables its button). */
  const [busyUri, setBusyUri] = useState<string | null>(null);
  /** Admin accounts get a Profile/Admin tab switch. */
  const [tab, setTab] = useState<"profile" | "admin">("profile");
  /** Own public profile — its reviews render in the Profile tab. */
  const [myProfile, setMyProfile] = useState<UserProfile | null>(null);

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

  useEffect(() => {
    fetchUserProfile(user.id)
      .then(setMyProfile)
      .catch(() => {});
  }, [user.id]);

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

  const showProfileTab = !user.is_admin || tab === "profile";

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
        {user.is_admin && (
          <div className="profile-tabs" role="tablist" aria-label="Profile sections">
            <button
              type="button"
              role="tab"
              aria-selected={tab === "profile"}
              className={tab === "profile" ? "active" : ""}
              onClick={() => setTab("profile")}
            >
              Profile
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "admin"}
              className={tab === "admin" ? "active" : ""}
              onClick={() => setTab("admin")}
            >
              Admin
            </button>
          </div>
        )}

        {showProfileTab && (
          <>
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
                            {fserver && (
                              <span className="following-server"> @{fserver}</span>
                            )}
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

              <FollowPanel />
            </section>

            <section className="profile-section">
              <h2 className="profile-section-title">
                Reviews{" "}
                <span className="review-count">
                  {myProfile ? myProfile.review_count : "…"}
                </span>
              </h2>
              {myProfile === null ? (
                <p className="profile-empty">Loading…</p>
              ) : myProfile.reviews.length === 0 ? (
                <p className="profile-empty">
                  You haven&apos;t written any reviews yet.
                </p>
              ) : (
                <div className="review-list profile-review-list">
                  {myProfile.reviews.map((r) => (
                    <ReviewCard key={r.id} review={r} />
                  ))}
                </div>
              )}
            </section>
          </>
        )}

        {user.is_admin && tab === "admin" && (
          <section className="profile-section">
            <AdminPanel currentUser={user} />
          </section>
        )}
      </div>
    </div>
  );
}
