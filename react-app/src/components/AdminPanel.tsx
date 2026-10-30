import { useCallback, useEffect, useState } from "react";

import { createUser, fetchAdminUsers, setUserAdmin } from "../api";
import type { AdminUser, Me } from "../types";

interface AdminPanelProps {
  currentUser: Me;
  onClose: () => void;
}

/** Pull a human-readable message out of a failed admin API response. */
async function errorDetail(resp: Response): Promise<string> {
  const data = await resp.json().catch(() => null);
  if (data && typeof data.detail === "string") return data.detail;
  return `Server error: ${resp.status}`;
}

/**
 * Admin panel — lists local accounts and lets an admin create new accounts
 * (optionally as admins) and promote/demote existing ones. Replaces the
 * sidebar content while open; only rendered for admin users.
 */
export default function AdminPanel({ currentUser, onClose }: AdminPanelProps) {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [adminCount, setAdminCount] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // New-account form state
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [makeAdmin, setMakeAdmin] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await fetchAdminUsers();
      setUsers(data.users);
      setAdminCount(data.admin_count);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  /** Run an admin action; on 401 the session is gone — go to /login. */
  const runAction = useCallback(
    async (action: () => Promise<Response>): Promise<boolean> => {
      setBusy(true);
      setError(null);
      try {
        const resp = await action();
        if (resp.status === 401) {
          window.location.href = "/login";
          return false;
        }
        if (!resp.ok) {
          setError(await errorDetail(resp));
          return false;
        }
        await load();
        return true;
      } catch (err) {
        setError((err as Error).message);
        return false;
      } finally {
        setBusy(false);
      }
    },
    [load],
  );

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password) {
      setError("Username and password are required.");
      return;
    }
    const ok = await runAction(() =>
      createUser(
        {
          username: username.trim(),
          displayName: displayName.trim() || username.trim(),
          password,
          isAdmin: makeAdmin,
        },
        currentUser.csrf_token,
      ),
    );
    if (ok) {
      setUsername("");
      setDisplayName("");
      setPassword("");
      setMakeAdmin(false);
    }
  };

  const toggleAdmin = (user: AdminUser) =>
    runAction(() =>
      setUserAdmin(user.id, !user.is_admin, currentUser.csrf_token),
    );

  return (
    <div className="admin-panel">
      <div className="panel-header">
        <h2>
          Admin <span className="review-count">{adminCount} admin{adminCount !== 1 ? "s" : ""}</span>
        </h2>
        <button
          type="button"
          className="icon-btn"
          onClick={onClose}
          aria-label="Back to map"
        >
          ✕
        </button>
      </div>

      {error && <div className="form-error admin-error">{error}</div>}

      <div className="admin-user-list">
        {users === null ? (
          <p className="admin-loading">Loading users…</p>
        ) : users.length === 0 ? (
          <p className="admin-loading">No accounts yet.</p>
        ) : (
          users.map((u) => (
            <div className="admin-user" key={u.id}>
              <span className="admin-user-name">
                {u.display_name || u.username}
                <span className="admin-user-username">@{u.username}</span>
                {u.is_admin && <span className="admin-badge">admin</span>}
              </span>
              {u.id === currentUser.id ? (
                <span className="admin-you">you</span>
              ) : (
                <button
                  type="button"
                  className={`btn btn-sm ${u.is_admin ? "btn-danger-soft" : "btn-secondary"}`}
                  disabled={busy}
                  onClick={() => toggleAdmin(u)}
                >
                  {u.is_admin ? "Remove admin" : "Make admin"}
                </button>
              )}
            </div>
          ))
        )}
      </div>

      <form className="admin-form" onSubmit={handleCreate}>
        <label htmlFor="admin-username">New account</label>
        <input
          id="admin-username"
          placeholder="Username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="off"
        />
        <input
          placeholder="Display name"
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          autoComplete="off"
        />
        <input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="new-password"
        />
        <label className="admin-checkbox">
          <input
            type="checkbox"
            checked={makeAdmin}
            onChange={(e) => setMakeAdmin(e.target.checked)}
          />
          Create as admin
        </label>
        <button type="submit" className="btn btn-primary" disabled={busy}>
          {busy ? "Working…" : "Create Account"}
        </button>
      </form>
    </div>
  );
}
