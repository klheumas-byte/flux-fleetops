import { Loader2, X } from 'lucide-react';
import type { ReactNode } from 'react';
import { FuelGaugeSelector } from './FuelGaugeSelector';

export type MovementFuelDraft = {
  fuel: number | null;
  odometer: string;
  notes: string;
};

export function MovementFuelDialog({
  mode,
  vehicleLabel,
  draft,
  busy,
  error,
  openingFuel,
  title,
  confirmLabel,
  onChange,
  onClose,
  onConfirm,
  children,
}: {
  mode: 'start' | 'return';
  vehicleLabel?: string | null;
  draft: MovementFuelDraft;
  busy: boolean;
  error?: string;
  openingFuel?: number | null;
  title?: string;
  confirmLabel?: string;
  onChange: (draft: MovementFuelDraft) => void;
  onClose: () => void;
  onConfirm: () => void;
  children?: ReactNode;
}) {
  const starting = mode === 'start';
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-slate-950/50 sm:items-center sm:p-4">
      <section className="flex max-h-[100dvh] w-full max-w-lg flex-col overflow-hidden rounded-t-2xl bg-white shadow-xl sm:max-h-[90dvh] sm:rounded-2xl">
        <header className="flex items-start justify-between gap-3 border-b px-4 py-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">{title || (starting ? 'Start Movement' : 'End / Return Movement')}</h2>
            <p className="mt-1 text-sm text-slate-500">Vehicle: {vehicleLabel || 'Assigned vehicle'}</p>
          </div>
          <button type="button" onClick={onClose} disabled={busy} className="rounded-lg p-2 text-slate-500 disabled:opacity-50" aria-label="Close"><X className="h-5 w-5" /></button>
        </header>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
          <FuelGaugeSelector
            label={starting ? 'Departure fuel' : 'Return fuel'}
            value={draft.fuel}
            onChange={(fuel) => onChange({ ...draft, fuel })}
            compareToValue={starting ? null : openingFuel}
            required
            compact
            disabled={busy}
            error={error && draft.fuel == null ? error : undefined}
          />
          <label className="block text-sm font-medium text-slate-700">
            {starting ? 'Opening' : 'Closing'} odometer (optional)
            <input type="number" min="0" value={draft.odometer} disabled={busy} onChange={(event) => onChange({ ...draft, odometer: event.target.value })} className="mt-1 min-h-11 w-full rounded-lg border border-slate-300 px-3 text-base" />
          </label>
          <label className="block text-sm font-medium text-slate-700">
            Inspection notes (optional)
            <textarea value={draft.notes} disabled={busy} onChange={(event) => onChange({ ...draft, notes: event.target.value })} className="mt-1 min-h-20 w-full rounded-lg border border-slate-300 p-3 text-base" />
          </label>
          {children}
          {error ? <p className="text-sm text-red-600" role="alert">{error}</p> : null}
        </div>
        <footer className="flex flex-col-reverse gap-2 border-t bg-white p-4 sm:flex-row sm:justify-end">
          <button type="button" onClick={onClose} disabled={busy} className="min-h-11 rounded-lg border px-4 text-sm font-medium text-slate-700 disabled:opacity-50">Cancel</button>
          <button type="button" onClick={onConfirm} disabled={busy || draft.fuel == null} className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 text-sm font-semibold text-white disabled:opacity-50">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}{busy ? 'Saving...' : confirmLabel || (starting ? 'Confirm Start' : 'Confirm Return')}
          </button>
        </footer>
      </section>
    </div>
  );
}
