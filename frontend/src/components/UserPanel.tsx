import type { UserContext, UserRole } from "../types";

const ROLE_LABELS: Record<UserRole, string> = {
  exec: "Executive",
  director: "Regional director",
  ram: "Territory manager"
};

interface UserPanelProps {
  users: UserContext[];
  currentUser: UserContext | null;
  disabled: boolean;
  onSelect: (userId: string) => void;
}

function scopeLabel(user: UserContext): string {
  if (user.territory_name) return user.territory_name;
  if (user.region_name) return user.region_name;
  return "All commercial data";
}

export function UserPanel({
  users,
  currentUser,
  disabled,
  onSelect
}: UserPanelProps) {
  const groupedUsers = (["ram", "director", "exec"] as const).map((role) => ({
    role,
    users: users.filter((user) => user.role === role)
  }));

  return (
    <aside className="user-panel" aria-label="Demo user controls">
      <div className="brand">
        <div className="brand-mark" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
        <div>
          <p className="brand-name">Nova Insights</p>
          <p className="brand-caption">Commercial analytics</p>
        </div>
      </div>

      <div className="demo-notice">
        <span className="notice-dot" aria-hidden="true" />
        <div>
          <strong>Secure demo</strong>
          <p>Synthetic pharmaceutical data only</p>
        </div>
      </div>

      <div className="control-group">
        <label htmlFor="demo-user">View as</label>
        <select
          id="demo-user"
          value={currentUser?.user_id ?? ""}
          disabled={disabled}
          onChange={(event) => onSelect(event.target.value)}
        >
          <option value="" disabled>
            Select a demo user
          </option>
          {groupedUsers.map(({ role, users: roleUsers }) => (
            <optgroup key={role} label={ROLE_LABELS[role]}>
              {roleUsers.map((user) => (
                <option key={user.user_id} value={user.user_id}>
                  {user.full_name}
                </option>
              ))}
            </optgroup>
          ))}
        </select>
      </div>

      {currentUser ? (
        <section className="scope-card" aria-label="Current access scope">
          <div className="avatar" aria-hidden="true">
            {currentUser.full_name
              .split(" ")
              .map((part) => part[0])
              .slice(0, 2)
              .join("")}
          </div>
          <div className="scope-identity">
            <strong>{currentUser.full_name}</strong>
            <span>{ROLE_LABELS[currentUser.role]}</span>
          </div>
          <dl>
            <div>
              <dt>Data scope</dt>
              <dd>{scopeLabel(currentUser)}</dd>
            </div>
            <div>
              <dt>Pricing</dt>
              <dd>{currentUser.can_view_wac ? "Available" : "Restricted"}</dd>
            </div>
          </dl>
        </section>
      ) : (
        <div className="scope-placeholder">
          Choose a user to apply their role and assigned business area.
        </div>
      )}

      <div className="security-note">
        <span aria-hidden="true">◆</span>
        <p>Your role and assigned business area are applied automatically.</p>
      </div>
    </aside>
  );
}
