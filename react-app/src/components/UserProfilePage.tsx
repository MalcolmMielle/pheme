import { useEffect, useState } from "react";

import {
  actorServer,
  avatarColor,
  errorFromResponse,
  fetchMyFollowing,
  fetchUserProfile,
  followActor,
  unfollowActor,
} from "../api";
import ReviewCard from "./ReviewCard";
import ThemeToggle from "./ThemeToggle";
import type { Me, UserProfile } from "../types";

interface UserProfilePageProps {
  actorId: number;
  /** Logged-in user (null when logged out) — the follow button needs a session. */
  user: Me | null;
  onBack: () => void;
}

/**
 * Public profile page for another actor — the SPA route /u/<id>, reached by
 * clicking a review's author on the map. Shows the identity card, a
 * follow/unfollow button (logged-in users, any actor but yourself — local
 * follows are accepted immediately by the server), and their reviews
 * (GET /api/users/{id}). Unlike /profile (the own-account page) there is no
 * following list, follow form, admin panel or logout here.
 */
export default function UserProfilePage({ actorId, user, onBack }: UserProfilePageProps) {
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [error, setError] = useState<string | null>(null);
  /** actor_uris the logged-in user already follows (null = unknown/logged out). */
  const [followingUris, setFollowingUris] = useState<Set<string> | null>(null);
  const [busy, setBusy] = useState(false);
  const [followError, setFollowError] = useState<string | null>(null);
  const [followMsg, setFollowMsg] = useState<string | null>(null);

  useEffect(() => {
    setProfile(null);
    setError(null);
    fetchUserProfile(actorId)
      .then(setProfile)
      .catch((err) => setError((err as Error).message));
  }, [actorId]);

  // Who the logged-in user follows — drives the button's Follow/Unfollow state.
  useEffect(() => {
    if (!user) return;
    fetchMyFollowing()
      .then((data) => {
        if (data !== null) setFollowingUris(new Set(data.map((f) => f.actor_uri)));
      })
      .catch(() => {});
  }, [user]);

  const isFollowing = profile != null && followingUris?.has(profile.actor_uri) === true;
  /** The follow button is for other actors only — never on your own profile. */
  const canFollow = !!user && !!profile && profile.id !== user.id;

  const toggleFollow = async () => {
    if (!profile) return;
    setBusy(true);
    setFollowError(null);
    setFollowMsg(null);
    try {
      const resp = isFollowing
        ? await unfollowActor(profile.actor_uri)
        : await followActor(profile.actor_uri);
      if (resp.status === 401) {
        // Session gone — go to the login page.
        window.location.href = "/login";
        return;
      }
      if (!resp.ok) {
        setFollowError(await errorFromResponse(resp));
        return;
      }
      const data = await resp.json().catch(() => null);
      setFollowingUris((prev) => {
        const next = new Set(prev ?? []);
        if (isFollowing) next.delete(profile.actor_uri);
        else next.add(profile.actor_uri);
        return next;
      });
      if (!isFollowing) {
        setFollowMsg(
          data?.delivered
            ? "Follow sent — their new reviews will appear on your map."
            : "Follow stored, but delivery to the remote server failed. Is it running?",
        );
      }
    } catch (err) {
      setFollowError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const server = profile ? actorServer(profile.actor_uri) : "";
  const handle = profile
    ? server
      ? `${profile.username}@${server}`
      : profile.username
    : "";
  const displayName = profile?.display_name || profile?.username || "";

  return (
    <div className="profile-page profile-page-public">
      <header className="profile-header">
        <button type="button" className="btn btn-sm btn-ghost" onClick={onBack}>
          ← Map
        </button>
        <h1>Profile</h1>
        <ThemeToggle />
      </header>

      <div className="profile-content">
        {error && <div className="form-error">{error}</div>}
        {!profile && !error && <p className="profile-empty">Loading…</p>}
        {profile && (
          <>
            <section className="profile-card">
              <div className="profile-banner" aria-hidden="true" />
              <div className="profile-id">
                <span
                  className="avatar profile-avatar"
                  style={{ background: avatarColor(displayName) }}
                  aria-hidden="true"
                >
                  {displayName.charAt(0)}
                </span>
                <div className="profile-id-text">
                  <div className="profile-name">{displayName}</div>
                  <div className="profile-handle">@{handle}</div>
                </div>
                {profile.is_admin && <span className="admin-badge">admin</span>}
                {canFollow && (
                  <button
                    type="button"
                    className={`btn btn-sm ${
                      isFollowing ? "btn-ghost" : "btn-primary"
                    } profile-follow-btn`}
                    disabled={busy}
                    onClick={() => void toggleFollow()}
                  >
                    {busy ? "Working…" : isFollowing ? "Unfollow" : "Follow"}
                  </button>
                )}
              </div>
            </section>

            {followError && <div className="form-error">{followError}</div>}
            {followMsg && <div className="form-success">{followMsg}</div>}

            <section className="profile-section">
              <h2 className="profile-section-title">
                Reviews{" "}
                <span className="review-count">{profile.review_count}</span>
              </h2>
              {profile.reviews.length === 0 ? (
                <p className="profile-empty">No reviews yet.</p>
              ) : (
                <div className="review-list profile-review-list">
                  {profile.reviews.map((r) => (
                    <ReviewCard key={r.id} review={r} />
                  ))}
                </div>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  );
}
