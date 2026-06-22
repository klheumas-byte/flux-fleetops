import { useEffect, useMemo, useState } from 'react';
import { Landmark, Loader2, ShieldCheck, Wallet } from 'lucide-react';
import { apiRequest, ApiRequestError } from '../../lib/api';

interface AdminUser {
  id: string;
  full_name: string;
  role: 'owner' | 'admin' | 'driver';
  phone: string;
}

interface AccountabilityRecord {
  admin: AdminUser;
  total_collected: number;
  total_approved: number;
  current_holding_balance: number;
}

interface AccountabilityResponse {
  success: boolean;
  data: {
    admins: AccountabilityRecord[];
  };
}

interface WeeklyOverview {
  total_expected: number;
  total_approved: number;
  total_outstanding: number;
  arrears: number;
  drivers_below_target: Array<{
    driver: AdminUser | null;
    assignment_id: string;
    cycle: {
      weekly_target: number;
      approved_total: number;
      outstanding_balance: number;
      status: string;
      payment_deadline: string;
    };
  }>;
}

interface FinanceReportResponse {
  success: boolean;
  data: {
    weekly_payment_overview: WeeklyOverview;
  };
}

function getSettledData<T>(result: PromiseSettledResult<T>) {
  return result.status === 'fulfilled' ? result.value : null;
}

function getSettledError(result: PromiseSettledResult<unknown>) {
  if (result.status !== 'rejected') {
    return null;
  }
  return result.reason instanceof ApiRequestError
    ? result.reason.message
    : 'Unable to load admin accountability right now.';
}

function formatCurrency(value: number) {
  return `GHS ${value.toLocaleString()}`;
}

