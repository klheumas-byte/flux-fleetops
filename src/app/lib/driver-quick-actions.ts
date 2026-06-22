export type DriverQuickActionIntent =
  | 'submit_collection'
  | 'log_fuel'
  | 'create_booking'
  | 'create_reminder'
  | 'schedule_follow_up';

const QUICK_ACTION_STORAGE_KEY = 'flux_driver_quick_action_intent';

function canUseStorage() {
  return typeof window !== 'undefined' && typeof window.sessionStorage !== 'undefined';
}

export function setDriverQuickActionIntent(intent: DriverQuickActionIntent) {
  if (!canUseStorage()) {
    return;
  }
  window.sessionStorage.setItem(QUICK_ACTION_STORAGE_KEY, intent);
}

export function peekDriverQuickActionIntent(): DriverQuickActionIntent | null {
  if (!canUseStorage()) {
    return null;
  }
  const value = window.sessionStorage.getItem(QUICK_ACTION_STORAGE_KEY);
  if (!value) {
    return null;
  }
  return value as DriverQuickActionIntent;
}

export function clearDriverQuickActionIntent() {
  if (!canUseStorage()) {
    return;
  }
  window.sessionStorage.removeItem(QUICK_ACTION_STORAGE_KEY);
}
