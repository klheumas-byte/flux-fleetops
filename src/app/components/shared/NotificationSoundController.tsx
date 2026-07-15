import { useEffect, useState } from 'react';
import { BellRing, Volume2, X } from 'lucide-react';
import {
  getNotificationSoundState,
  initializeNotificationSound,
  playNotificationSound,
  unlockNotificationSound,
} from '../../lib/notification-sound';

export default function NotificationSoundController() {
  const [state, setState] = useState(getNotificationSoundState);
  const [dismissed, setDismissed] = useState(false);
  useEffect(() => {
    const cleanup = initializeNotificationSound();
    const update = (event: Event) => setState((event as CustomEvent<ReturnType<typeof getNotificationSoundState>>).detail);
    window.addEventListener('flux-notification-sound-state', update);
    setState(getNotificationSoundState());
    return () => { window.removeEventListener('flux-notification-sound-state', update); cleanup(); };
  }, []);
  if (!state.enabled || state.unlocked || dismissed) return null;
  return <div role="status" className="fixed bottom-4 right-4 z-[80] max-w-sm rounded-xl border border-amber-300 bg-white p-4 shadow-xl">
    <button aria-label="Dismiss notification sound prompt" onClick={() => setDismissed(true)} className="absolute right-2 top-2 rounded p-1 text-slate-500 hover:bg-slate-100"><X size={15}/></button>
    <div className="flex gap-3 pr-6"><BellRing className="mt-0.5 text-amber-600" size={20}/><div><div className="font-semibold text-slate-900">Enable notification sound</div><p className="mt-1 text-sm text-slate-600">Your browser needs one tap before in-app alerts can make sound.</p></div></div>
    <div className="mt-3 flex gap-2"><button onClick={() => void unlockNotificationSound()} className="rounded-lg bg-amber-500 px-3 py-2 text-sm font-medium text-white">Enable sound</button><button onClick={() => void unlockNotificationSound().then(() => playNotificationSound('action_required'))} className="inline-flex items-center gap-1 rounded-lg border px-3 py-2 text-sm"><Volume2 size={15}/>Test sound</button></div>
  </div>;
}