export default function AdminAccountability() {
  const [records, setRecords] = useState<AccountabilityRecord[]>([]);
  const [weeklyOverview, setWeeklyOverview] = useState<WeeklyOverview | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [pageError, setPageError] = useState('');
  const [pageNotice, setPageNotice] = useState('');

  const storedUser = localStorage.getItem('flux_user');
  const currentRole = storedUser ? JSON.parse(storedUser).role : null;

  const loadRecords = async () => {
      setIsLoading(true);
      setPageError('');
      setPageNotice('');
      try {
        const accountabilityResponse = await apiRequest<AccountabilityResponse>('/admins/accountability', {
          cacheTtlMs: 10000,
          timeoutMs: 15000,
        });

        setRecords(Array.isArray(accountabilityResponse?.data?.admins) ? accountabilityResponse.data.admins : []);
        setIsLoading(false);

        const financeResult = await Promise.allSettled([
          apiRequest<FinanceReportResponse>('/reports/finance', { cacheTtlMs: 10000, timeoutMs: 15000 }),
        ]);
        const financeResponse = getSettledData(financeResult[0]);
        setWeeklyOverview(financeResponse?.data?.weekly_payment_overview || null);

        const financeError = getSettledError(financeResult[0]);
        if (financeError) {
          setPageNotice('Weekly finance overview is temporarily unavailable.');
        }
      } catch (error) {
        if (error instanceof ApiRequestError) {
          setPageError(error.message);
        } else {
          setPageError('Unable to load admin accountability right now.');
        }
      } finally {
        setIsLoading(false);
      }
    };

  useEffect(() => {
    if (currentRole === 'driver') {
      setIsLoading(false);
      return;
    }
    void loadRecords();
  }, [currentRole]);

  const totals = useMemo(() => {
    return records.reduce(
      (summary, record) => ({
        totalCollected: summary.totalCollected + record.total_collected,
        totalApproved: summary.totalApproved + record.total_approved,
        totalHolding: summary.totalHolding + record.current_holding_balance,
      }),
      { totalCollected: 0, totalApproved: 0, totalHolding: 0 },
    );
  }, [records]);

  if (currentRole === 'driver') {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Drivers do not have access to Admin Accountability.
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-[#0F172A]">Admin Accountability</h1>
        <p className="mt-1 text-gray-600">Track who collected funds, approved collections, and still holds cash</p>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-blue-100">
            <Landmark className="h-5 w-5 text-blue-600" />
          </div>
          <div className="text-2xl font-semibold text-[#0F172A]">{formatCurrency(totals.totalCollected)}</div>
          <div className="text-sm text-gray-600">Total Collected</div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-green-100">
            <ShieldCheck className="h-5 w-5 text-green-600" />
          </div>
          <div className="text-2xl font-semibold text-[#0F172A]">{formatCurrency(totals.totalApproved)}</div>
          <div className="text-sm text-gray-600">Total Approved</div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-amber-100">
            <Wallet className="h-5 w-5 text-amber-600" />
          </div>
          <div className="text-2xl font-semibold text-[#0F172A]">{formatCurrency(totals.totalHolding)}</div>
          <div className="text-sm text-gray-600">Current Holding Balance</div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-4">
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="text-2xl font-semibold text-[#0F172A]">{formatCurrency(weeklyOverview?.total_expected || 0)}</div>
          <div className="text-sm text-gray-600">Total Expected</div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="text-2xl font-semibold text-green-700">{formatCurrency(weeklyOverview?.total_approved || 0)}</div>
          <div className="text-sm text-gray-600">Total Approved / Collected</div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="text-2xl font-semibold text-red-700">{formatCurrency(weeklyOverview?.total_outstanding || 0)}</div>
          <div className="text-sm text-gray-600">Total Outstanding</div>
        </div>
        <div className="rounded-xl border border-gray-200 bg-white p-5">
          <div className="text-2xl font-semibold text-amber-700">{formatCurrency(weeklyOverview?.arrears || 0)}</div>
          <div className="text-sm text-gray-600">Arrears</div>
        </div>
      </div>

      {pageError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <span>{pageError}</span>
            <button
              onClick={() => void loadRecords()}
              className="rounded-lg border border-red-200 bg-white px-3 py-2 text-xs font-medium text-red-700 hover:bg-red-100"
            >
              Retry
            </button>
          </div>
        </div>
      )}

      {pageNotice && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          {pageNotice}
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        {isLoading ? (
          <div className="flex items-center justify-center gap-3 px-6 py-16 text-gray-500">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span>Loading accountability records...</span>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="border-b border-gray-200 bg-gray-50">
                <tr>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Admin</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Role</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Total Collected</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Total Approved</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Holding Balance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {records.map((record) => (
                  <tr key={record.admin.id} className="transition-colors hover:bg-gray-50">
                    <td className="px-6 py-4">
                      <div className="font-medium text-[#0F172A]">{record.admin.full_name}</div>
                      <div className="text-xs text-gray-500">{record.admin.phone}</div>
                    </td>
                    <td className="px-6 py-4 capitalize text-gray-700">{record.admin.role}</td>
                    <td className="px-6 py-4 font-semibold text-[#0F172A]">
                      {formatCurrency(record.total_collected)}
                    </td>
                    <td className="px-6 py-4 font-semibold text-green-700">
                      {formatCurrency(record.total_approved)}
                    </td>
                    <td className="px-6 py-4 font-semibold text-amber-700">
                      {formatCurrency(record.current_holding_balance)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {records.length === 0 && (
              <div className="px-6 py-12 text-center text-gray-500">No admin accountability records found.</div>
            )}
          </div>
        )}
      </div>

      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-[#0F172A]">Drivers Below Target</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="border-b border-gray-200 bg-gray-50">
              <tr>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Driver</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Target</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Approved</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Outstanding</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Deadline</th>
                <th className="px-6 py-4 text-left text-xs font-semibold uppercase tracking-wider text-gray-700">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {(weeklyOverview?.drivers_below_target || []).map((record) => (
                <tr key={`${record.driver?.id || 'driver'}-${record.assignment_id}`} className="transition-colors hover:bg-gray-50">
                  <td className="px-6 py-4">
                    <div className="font-medium text-[#0F172A]">{record.driver?.full_name || 'Unknown Driver'}</div>
                    <div className="text-xs text-gray-500">{record.driver?.phone || record.assignment_id}</div>
                  </td>
                  <td className="px-6 py-4 text-gray-700">{formatCurrency(record.cycle.weekly_target)}</td>
                  <td className="px-6 py-4 text-green-700">{formatCurrency(record.cycle.approved_total)}</td>
                  <td className="px-6 py-4 text-red-700">{formatCurrency(record.cycle.outstanding_balance)}</td>
                  <td className="px-6 py-4 text-gray-700">{record.cycle.payment_deadline}</td>
                  <td className="px-6 py-4 capitalize text-gray-700">{record.cycle.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {(weeklyOverview?.drivers_below_target || []).length === 0 && (
            <div className="px-6 py-12 text-center text-gray-500">No drivers are below target right now.</div>
          )}
        </div>
      </div>
    </div>
  );
}
