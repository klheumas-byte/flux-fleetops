export const FUEL_LEVEL_MAX_EIGHTHS = 8;

export type FuelGaugeColorState = 'red' | 'amber' | 'green';

export interface FuelLevelDetails {
  eighths: number;
  fraction: string;
  percentage: number;
  label: string;
  colorState: FuelGaugeColorState;
  estimatedLitres: number | null;
}

const TEXT_MAPPINGS = new Map<string, number>([
  ['e', 0],
  ['empty', 0],
  ['none', 0],
  ['low', 1],
  ['very low', 1],
  ['quarter', 2],
  ['1/4', 2],
  ['half', 4],
  ['half tank', 4],
  ['1/2', 4],
  ['three quarters', 6],
  ['3/4', 6],
  ['full', 8],
  ['full tank', 8],
  ['f', 8],
]);

export function normalizeFuelLevelEighths(value: unknown): number | null {
  if (value === null || value === undefined || value === '') {
    return null;
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    if (value >= 0 && value <= 1) {
      return clampFuelLevel(Math.round(value * FUEL_LEVEL_MAX_EIGHTHS));
    }
    if (value >= 0 && value <= FUEL_LEVEL_MAX_EIGHTHS) {
      return clampFuelLevel(Math.round(value));
    }
    if (value >= 0 && value <= 100) {
      return clampFuelLevel(Math.round((value / 100) * FUEL_LEVEL_MAX_EIGHTHS));
    }
    return null;
  }
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase();
    if (!normalized) {
      return null;
    }
    if (TEXT_MAPPINGS.has(normalized)) {
      return TEXT_MAPPINGS.get(normalized) ?? null;
    }
    if (normalized.endsWith('%')) {
      return normalizeFuelLevelEighths(Number(normalized.slice(0, -1)));
    }
    if (normalized.includes('/')) {
      const [left, right] = normalized.split('/');
      const numerator = Number(left);
      const denominator = Number(right);
      if (Number.isFinite(numerator) && Number.isFinite(denominator) && denominator > 0) {
        return normalizeFuelLevelEighths((numerator / denominator) * FUEL_LEVEL_MAX_EIGHTHS);
      }
    }
    const parsed = Number(normalized);
    if (Number.isFinite(parsed)) {
      return normalizeFuelLevelEighths(parsed);
    }
  }
  return null;
}

export function clampFuelLevel(value: number) {
  return Math.min(FUEL_LEVEL_MAX_EIGHTHS, Math.max(0, value));
}

export function getFuelLevelDetails(value: number | null | undefined, tankCapacityLitres?: number | null): FuelLevelDetails | null {
  if (value === null || value === undefined) {
    return null;
  }
  const eighths = clampFuelLevel(value);
  const estimatedLitres =
    typeof tankCapacityLitres === 'number' && Number.isFinite(tankCapacityLitres) && tankCapacityLitres > 0
      ? Number(((eighths / FUEL_LEVEL_MAX_EIGHTHS) * tankCapacityLitres).toFixed(2))
      : null;
  return {
    eighths,
    fraction: `${eighths}/${FUEL_LEVEL_MAX_EIGHTHS}`,
    percentage: Number(((eighths / FUEL_LEVEL_MAX_EIGHTHS) * 100).toFixed(1)),
    label:
      {
        0: 'Empty',
        1: 'Very Low',
        2: 'Low',
        3: 'Below Half',
        4: 'Half Tank',
        5: 'Above Half',
        6: 'Three Quarters',
        7: 'Nearly Full',
        8: 'Full Tank',
      }[eighths] ?? `${eighths}/8`,
    colorState: eighths <= 2 ? 'red' : eighths <= 5 ? 'amber' : 'green',
    estimatedLitres,
  };
}

export function getFuelLevelComparison(opening: number | null | undefined, closing: number | null | undefined) {
  if (opening == null || closing == null) {
    return null;
  }
  const differenceBars = closing - opening;
  const percentagePointChange = (differenceBars / FUEL_LEVEL_MAX_EIGHTHS) * 100;
  return {
    differenceBars,
    percentagePointChange,
    directionLabel: differenceBars === 0 ? 'No change' : differenceBars > 0 ? 'Increase' : 'Decrease',
  };
}
