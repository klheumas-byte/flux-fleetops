import { useEffect, useState, type FormEvent } from 'react';
import { KeyRound, Loader2, LogOut } from 'lucide-react';
import { apiRequest, ApiRequestError } from '../lib/api';
import type { SessionUser } from '../lib/auth-session';

export default function ChangePassword({ onChanged, onLogout, optional = false, onSkip }: { onChanged: (user: SessionUser) => void; onLogout: () => void; optional?: boolean; onSkip?: () => void }) {
  const [form, setForm] = useState({ current_password: '', new_password: '', confirm_password: '' });
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  useEffect(() => { window.history.replaceState({ page: 'change-password' }, '', '/change-password'); }, []);
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const response = await apiRequest<{ data: { user: SessionUser } }>('/auth/change-password', { method: 'POST', body: JSON.stringify(form) });
      onChanged(response.data.user);
    } catch (caught) { setError(caught instanceof ApiRequestError || caught instanceof Error ? caught.message : 'Password could not be changed.'); }
    finally { setBusy(false); }
  };
  return <main className="flex min-h-screen items-center justify-center bg-slate-100 p-4"><section className="w-full max-w-md rounded-2xl border bg-white p-6 shadow-sm"><div className="mb-5 flex items-center gap-3"><span className="rounded-xl bg-blue-600 p-3 text-white"><KeyRound /></span><div><h1 className="text-xl font-bold">Change temporary password</h1><p className="text-sm text-slate-500">{optional?'For better security, replace the default password. You may continue and do this later.':'Set a private password before entering your account.'}</p></div></div>{error && <div className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>}<form onSubmit={submit} className="space-y-4">{[['current_password', 'Temporary password'], ['new_password', 'New password'], ['confirm_password', 'Confirm new password']].map(([name, label]) => <label key={name} className="block text-sm font-medium">{label}<input required minLength={name === 'current_password' ? 6 : 8} type="password" value={(form as any)[name]} onChange={(event) => setForm({ ...form, [name]: event.target.value })} className="mt-1 w-full rounded-lg border px-3 py-2.5" /></label>)}<button disabled={busy} className="flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-3 font-semibold text-white disabled:opacity-50">{busy && <Loader2 className="h-4 w-4 animate-spin" />}Change password</button></form>{optional&&<button type="button" onClick={onSkip} className="mt-3 w-full rounded-lg border px-4 py-2.5 text-sm font-medium text-slate-700">Continue for now</button>}<button onClick={onLogout} className="mt-4 flex w-full items-center justify-center gap-2 text-sm text-slate-500"><LogOut className="h-4 w-4" />Sign out</button></section></main>;
}
