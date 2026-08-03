import { toast } from 'sonner';
import { apiRequest } from '../../lib/api';
import {
  getWorkspaceLandingPage,
  setStoredSessionUser,
  type SessionUser,
} from '../../lib/auth-session';

export default function WorkspaceSwitcher({
  user,
  className = '',
}: {
  user: SessionUser | null | undefined;
  className?: string;
}) {
  const workspaces = (user?.roles || []).filter((role) => role.active !== false);
  if (!user || workspaces.length < 2) return null;

  const activeWorkspace = user.selected_workspace || user.role;
  const switchWorkspace = async (role: string) => {
    if (role === activeWorkspace) return;
    try {
      const response = await apiRequest<any>('/rbac/workspace', {
        method: 'POST',
        body: JSON.stringify({ role }),
      });
      if (response.data.access_token) localStorage.setItem('flux_token', response.data.access_token);
      const workspace = workspaces.find((item) => item.code === role);
      const updated: SessionUser = response.data.user || {
        ...user,
        selected_workspace: role,
        role_name: workspace?.name,
        dashboard: response.data.dashboard,
      };
      setStoredSessionUser(updated);
      window.dispatchEvent(new CustomEvent('flux-workspace-changed', {
        detail: {
          role,
          user: updated,
          dashboard: getWorkspaceLandingPage(role, response.data.dashboard || updated.dashboard),
        },
      }));
      toast.success(`Switched to ${workspace?.name || role}.`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to switch workspace.');
    }
  };

  return (
    <label className={`flex items-center gap-2 ${className}`}>
      <span className="sr-only">Active workspace</span>
      <select
        aria-label="Active workspace"
        value={activeWorkspace}
        onChange={(event) => void switchWorkspace(event.target.value)}
        className="max-w-52 rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs font-medium text-slate-700 shadow-sm"
      >
        {workspaces.map((workspace) => (
          <option key={workspace.code} value={workspace.code}>{workspace.name}</option>
        ))}
      </select>
    </label>
  );
}
