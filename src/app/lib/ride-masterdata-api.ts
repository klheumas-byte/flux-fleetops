import { apiRequest } from './api';
import type { CustomerRecord } from './customer-booking-api';

export interface DriverSummary {
  id: string;
  full_name: string;
  role: string;
  status: string;
}

export interface VehicleSummary {
  id: string;
  registration_number: string;
  vehicle_type?: string | null;
  make?: string | null;
  model?: string | null;
}

export interface BookingSummaryOption {
  id: string;
  booking_id: string;
  customer_id: string;
  driver_id?: string | null;
  vehicle_id?: string | null;
  booking_type: string;
  pickup_location: string;
  destination: string;
  pickup_date: string;
  pickup_time: string;
  pickup_at?: string | null;
  status: string;
}

export interface MasterDataItem {
  id: string;
  data_type: string;
  name: string;
  active: boolean;
  archived: boolean;
  admin_editable: boolean;
  description?: string | null;
  sort_order: number;
  created_by?: string | null;
  updated_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface TripRecord {
  id: string;
  trip_id: string;
  ride_id: string;
  customer_id?: string | null;
  driver_id?: string | null;
  vehicle_id?: string | null;
  trip_source_id: string;
  trip_purpose_id: string;
  trip_source: string;
  trip_purpose: string;
  trip_date: string;
  start_time?: string | null;
  end_time?: string | null;
  pickup_area: string;
  destination_area: string;
  odometer_start?: number | null;
  odometer_end?: number | null;
  notes?: string | null;
  status: string;
  created_by: string;
  created_at?: string | null;
  updated_at?: string | null;
  source_booking_id?: string | null;
  counts_toward_company_collections?: boolean;
  counts_toward_utilization?: boolean;
  customer?: CustomerRecord | null;
  driver?: DriverSummary | null;
  vehicle?: VehicleSummary | null;
  source_booking?: BookingSummaryOption | null;
  trip_source_item?: Pick<MasterDataItem, 'id' | 'name' | 'active'> | null;
  trip_purpose_item?: Pick<MasterDataItem, 'id' | 'name' | 'active'> | null;
  ride_source?: string;
  ride_purpose?: string;
  pickup_location?: string;
  destination?: string;
  scheduled_time?: string | null;
  estimated_fare?: number | null;
  actual_fare?: number | null;
  payment_method?: string | null;
}

export interface TripSummary {
  total_trips: number;
  completed_trips: number;
  cancelled_trips: number;
  scheduled_trips: number;
  logged_trips: number;
  trips_today: number;
  trips_this_week: number;
  trips_this_month: number;
  vehicle_active_days: number;
  vehicle_idle_days: number;
  activity_trends: Array<{
    date: string;
    trips: number;
    completed: number;
    vehicles_active: number;
  }>;
  trip_performance: Array<{
    driver: DriverSummary | null;
    trips: number;
    completed_trips: number;
  }>;
  trips_by_platform: Array<{ label: string; count: number }>;
  trips_by_purpose: Array<{ label: string; count: number }>;
  vehicle_utilization: Array<{
    vehicle: VehicleSummary;
    active_days: number;
    idle_days: number;
    trip_count: number;
  }>;
  personal_trip_count: number;
  company_trip_count: number;
  customer_linked_trip_count: number;
  generated_at: string;
}

export type RideRecord = TripRecord;
export type RideSummary = TripSummary;

export interface TripOptions {
  customers: CustomerRecord[];
  drivers: DriverSummary[];
  vehicles: VehicleSummary[];
  bookings: BookingSummaryOption[];
  trip_sources: MasterDataItem[];
  trip_purposes: MasterDataItem[];
  statuses: string[];
}

export interface MasterDataResponse {
  master_data: Record<string, MasterDataItem[]>;
  types: string[];
}

export async function fetchRideOptions() {
  const response = await apiRequest<{ data: TripOptions }>('/rides/options');
  return response.data;
}

export async function fetchRides() {
  const response = await apiRequest<{ data: { rides: TripRecord[] } }>('/rides');
  return response.data.rides;
}

export async function createRide(payload: Record<string, unknown>) {
  const response = await apiRequest<{ data: { ride: TripRecord } }>('/rides', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return response.data.ride;
}

export async function convertBookingToRide(bookingId: string, payload: Record<string, unknown>) {
  const response = await apiRequest<{ data: { ride: TripRecord } }>(`/rides/from-booking/${bookingId}`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return response.data.ride;
}

export async function updateRide(rideId: string, payload: Record<string, unknown>) {
  const response = await apiRequest<{ data: { ride: TripRecord } }>(`/rides/${rideId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  return response.data.ride;
}

export async function fetchRideSummary() {
  const response = await apiRequest<{ data: { summary: TripSummary } }>('/rides/summary');
  return response.data.summary;
}

export async function fetchMasterData(activeOnly = false) {
  const query = activeOnly ? '?active_only=true' : '';
  const response = await apiRequest<{ data: MasterDataResponse }>(`/master-data${query}`);
  return response.data;
}

export async function createMasterDataItem(payload: Record<string, unknown>) {
  const response = await apiRequest<{ data: { item: MasterDataItem } }>('/master-data', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  return response.data.item;
}

export async function updateMasterDataItem(itemId: string, payload: Record<string, unknown>) {
  const response = await apiRequest<{ data: { item: MasterDataItem } }>(`/master-data/${itemId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  });
  return response.data.item;
}
