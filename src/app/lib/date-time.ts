const ISO_DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;
const ISO_DATE_TIME_PREFIX_PATTERN = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})/;
const TIME_PATTERN = /^(\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?$/;

function isCalendarDate(value: string) {
  const match = ISO_DATE_PATTERN.exec(value);
  if (!match) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return parsed.getUTCFullYear() === year && parsed.getUTCMonth() === month - 1 && parsed.getUTCDate() === day;
}

export function isTimeValue(value: unknown): value is string {
  if (typeof value !== 'string') return false;
  const match = TIME_PATTERN.exec(value.trim());
  return Boolean(match && Number(match[1]) <= 23 && Number(match[2]) <= 59);
}

export function parseDateTime(value: unknown): Date | null {
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : new Date(value.getTime());
  if (typeof value !== 'string' || !value.trim()) return null;
  const parsed = new Date(value.trim());
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function formatDateTimeSafe(value: unknown, fallback = 'Date unavailable') {
  const parsed = parseDateTime(value);
  return parsed ? parsed.toLocaleString() : fallback;
}

export function toDateInputValue(value: unknown) {
  if (typeof value !== 'string' || !value.trim()) return '';
  const candidate = value.trim();
  const datePart = ISO_DATE_TIME_PREFIX_PATTERN.exec(candidate)?.[1] || candidate;
  return isCalendarDate(datePart) ? datePart : '';
}

export function toTimeInputValue(value: unknown) {
  if (typeof value !== 'string' || !value.trim()) return '';
  const candidate = value.trim();
  if (isTimeValue(candidate)) return candidate.slice(0, 5);
  const match = ISO_DATE_TIME_PREFIX_PATTERN.exec(candidate);
  const timePart = match ? `${match[2]}:${match[3]}` : '';
  return isTimeValue(timePart) ? timePart : '';
}

export function toDateTimeLocalInputValue(value: unknown) {
  const parsed = parseDateTime(value);
  if (!parsed) return '';
  const local = new Date(parsed.getTime() - parsed.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

export function toIsoDateTime(value: unknown) {
  const parsed = parseDateTime(value);
  return parsed ? parsed.toISOString() : null;
}

export function combineLocalDateAndTime(dateValue: unknown, timeValue: unknown) {
  const date = toDateInputValue(dateValue);
  const time = toTimeInputValue(timeValue);
  if (!date || !time) return null;
  return toIsoDateTime(`${date}T${time}:00`);
}
