import { logout } from "../api";

/** Log out (POST /logout) and reload to the map, dropping the session. */
export default function LogoutButton({ label = "Logout" }: { label?: string }) {
  return (
    <button
      type="button"
      className="btn btn-sm btn-ghost"
      onClick={() => void logout()}
    >
      <svg
        width="14"
        height="14"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
        <polyline points="16 17 21 12 16 7" />
        <line x1="21" y1="12" x2="9" y2="12" />
      </svg>
      {label}
    </button>
  );
}
