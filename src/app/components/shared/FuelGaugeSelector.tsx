import { useId } from 'react';
import { clampFuelLevel, FUEL_LEVEL_MAX_EIGHTHS, getFuelLevelComparison, getFuelLevelDetails } from '../../lib/fuel-gauge';

type FuelGaugeSelectorProps = {
  value: number | null;
  onChange?: (value: number) => void;
  readOnly?: boolean;
  disabled?: boolean;
  required?: boolean;
  label?: string;
  error?: string;
  compact?: boolean;
  showPercentage?: boolean;
  showFraction?: boolean;
  showEstimatedLitres?: boolean;
  tankCapacityLitres?: number | null;
  loading?: boolean;
  compareToValue?: number | null;
};

const toneClasses = {
  red: {
    active: 'border-red-300 bg-red-600 text-white',
    inactive: 'border-red-200 bg-red-50 text-red-700',
  },
  amber: {
    active: 'border-amber-300 bg-amber-500 text-white',
    inactive: 'border-amber-200 bg-amber-50 text-amber-700',
  },
  green: {
    active: 'border-emerald-300 bg-emerald-600 text-white',
    inactive: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  },
} as const;

export function FuelGaugeSelector({
  value,
  onChange,
  readOnly = false,
  disabled = false,
  required = false,
  label,
  error,
  compact = false,
  showPercentage = true,
  showFraction = true,
  showEstimatedLitres = false,
  tankCapacityLitres,
  loading = false,
  compareToValue,
}: FuelGaugeSelectorProps) {
  const fallbackId = useId();
  const details = getFuelLevelDetails(value, tankCapacityLitres);
  const comparison = getFuelLevelComparison(compareToValue, value);
  const isInteractive = !readOnly && !disabled && !loading && typeof onChange === 'function';
  const activeLevel = value == null ? null : clampFuelLevel(value);

  return (
    <div className="space-y-3">
      {label ? (
        <div className="flex items-center justify-between gap-3">
          <label className="text-sm font-medium text-gray-700" htmlFor={fallbackId}>
            {label}
            {required ? ' *' : ''}
          </label>
          {loading ? <span className="text-xs text-gray-500">Loading fuel level...</span> : null}
        </div>
      ) : null}

      <div
        id={fallbackId}
        className={`rounded-xl border ${error ? 'border-red-300' : 'border-gray-200'} bg-white ${compact ? 'p-3' : 'p-4'}`}
      >
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => isInteractive && onChange?.(0)}
            disabled={!isInteractive}
            className={`min-w-10 rounded-lg border px-3 py-2 text-sm font-semibold ${
              activeLevel === 0 ? 'border-slate-300 bg-slate-900 text-white' : 'border-gray-300 bg-gray-50 text-gray-700'
            } ${isInteractive ? 'hover:bg-gray-100' : 'cursor-default'}`}
            aria-pressed={activeLevel === 0}
          >
            E
          </button>
          <div className="grid flex-1 grid-cols-8 gap-2">
            {Array.from({ length: FUEL_LEVEL_MAX_EIGHTHS }, (_, index) => {
              const level = index + 1;
              const barDetails = getFuelLevelDetails(level);
              const tone = barDetails?.colorState ?? 'amber';
              const active = activeLevel != null && level <= activeLevel;
              return (
                <button
                  key={level}
                  type="button"
                  onClick={() => isInteractive && onChange?.(level)}
                  onKeyDown={(event) => {
                    if (!isInteractive) {
                      return;
                    }
                    if (event.key === 'ArrowRight' || event.key === 'ArrowUp') {
                      event.preventDefault();
                      onChange?.(clampFuelLevel((activeLevel ?? 0) + 1));
                    }
                    if (event.key === 'ArrowLeft' || event.key === 'ArrowDown') {
                      event.preventDefault();
                      onChange?.(clampFuelLevel((activeLevel ?? 0) - 1));
                    }
                  }}
                  disabled={!isInteractive}
                  aria-label={`${barDetails?.label || `${level}/8`} (${level}/8)`}
                  aria-pressed={activeLevel === level}
                  className={`${compact ? 'h-10' : 'h-12'} rounded-lg border text-xs font-semibold transition ${
                    active ? toneClasses[tone].active : toneClasses[tone].inactive
                  } ${isInteractive ? 'hover:opacity-90' : 'cursor-default opacity-100'}`}
                >
                  {level}
                </button>
              );
            })}
          </div>
          <div className="min-w-10 rounded-lg border border-gray-300 bg-gray-50 px-3 py-2 text-center text-sm font-semibold text-gray-700">
            F
          </div>
        </div>

        <div className="mt-3 grid gap-2 text-sm text-gray-600 sm:grid-cols-2">
          <div>
            <span className="font-medium text-[#0F172A]">Selected:</span> {details?.label || 'Not selected'}
          </div>
          {showFraction ? (
            <div>
              <span className="font-medium text-[#0F172A]">Level:</span> {details?.fraction || 'Not selected'}
            </div>
          ) : null}
          {showPercentage ? (
            <div>
              <span className="font-medium text-[#0F172A]">Estimated:</span>{' '}
              {details ? `${details.percentage}%` : 'Not selected'}
            </div>
          ) : null}
          {showEstimatedLitres ? (
            <div>
              <span className="font-medium text-[#0F172A]">Litres:</span>{' '}
              {details?.estimatedLitres != null && tankCapacityLitres
                ? `${details.estimatedLitres}L of ${tankCapacityLitres}L (estimate)`
                : 'Tank capacity unavailable'}
            </div>
          ) : null}
        </div>

        {comparison ? (
          <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-700">
            <div>Difference: {comparison.differenceBars > 0 ? '+' : ''}{comparison.differenceBars} bars</div>
            <div>
              Estimated {comparison.directionLabel.toLowerCase()}: {Math.abs(comparison.percentagePointChange)} percentage points
            </div>
          </div>
        ) : null}
      </div>

      {error ? <p className="text-sm text-red-600">{error}</p> : null}
    </div>
  );
}
