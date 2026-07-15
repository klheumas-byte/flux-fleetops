export type NotificationSoundPriority = 'information' | 'reminder' | 'action_required' | 'critical';

const ENABLED_KEY = 'flux_notification_sounds_enabled';
const PLAYED_KEY = 'flux_notification_sound_last_event';
const CHANNEL_NAME = 'flux-notification-sound';

let context: AudioContext | null = null;
let unlocked = false;
let initialized = false;
let channel: BroadcastChannel | null = null;
let tabId = '';

function enabled() {
  return localStorage.getItem(ENABLED_KEY) !== 'false';
}

function notifyState() {
  window.dispatchEvent(new CustomEvent('flux-notification-sound-state', {
    detail: { enabled: enabled(), unlocked, supported: Boolean(window.AudioContext) },
  }));
}

function ensureContext() {
  if (!window.AudioContext) return null;
  context ||= new AudioContext({ latencyHint: 'interactive' });
  return context;
}

export async function unlockNotificationSound() {
  if (!enabled()) return false;
  const audio = ensureContext();
  if (!audio) { notifyState(); return false; }
  try {
    await audio.resume();
    const buffer = audio.createBuffer(1, 1, audio.sampleRate);
    const source = audio.createBufferSource();
    source.buffer = buffer;
    source.connect(audio.destination);
    source.start();
    unlocked = audio.state === 'running';
    notifyState();
    return unlocked;
  } catch (error) {
    console.info('[Flux Notifications] Sound remains locked until the browser accepts a user gesture.', error);
    notifyState();
    return false;
  }
}

function tone(audio: AudioContext, frequency: number, start: number, duration: number, gainValue: number) {
  const oscillator = audio.createOscillator();
  const gain = audio.createGain();
  oscillator.type = 'sine';
  oscillator.frequency.setValueAtTime(frequency, start);
  gain.gain.setValueAtTime(0.0001, start);
  gain.gain.exponentialRampToValueAtTime(gainValue, start + 0.015);
  gain.gain.exponentialRampToValueAtTime(0.0001, start + duration);
  oscillator.connect(gain).connect(audio.destination);
  oscillator.start(start);
  oscillator.stop(start + duration + 0.02);
}

export async function playNotificationSound(priority: NotificationSoundPriority, eventId?: string) {
  if (!enabled() || priority === 'information') return false;
  if (eventId) {
    const last = localStorage.getItem(PLAYED_KEY);
    if (last === eventId) return false;
    localStorage.setItem(PLAYED_KEY, eventId);
    channel?.postMessage({ eventId, tabId });
  }
  const audio = ensureContext();
  if (!audio || !unlocked || audio.state !== 'running') {
    notifyState();
    console.info('[Flux Notifications] Tap Enable notification sound before audio can play.');
    return false;
  }
  const now = audio.currentTime + 0.01;
  if (priority === 'reminder') tone(audio, 660, now, 0.16, 0.06);
  else if (priority === 'critical') {
    tone(audio, 880, now, 0.17, 0.12);
    tone(audio, 1040, now + 0.2, 0.2, 0.12);
  } else {
    tone(audio, 720, now, 0.16, 0.09);
    tone(audio, 900, now + 0.16, 0.18, 0.09);
  }
  return true;
}

export function setNotificationSoundsEnabled(value: boolean) {
  localStorage.setItem(ENABLED_KEY, String(value));
  if (!value && context?.state === 'running') void context.suspend();
  unlocked = value && context?.state === 'running';
  notifyState();
}

export function getNotificationSoundState() {
  return { enabled: enabled(), unlocked, supported: typeof window !== 'undefined' && Boolean(window.AudioContext) };
}

export function initializeNotificationSound() {
  if (initialized) return () => undefined;
  initialized = true;
  tabId = crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`;
  if ('BroadcastChannel' in window) {
    channel = new BroadcastChannel(CHANNEL_NAME);
    channel.onmessage = (event) => {
      if (event.data?.eventId) localStorage.setItem(PLAYED_KEY, String(event.data.eventId));
    };
  }
  const unlock = () => { void unlockNotificationSound().then((success) => {
    if (success) ['pointerdown', 'keydown', 'touchstart'].forEach((name) => window.removeEventListener(name, unlock));
  }); };
  ['pointerdown', 'keydown', 'touchstart'].forEach((name) => window.addEventListener(name, unlock, { passive: true }));
  const onNotification = (event: Event) => {
    const detail = (event as CustomEvent<{ id?: string; priority?: NotificationSoundPriority }>).detail;
    if (detail?.id) void playNotificationSound(detail.priority || 'action_required', detail.id);
  };
  window.addEventListener('flux-new-actionable-notification', onNotification);
  notifyState();
  return () => {
    ['pointerdown', 'keydown', 'touchstart'].forEach((name) => window.removeEventListener(name, unlock));
    window.removeEventListener('flux-new-actionable-notification', onNotification);
    channel?.close(); channel = null; initialized = false;
  };
}
