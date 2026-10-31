import { useState } from "react";

import { followActor } from "../api";
import type { Me } from "../types";

interface FollowPanelProps {
  currentUser: Me;
}

interface FollowResult {
  target: string;
  delivered: boolean;
}

/**
 * Follow section — let the logged-in user follow an actor on another server
 * by handle (user@domain) or full actor URI. POSTs to /api/follow, which
 * resolves the target via WebFinger, then sends a signed Follow activity
 * to the remote inbox; the remote server auto-accepts and starts
 * federating that actor's new reviews to this server.
 * Embedded in the profile page.
 */
export default function FollowPanel({ currentUser }: FollowPanelProps) {
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<FollowResult | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const value = target.trim();
    if (!value) {
      setError("Enter a user@domain or an actor URL.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const resp = await followActor(value, currentUser.csrf_token);
      if (resp.status === 401) {
        // Session gone — go to the login page.
        window.location.href = "/login";
        return;
      }
      const data = await resp.json().catch(() => null);
      if (!resp.ok) {
        setError(
          data && typeof data.detail === "string"
            ? data.detail
            : `Server error: ${resp.status}`,
        );
        return;
      }
      setResult({
        target: typeof data?.target === "string" ? data.target : value,
        delivered: Boolean(data?.delivered),
      });
      setTarget("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="follow-panel">
      <p className="follow-hint">
        Enter a handle like <code>alice@example.com</code> or a full actor URL
        like <code>https://example.com/actor/alice</code>. Once you follow
        someone, their new reviews appear on your map.
      </p>

      {error && <div className="form-error follow-error">{error}</div>}
      {result && (
        <div className="form-success follow-success">
          {result.delivered
            ? `Follow sent to ${result.target} — their new reviews will appear on your map.`
            : `Follow stored for ${result.target}, but delivery to the remote server failed. Is it running?`}
        </div>
      )}

      <form className="follow-form" onSubmit={handleSubmit}>
        <input
          placeholder="user@domain or actor URL"
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          autoComplete="off"
          autoFocus
        />
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? "Sending…" : "Follow"}
        </button>
      </form>
    </div>
  );
}
