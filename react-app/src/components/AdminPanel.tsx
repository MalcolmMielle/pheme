import { useCallback, useEffect, useState } from "react";

import {
  createInvite,
  createUser,
  deleteInvite,
  deleteUser,
  fetchAdminInvites,
  fetchAdminUsers,
  setUserAdmin,
  setUserSuspended,
} from "../api";
import type { Invite } from "../api";
import type { AdminUser, Me } from "../types";

interface AdminPanelProps {
  currentUser: Me;
}

/** Pull a human-readable message out of a failed admin API response. */
async function errorDetail(resp: Response): Promise<string> {
  const data = await resp.json().catch(() => null);
  if (data && typeof data.detail === "string") return data.detail;
  return `Server error: ${resp.status}`;
}

/**
 * Admin section — lists local accounts and lets an admin create new accounts
 * (optionally as admins) and promote/demote existing ones.
 * Embedded in the profile page; only rendered for admin users.
 */
export default function AdminPanel({ currentUser }: AdminPanelProps) {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [adminCount, setAdminCount] = useState(0);
  const [invites, setInvites] = useState<Invite[] | null>(null);
  const [registrationMode, setRegistrationMode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // New-account form state
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [makeAdmin, setMakeAdmin] = useState(false);

  // New-invite form state
  const [expiresDays, setExpiresDays] = useState("");

  const load = useCallback(async () => {
    try {
      const [data, inviteData] = await Promise.all([
        fetchAdminUsers(),
        fetchAdminInvites(),
      ]);
      setUsers(data.users);
      setAdminCount(data.admin_count);
      setInvites(inviteData.invites);
      setRegistrationMode(inviteData.registration_mode);
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
      createUser({
        username: username.trim(),
        displayName: displayName.trim() || username.trim(),
        password,
        isAdmin: makeAdmin,
      }),
    );
    if (ok) {
      setUsername("");
      setDisplayName("");
      setPassword("");
      setMakeAdmin(false);
    }
  };

  const toggleAdmin = (user: AdminUser) =>
    runAction(() => setUserAdmin(user.id, !user.is_admin));

  const toggleSuspended = (user: AdminUser) =>
    runAction(() => setUserSuspended(user.id, !user.is_suspended));

  const removeUser = (user: AdminUser) => {
    if (!window.confirm(`Delete @${user.username} and all their reviews?`)) return;
    return runAction(() => deleteUser(user.id));
  };

  const handleCreateInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = expiresDays.trim();
    const days = trimmed === "" ? null : Number(trimmed);
    if (days !== null && (!Number.isInteger(days) || days < 1)) {
      setError("Expiry must be a positive whole number of days (or empty).");
      return;
    }
    const ok = await runAction(() => createInvite(days));
    if (ok) setExpiresDays("");
  };

  const revokeInvite = (invite: Invite) =>
    runAction(() => deleteInvite(invite.id));

  const [copiedId, setCopiedId] = useState<number | null>(null);

  /** Copy the invite's registration URL to the clipboard, with feedback. */
  const copyInvite = async (invite: Invite) => {
    try {
      await navigator.clipboard.writeText(invite.register_url);
    } catch {
      // Clipboard API unavailable (non-secure context) — legacy fallback.
      const ta = document.createElement("textarea");
      ta.value = invite.register_url;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    setCopiedId(invite.id);
    setTimeout(() => setCopiedId((cur) => (cur === invite.id ? null : cur)), 1500);
  };

  return (
    <div className="admin-panel">
      <h2>
        Admin <span className="review-count">{adminCount} admin{adminCount !== 1 ? "s" : ""}</span>
      </h2>

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
                {u.is_suspended && <span className="admin-badge">suspended</span>}
              </span>
              {u.id === currentUser.id ? (
                <span className="admin-you">you</span>
              ) : (
                <span className="admin-user-actions">
                  <button
                    type="button"
                    className={`btn btn-sm ${u.is_admin ? "btn-danger-soft" : "btn-secondary"}`}
                    disabled={busy}
                    onClick={() => toggleAdmin(u)}
                  >
                    {u.is_admin ? "Remove admin" : "Make admin"}
                  </button>
                  <button
                    type="button"
                    className={`btn btn-sm ${u.is_suspended ? "btn-secondary" : "btn-danger-soft"}`}
                    disabled={busy}
                    onClick={() => toggleSuspended(u)}
                  >
                    {u.is_suspended ? "Unsuspend" : "Suspend"}
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm btn-danger-soft"
                    disabled={busy}
                    onClick={() => void removeUser(u)}
                  >
                    Delete
                  </button>
                </span>
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

      <div className="admin-invites">
        <h3>
          Invite codes{" "}
          <span className="review-count">registration: {registrationMode || "?"}</span>
        </h3>
        {invites === null ? (
          <p className="admin-loading">Loading invites…</p>
        ) : invites.length === 0 ? (
          <p className="admin-loading">No invite codes yet.</p>
        ) : (
          invites.map((inv) => (
            <div className="admin-user" key={inv.id}>
              <span className="admin-user-name">
                <code>{inv.register_url}</code>
                {inv.used_by ? (
                  <span className="admin-badge">used by @{inv.used_by}</span>
                ) : inv.expires_at ? (
                  <span className="admin-user-username">expires {inv.expires_at}</span>
                ) : (
                  <span className="admin-user-username">no expiry</span>
                )}
              </span>
              <span className="admin-user-actions">
                <button
                  type="button"
                  className="btn btn-sm btn-secondary"
                  disabled={busy}
                  onClick={() => void copyInvite(inv)}
                >
                  {copiedId === inv.id ? "Copied!" : "Copy link"}
                </button>
                {!inv.used_by && (
                  <button
                    type="button"
                    className="btn btn-sm btn-danger-soft"
                    disabled={busy}
                    onClick={() => revokeInvite(inv)}
                  >
                    Revoke
                  </button>
                )}
              </span>
            </div>
          ))
        )}
        <form className="admin-form" onSubmit={handleCreateInvite}>
          <label htmlFor="admin-invite-expiry">New invite code</label>
          <input
            id="admin-invite-expiry"
            placeholder="Expires in days (optional)"
            value={expiresDays}
            onChange={(e) => setExpiresDays(e.target.value)}
            autoComplete="off"
            inputMode="numeric"
          />
          <button type="submit" className="btn btn-secondary" disabled={busy}>
            {busy ? "Working…" : "Create Invite"}
          </button>
        </form>
      </div>
    </div>
  );
}
