import { useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  Bell,
  Building2,
  CheckCircle,
  Database,
  DollarSign,
  Loader2,
  Pencil,
  Plus,
  RotateCcw,
  Save,
  Settings as SettingsIcon,
  Shield,
  Truck,
} from 'lucide-react';

import { ApiRequestError } from '../../lib/api';
import { getStoredSessionUser } from '../../lib/auth-session';
import {
  createMasterDataItem,
  fetchMasterData,
  updateMasterDataItem,
  type MasterDataItem,
  type MasterDataResponse,
} from '../../lib/ride-masterdata-api';
import {
  fetchSystemSettings,
  updateSystemSettings,
  type SystemSettingsRecord,
} from '../../lib/system-settings-api';

type SettingsTab =
  | 'master-data'
  | 'company'
  | 'fleet'
  | 'role-permissions'
  | 'revenue'
  | 'notifications'
  | 'security';

interface MasterDataFormState {
  data_type: string;
  name: string;
  description: string;
  active: boolean;
  admin_editable: boolean;
}

const initialFormState: MasterDataFormState = {
  data_type: 'customer_categories',
  name: '',
  description: '',
  active: true,
  admin_editable: true,
};

const tabConfig: Array<{
  id: SettingsTab;
  label: string;
  icon: typeof Database;
}> = [
  { id: 'master-data', label: 'Master Data', icon: Database },
  { id: 'company', label: 'Company', icon: Building2 },
  { id: 'fleet', label: 'Fleet', icon: Truck },
  { id: 'role-permissions', label: 'Role Permissions', icon: Shield },
  { id: 'revenue', label: 'Revenue', icon: DollarSign },
  { id: 'notifications', label: 'Notifications', icon: Bell },
  { id: 'security', label: 'Security', icon: Shield },
];

const typeLabels: Record<string, string> = {
  customer_categories: 'Customer Categories',
  relationship_categories: 'Relationship Categories',
  opportunity_levels: 'Opportunity Levels',
  network_values: 'Network Values',
  ride_types: 'Ride Types',
  ride_sources: 'Trip Sources',
  booking_types: 'Booking Types',
  customer_sources: 'Customer Sources',
  organization_types: 'Organization Types',
  industries: 'Industries',
  lead_statuses: 'Lead Statuses',
  potential_services: 'Potential Services',
  payment_methods: 'Payment Methods',
  ride_purposes: 'Trip Purposes',
};

function EmptyState({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="rounded-2xl border border-dashed border-gray-300 bg-gray-50 px-6 py-10 text-center">
      <div className="text-base font-semibold text-[#0F172A]">{title}</div>
      <p className="mt-2 text-sm text-gray-500">{description}</p>
    </div>
  );
}

function formatTypeLabel(value: string) {
  return typeLabels[value] || value.replaceAll('_', ' ');
}

export default function Settings() {
  const sessionUser = getStoredSessionUser();
  const currentRole = sessionUser?.role || 'admin';
  const canEditMasterData = currentRole === 'owner' || currentRole === 'admin';
  const isOwner = currentRole === 'owner';

  const [activeTab, setActiveTab] = useState<SettingsTab>('master-data');
  const [showSaveSuccess, setShowSaveSuccess] = useState(false);
  const [pageError, setPageError] = useState('');
  const [isLoadingMasterData, setIsLoadingMasterData] = useState(true);
  const [isSavingMasterData, setIsSavingMasterData] = useState(false);
  const [masterDataResponse, setMasterDataResponse] = useState<MasterDataResponse | null>(null);
  const [systemSettings, setSystemSettings] = useState<SystemSettingsRecord | null>(null);
  const [selectedType, setSelectedType] = useState('customer_categories');
  const [editingItemId, setEditingItemId] = useState<string | null>(null);
  const [masterDataForm, setMasterDataForm] = useState<MasterDataFormState>(initialFormState);
  const [isLoadingSystemSettings, setIsLoadingSystemSettings] = useState(true);
  const [isSavingSystemSettings, setIsSavingSystemSettings] = useState(false);
  const [systemSettingsForm, setSystemSettingsForm] = useState({
    default_currency: 'GHS',
    currency_symbol: 'GHS',
    distance_unit: 'KM',
    include_fuel_in_profitability: false,
    role_permissions: {
      admin: {
        view_vehicle_investment: false,
        view_vehicle_recovery: false,
        view_profitability: false,
        view_investor_information: false,
        view_reports: false,
        export_financial_reports: false,
        manage_vehicle_cost_items: false,
      },
    },
  });

  const [defaultWeeklyTarget, setDefaultWeeklyTarget] = useState('2500');
  const [defaultDeposit, setDefaultDeposit] = useState('5000');
  const [commissionRate, setCommissionRate] = useState('20');
  const [baseFare, setBaseFare] = useState('10');
  const [emailNotifications, setEmailNotifications] = useState(true);
  const [smsNotifications, setSmsNotifications] = useState(true);

  const loadMasterData = async () => {
    setIsLoadingMasterData(true);
    setPageError('');
    try {
      const response = await fetchMasterData();
      setMasterDataResponse(response);
      setSelectedType((current) =>
        response.types.includes(current) ? current : response.types[0] || 'customer_categories',
      );
      setMasterDataForm((current) => ({
        ...current,
        data_type:
          response.types.includes(current.data_type)
            ? current.data_type
            : response.types[0] || 'customer_categories',
      }));
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setPageError(error.message);
      } else {
        setPageError('Unable to load master data right now.');
      }
    } finally {
      setIsLoadingMasterData(false);
    }
  };

  useEffect(() => {
    void loadMasterData();
  }, []);

  useEffect(() => {
    const loadSystemSettings = async () => {
      setIsLoadingSystemSettings(true);
      try {
        const response = await fetchSystemSettings();
        setSystemSettings(response);
        setSystemSettingsForm({
          default_currency: response.default_currency,
          currency_symbol: response.currency_symbol,
          distance_unit: response.distance_unit,
          include_fuel_in_profitability: response.include_fuel_in_profitability,
          role_permissions: response.role_permissions,
        });
      } catch (error) {
        if (error instanceof ApiRequestError) {
          setPageError(error.message);
        } else {
          setPageError('Unable to load system settings right now.');
        }
      } finally {
        setIsLoadingSystemSettings(false);
      }
    };

    void loadSystemSettings();
  }, []);

  const types = masterDataResponse?.types || Object.keys(typeLabels);
  const selectedItems = useMemo(
    () => masterDataResponse?.master_data?.[selectedType] || [],
    [masterDataResponse, selectedType],
  );

  const totals = useMemo(() => {
    const allItems = Object.values(masterDataResponse?.master_data || {}).flat();
    return {
      total: allItems.length,
      active: allItems.filter((item) => item.active).length,
      inactive: allItems.filter((item) => !item.active).length,
      restricted: allItems.filter((item) => !item.admin_editable).length,
    };
  }, [masterDataResponse]);

  const handleSaveSettings = () => {
    setShowSaveSuccess(true);
    setTimeout(() => setShowSaveSuccess(false), 3000);
  };

  const handleResetMasterDataForm = () => {
    setEditingItemId(null);
    setMasterDataForm({
      ...initialFormState,
      data_type: selectedType,
    });
  };

  const handleEditItem = (item: MasterDataItem) => {
    setEditingItemId(item.id);
    setMasterDataForm({
      data_type: item.data_type,
      name: item.name,
      description: item.description || '',
      active: item.active,
      admin_editable: item.admin_editable,
    });
    setSelectedType(item.data_type);
  };

  const handleSubmitMasterData = async () => {
    if (!canEditMasterData) {
      return;
    }

    setIsSavingMasterData(true);
    setPageError('');
    try {
      const payload: Record<string, unknown> = {
        data_type: masterDataForm.data_type,
        name: masterDataForm.name,
        description: masterDataForm.description || undefined,
        active: masterDataForm.active,
      };
      if (isOwner) {
        payload.admin_editable = masterDataForm.admin_editable;
      }

      if (editingItemId) {
        await updateMasterDataItem(editingItemId, payload);
      } else {
        await createMasterDataItem(payload);
      }

      handleResetMasterDataForm();
      await loadMasterData();
      handleSaveSettings();
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setPageError(error.message);
      } else {
        setPageError('Unable to save that master data item right now.');
      }
    } finally {
      setIsSavingMasterData(false);
    }
  };

  const handleToggleItem = async (item: MasterDataItem) => {
    setIsSavingMasterData(true);
    setPageError('');
    try {
      const payload: Record<string, unknown> = { active: !item.active };
      if (isOwner) {
        payload.admin_editable = item.admin_editable;
      }
      await updateMasterDataItem(item.id, payload);
      await loadMasterData();
      handleSaveSettings();
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setPageError(error.message);
      } else {
        setPageError('Unable to update that master data item right now.');
      }
    } finally {
      setIsSavingMasterData(false);
    }
  };

  const handleSaveSystemSettings = async () => {
    if (!isOwner) {
      return;
    }

    setIsSavingSystemSettings(true);
    setPageError('');
    try {
      const nextSettings = await updateSystemSettings(systemSettingsForm);
      setSystemSettings(nextSettings);
      setSystemSettingsForm({
        default_currency: nextSettings.default_currency,
        currency_symbol: nextSettings.currency_symbol,
        distance_unit: nextSettings.distance_unit,
        include_fuel_in_profitability: nextSettings.include_fuel_in_profitability,
        role_permissions: nextSettings.role_permissions,
      });
      handleSaveSettings();
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setPageError(error.message);
      } else {
        setPageError('Unable to save system settings right now.');
      }
    } finally {
      setIsSavingSystemSettings(false);
    }
  };

  return (
    <div className="space-y-6 p-4 md:p-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="flex items-center gap-3 text-2xl font-semibold text-[#0F172A]">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-purple-100">
              <SettingsIcon className="h-6 w-6 text-purple-600" />
            </div>
            System Settings
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Manage reusable platform options and core operating defaults.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={handleResetMasterDataForm}
            className="inline-flex items-center gap-2 rounded-xl border border-gray-300 bg-white px-4 py-2.5 text-sm font-medium text-[#0F172A] hover:bg-gray-50"
          >
            <RotateCcw className="h-4 w-4" />
            Reset Form
          </button>
          <button
            onClick={handleSaveSettings}
            className="inline-flex items-center gap-2 rounded-xl bg-[#2563EB] px-4 py-2.5 text-sm font-medium text-white hover:bg-[#1d4ed8]"
          >
            <Save className="h-4 w-4" />
            Save Changes
          </button>
        </div>
      </div>

      {showSaveSuccess && (
        <div className="flex items-center gap-3 rounded-xl border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">
          <CheckCircle className="h-5 w-5 text-green-600" />
          Settings saved successfully.
        </div>
      )}

      {pageError && (
        <div className="flex items-center gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertCircle className="h-5 w-5 text-red-600" />
          {pageError}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        {[
          { label: 'Master Data Items', value: totals.total, tint: 'bg-blue-100 text-blue-700' },
          { label: 'Active Options', value: totals.active, tint: 'bg-emerald-100 text-emerald-700' },
          { label: 'Inactive Options', value: totals.inactive, tint: 'bg-amber-100 text-amber-700' },
          { label: 'Owner Locked', value: totals.restricted, tint: 'bg-purple-100 text-purple-700' },
        ].map((card) => (
          <div key={card.label} className="rounded-2xl border border-gray-200 bg-white p-5">
            <div className={`mb-4 flex h-12 w-12 items-center justify-center rounded-xl ${card.tint}`}>
              <Database className="h-5 w-5" />
            </div>
            <div className="text-3xl font-semibold text-[#0F172A]">{card.value}</div>
            <div className="mt-1 text-sm text-gray-500">{card.label}</div>
          </div>
        ))}
      </div>

      <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white">
        <div className="overflow-x-auto border-b border-gray-200">
          <div className="flex">
            {tabConfig.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex items-center gap-2 whitespace-nowrap border-b-2 px-5 py-4 text-sm font-medium ${
                    isActive
                      ? 'border-[#2563EB] bg-blue-50 text-[#2563EB]'
                      : 'border-transparent text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                  }`}
                >
                  <Icon className="h-4 w-4" />
                  {tab.label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="p-4 md:p-6">
          {activeTab === 'master-data' && (
            <div className="space-y-6">
              <div className="rounded-2xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-900">
                Dropdown values now come from live master data instead of hardcoded lists. Drivers only see active
                approved options, while historical records keep any older values already used.
              </div>

              <div className="grid grid-cols-1 gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
                <div className="space-y-4">
                  <div className="rounded-2xl border border-gray-200 bg-white p-4">
                    <div className="mb-3 text-sm font-semibold text-[#0F172A]">Data Types</div>
                    <div className="space-y-2">
                      {types.map((type) => {
                        const isActive = selectedType === type;
                        const count = masterDataResponse?.master_data?.[type]?.length || 0;
                        return (
                          <button
                            key={type}
                            onClick={() => {
                              setSelectedType(type);
                              setMasterDataForm((current) => ({ ...current, data_type: type }));
                            }}
                            className={`flex w-full items-center justify-between rounded-xl px-4 py-3 text-left text-sm ${
                              isActive ? 'bg-blue-50 text-[#2563EB]' : 'bg-gray-50 text-gray-700 hover:bg-gray-100'
                            }`}
                          >
                            <span>{formatTypeLabel(type)}</span>
                            <span className="rounded-full bg-white px-2 py-0.5 text-xs text-gray-500">{count}</span>
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  <div className="rounded-2xl border border-gray-200 bg-white p-4">
                    <div className="mb-3 flex items-center justify-between">
                      <div>
                        <div className="text-sm font-semibold text-[#0F172A]">
                          {editingItemId ? 'Edit Value' : 'Create Value'}
                        </div>
                        <p className="mt-1 text-xs text-gray-500">
                          Duplicate names are blocked case-insensitively.
                        </p>
                      </div>
                      <button
                        onClick={handleResetMasterDataForm}
                        className="rounded-lg border border-gray-300 px-3 py-2 text-xs font-medium text-gray-600 hover:bg-gray-50"
                      >
                        Clear
                      </button>
                    </div>

                    <div className="space-y-3">
                      <label className="block space-y-2">
                        <span className="text-sm font-medium text-[#0F172A]">Data Type</span>
                        <select
                          value={masterDataForm.data_type}
                          onChange={(event) =>
                            setMasterDataForm((current) => ({ ...current, data_type: event.target.value }))
                          }
                          className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm focus:border-[#2563EB] focus:outline-none"
                        >
                          {types.map((type) => (
                            <option key={type} value={type}>
                              {formatTypeLabel(type)}
                            </option>
                          ))}
                        </select>
                      </label>

                      <label className="block space-y-2">
                        <span className="text-sm font-medium text-[#0F172A]">Name</span>
                        <input
                          value={masterDataForm.name}
                          onChange={(event) =>
                            setMasterDataForm((current) => ({ ...current, name: event.target.value }))
                          }
                          placeholder="Enter dropdown value"
                          className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm focus:border-[#2563EB] focus:outline-none"
                        />
                      </label>

                      <label className="block space-y-2">
                        <span className="text-sm font-medium text-[#0F172A]">Description</span>
                        <textarea
                          rows={3}
                          value={masterDataForm.description}
                          onChange={(event) =>
                            setMasterDataForm((current) => ({ ...current, description: event.target.value }))
                          }
                          placeholder="Optional note for admins and owners"
                          className="w-full rounded-xl border border-gray-300 px-4 py-3 text-sm focus:border-[#2563EB] focus:outline-none"
                        />
                      </label>

                      <label className="flex items-center justify-between rounded-xl border border-gray-200 px-4 py-3">
                        <div>
                          <div className="text-sm font-medium text-[#0F172A]">Active</div>
                          <div className="text-xs text-gray-500">Inactive values stay on historical records only.</div>
                        </div>
                        <input
                          type="checkbox"
                          checked={masterDataForm.active}
                          onChange={(event) =>
                            setMasterDataForm((current) => ({ ...current, active: event.target.checked }))
                          }
                          className="h-4 w-4 rounded border-gray-300 text-[#2563EB] focus:ring-[#2563EB]"
                        />
                      </label>

                      {isOwner && (
                        <label className="flex items-center justify-between rounded-xl border border-gray-200 px-4 py-3">
                          <div>
                            <div className="text-sm font-medium text-[#0F172A]">Admin Editable</div>
                            <div className="text-xs text-gray-500">
                              Turn this off to reserve edits for the owner only.
                            </div>
                          </div>
                          <input
                            type="checkbox"
                            checked={masterDataForm.admin_editable}
                            onChange={(event) =>
                              setMasterDataForm((current) => ({
                                ...current,
                                admin_editable: event.target.checked,
                              }))
                            }
                            className="h-4 w-4 rounded border-gray-300 text-[#2563EB] focus:ring-[#2563EB]"
                          />
                        </label>
                      )}

                      <button
                        onClick={() => void handleSubmitMasterData()}
                        disabled={isSavingMasterData || !canEditMasterData}
                        className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-[#2563EB] px-4 py-2.5 text-sm font-medium text-white hover:bg-[#1d4ed8] disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {isSavingMasterData ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                        {editingItemId ? 'Update Value' : 'Create Value'}
                      </button>
                    </div>
                  </div>
                </div>

                <div className="space-y-4">
                  <div className="rounded-2xl border border-gray-200 bg-white">
                    <div className="flex flex-col gap-3 border-b border-gray-200 px-5 py-4 md:flex-row md:items-center md:justify-between">
                      <div>
                        <h2 className="text-lg font-semibold text-[#0F172A]">{formatTypeLabel(selectedType)}</h2>
                        <p className="mt-1 text-sm text-gray-500">
                          Manage reusable values for forms, bookings, rides, and CRM workflows.
                        </p>
                      </div>
                      <div className="rounded-full bg-slate-100 px-3 py-1 text-xs font-medium text-slate-700">
                        {selectedItems.length} values
                      </div>
                    </div>

                    <div className="divide-y divide-gray-100">
                      {isLoadingMasterData ? (
                        <div className="flex items-center justify-center gap-3 px-6 py-12 text-sm text-gray-500">
                          <Loader2 className="h-4 w-4 animate-spin" />
                          Loading master data...
                        </div>
                      ) : selectedItems.length ? (
                        selectedItems.map((item) => {
                          const lockedForAdmin = currentRole === 'admin' && !item.admin_editable;
                          return (
                            <div key={item.id} className="flex flex-col gap-4 px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
                              <div className="min-w-0">
                                <div className="flex flex-wrap items-center gap-2">
                                <div className="text-sm font-semibold text-[#0F172A]">{item.name}</div>
                                  <span
                                    className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                                      item.archived
                                        ? 'bg-slate-200 text-slate-700'
                                        : item.active
                                        ? 'bg-emerald-100 text-emerald-700'
                                        : 'bg-gray-100 text-gray-600'
                                    }`}
                                  >
                                    {item.archived ? 'Archived' : item.active ? 'Active' : 'Inactive'}
                                  </span>
                                  <span
                                    className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                                      item.active
                                        ? 'bg-blue-100 text-blue-700'
                                        : 'bg-amber-100 text-amber-700'
                                    }`}
                                  >
                                    {item.active ? 'Available in Forms' : 'Hidden from New Forms'}
                                  </span>
                                  <span
                                    className={`rounded-full px-2.5 py-1 text-xs font-medium ${
                                      item.admin_editable
                                        ? 'bg-blue-100 text-blue-700'
                                        : 'bg-purple-100 text-purple-700'
                                    }`}
                                  >
                                    {item.admin_editable ? 'Admin Editable' : 'Owner Only'}
                                  </span>
                                </div>
                                <div className="mt-1 text-sm text-gray-500">
                                  {item.description || 'No description provided.'}
                                </div>
                              </div>

                              <div className="flex flex-wrap items-center gap-2">
                                <button
                                  onClick={() => handleEditItem(item)}
                                  disabled={lockedForAdmin}
                                  className="inline-flex items-center gap-2 rounded-lg border border-gray-300 px-3 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                                >
                                  <Pencil className="h-3.5 w-3.5" />
                                  Edit
                                </button>
                                <button
                                  onClick={() => void handleToggleItem(item)}
                                  disabled={lockedForAdmin || isSavingMasterData}
                                  className="rounded-lg bg-[#0F172A] px-3 py-2 text-xs font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
                                >
                                  {item.active ? 'Deactivate' : 'Activate'}
                                </button>
                                <button
                                  onClick={() => void updateMasterDataItem(item.id, { archived: !item.archived }).then(loadMasterData).then(handleSaveSettings).catch((error) => {
                                    if (error instanceof ApiRequestError) {
                                      setPageError(error.message);
                                    } else {
                                      setPageError('Unable to archive that master data item right now.');
                                    }
                                  })}
                                  disabled={lockedForAdmin || isSavingMasterData}
                                  className="rounded-lg border border-gray-300 px-3 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
                                >
                                  {item.archived ? 'Unarchive' : 'Archive'}
                                </button>
                              </div>
                            </div>
                          );
                        })
                      ) : (
                        <div className="px-5 py-8">
                          <EmptyState
                            title="No values yet"
                            description="Create the first approved value for this master data type."
                          />
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {activeTab === 'company' && (
            <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
              <div className="rounded-2xl border border-gray-200 bg-white p-5">
                <h2 className="text-lg font-semibold text-[#0F172A]">System Controls</h2>
                <div className="mt-4 space-y-4">
                  {isLoadingSystemSettings ? (
                    <div className="flex items-center gap-3 rounded-xl border border-gray-200 px-4 py-4 text-sm text-gray-500">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Loading currency and unit settings...
                    </div>
                  ) : (
                    <>
                      <label className="block space-y-2">
                        <span className="text-sm font-medium text-[#0F172A]">Default Currency</span>
                        <select
                          value={systemSettingsForm.default_currency}
                          onChange={(event) =>
                            setSystemSettingsForm((current) => ({
                              ...current,
                              default_currency: event.target.value,
                            }))
                          }
                          disabled={!isOwner}
                          className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm disabled:bg-gray-50"
                        >
                          {(systemSettings?.supported_currencies || []).map((currency) => (
                            <option key={currency} value={currency}>
                              {currency}
                            </option>
                          ))}
                        </select>
                      </label>

                      <label className="block space-y-2">
                        <span className="text-sm font-medium text-[#0F172A]">Currency Symbol</span>
                        <input
                          value={systemSettingsForm.currency_symbol}
                          onChange={(event) =>
                            setSystemSettingsForm((current) => ({
                              ...current,
                              currency_symbol: event.target.value,
                            }))
                          }
                          disabled={!isOwner}
                          className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm disabled:bg-gray-50"
                        />
                      </label>

                      <label className="block space-y-2">
                        <span className="text-sm font-medium text-[#0F172A]">Distance Unit</span>
                        <select
                          value={systemSettingsForm.distance_unit}
                          onChange={(event) =>
                            setSystemSettingsForm((current) => ({
                              ...current,
                              distance_unit: event.target.value,
                            }))
                          }
                          disabled={!isOwner}
                          className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm disabled:bg-gray-50"
                        >
                          {(systemSettings?.supported_distance_units || []).map((unit) => (
                            <option key={unit} value={unit}>
                              {unit}
                            </option>
                          ))}
                        </select>
                      </label>

                      <button
                        onClick={() => void handleSaveSystemSettings()}
                        disabled={!isOwner || isSavingSystemSettings}
                        className="inline-flex items-center gap-2 rounded-xl bg-[#2563EB] px-4 py-2.5 text-sm font-medium text-white hover:bg-[#1d4ed8] disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {isSavingSystemSettings ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                        Save System Settings
                      </button>
                    </>
                  )}
                </div>
              </div>
              <div className="rounded-2xl border border-gray-200 bg-white p-5">
                <h2 className="text-lg font-semibold text-[#0F172A]">Operational Snapshot</h2>
                <div className="mt-4 space-y-4 text-sm text-gray-600">
                  <div className="rounded-xl border border-gray-200 px-4 py-3">
                    <div className="font-medium text-[#0F172A]">Current Currency</div>
                    <div className="mt-1">
                      {systemSettings?.default_currency || 'GHS'} ({systemSettings?.currency_symbol || 'GHS'})
                    </div>
                  </div>
                  <div className="rounded-xl border border-gray-200 px-4 py-3">
                    <div className="font-medium text-[#0F172A]">Distance Measurement</div>
                    <div className="mt-1">{systemSettings?.distance_unit || 'KM'}</div>
                  </div>
                  <div className="rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-blue-900">
                    Currency and unit defaults now live in the backend so ride fares, reports, and upcoming ride-management
                    screens can share one source of truth.
                  </div>
                  {!isOwner && (
                    <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-amber-900">
                      Only the owner can change system currency and distance settings. Admins can still manage ride-purpose
                      and other approved master data.
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}

          {activeTab === 'fleet' && (
            <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
              <div className="rounded-2xl border border-gray-200 bg-white p-5">
                <h2 className="text-lg font-semibold text-[#0F172A]">Fleet Defaults</h2>
                <div className="mt-4 space-y-4">
                  <input
                    value={defaultWeeklyTarget}
                    onChange={(event) => setDefaultWeeklyTarget(event.target.value)}
                    className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
                    placeholder="Default weekly target"
                  />
                  <input
                    value={defaultDeposit}
                    onChange={(event) => setDefaultDeposit(event.target.value)}
                    className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
                    placeholder="Default deposit"
                  />
                </div>
              </div>
              <EmptyState
                title="Fleet configuration remains available"
                description="Vehicle and driver defaults stay in this settings shell without affecting the new ride and master-data flow."
              />
            </div>
          )}

          {activeTab === 'role-permissions' && (
            <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
              <div className="rounded-2xl border border-gray-200 bg-white p-5">
                <h2 className="text-lg font-semibold text-[#0F172A]">Admin Financial Visibility</h2>
                <p className="mt-1 text-sm text-gray-500">
                  Sensitive owner and investor economics stay hidden from admins unless the owner enables access here.
                </p>
                <label className="mt-4 flex items-center justify-between rounded-xl border border-gray-200 px-4 py-3">
                  <div>
                    <div className="text-sm font-medium text-[#0F172A]">Include Fuel In Profitability</div>
                    <div className="text-xs text-gray-500">
                      Fuel remains monitoring-only by default and only affects vehicle profitability when enabled by the owner.
                    </div>
                  </div>
                  <input
                    type="checkbox"
                    checked={Boolean(systemSettingsForm.include_fuel_in_profitability)}
                    onChange={(event) =>
                      setSystemSettingsForm((current) => ({
                        ...current,
                        include_fuel_in_profitability: event.target.checked,
                      }))
                    }
                    disabled={!isOwner}
                    className="h-4 w-4 rounded border-gray-300 text-[#2563EB] focus:ring-[#2563EB] disabled:opacity-60"
                  />
                </label>
                <div className="mt-4 space-y-3">
                  {[
                    ['view_vehicle_investment', 'View Vehicle Investment'],
                    ['view_vehicle_recovery', 'View Vehicle Recovery'],
                    ['view_profitability', 'View Profitability'],
                    ['view_investor_information', 'View Investor Information'],
                    ['view_reports', 'View Reports'],
                    ['export_financial_reports', 'Export Financial Reports'],
                    ['manage_vehicle_cost_items', 'Manage Vehicle Cost Items'],
                  ].map(([key, label]) => (
                    <label key={key} className="flex items-center justify-between rounded-xl border border-gray-200 px-4 py-3">
                      <div>
                        <div className="text-sm font-medium text-[#0F172A]">{label}</div>
                        <div className="text-xs text-gray-500">Applied on both API responses and admin screens.</div>
                      </div>
                      <input
                        type="checkbox"
                        checked={Boolean(systemSettingsForm.role_permissions.admin[key as keyof typeof systemSettingsForm.role_permissions.admin])}
                        onChange={(event) =>
                          setSystemSettingsForm((current) => ({
                            ...current,
                            role_permissions: {
                              ...current.role_permissions,
                              admin: {
                                ...current.role_permissions.admin,
                                [key]: event.target.checked,
                              },
                            },
                          }))
                        }
                        disabled={!isOwner}
                        className="h-4 w-4 rounded border-gray-300 text-[#2563EB] focus:ring-[#2563EB] disabled:opacity-60"
                      />
                    </label>
                  ))}
                </div>
                <button
                  onClick={() => void handleSaveSystemSettings()}
                  disabled={!isOwner || isSavingSystemSettings}
                  className="mt-4 inline-flex items-center gap-2 rounded-xl bg-[#2563EB] px-4 py-2.5 text-sm font-medium text-white hover:bg-[#1d4ed8] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {isSavingSystemSettings ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                  Save Role Permissions
                </button>
              </div>
              <div className="rounded-2xl border border-gray-200 bg-white p-5">
                <h2 className="text-lg font-semibold text-[#0F172A]">Permission Audit Trail</h2>
                <div className="mt-4 space-y-3">
                  {(systemSettings?.role_permission_audit_log || []).length ? (
                    (systemSettings?.role_permission_audit_log || []).slice().reverse().map((entry, index) => (
                      <div key={`${entry.changed_at || 'permission'}-${index}`} className="rounded-xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-700">
                        <div className="font-medium text-[#0F172A]">{entry.changed_keys?.join(', ') || 'Permission update'}</div>
                        <div className="mt-1 text-xs text-gray-500">Changed at {entry.changed_at || 'Unknown time'}</div>
                      </div>
                    ))
                  ) : (
                    <EmptyState
                      title="No permission changes yet"
                      description="Role permission changes made by the owner will appear here for audit visibility."
                    />
                  )}
                </div>
              </div>
            </div>
          )}

          {activeTab === 'revenue' && (
            <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
              <div className="rounded-2xl border border-gray-200 bg-white p-5">
                <h2 className="text-lg font-semibold text-[#0F172A]">Revenue Defaults</h2>
                <div className="mt-4 space-y-4">
                  <input
                    value={commissionRate}
                    onChange={(event) => setCommissionRate(event.target.value)}
                    className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
                    placeholder="Commission rate"
                  />
                  <input
                    value={baseFare}
                    onChange={(event) => setBaseFare(event.target.value)}
                    className="w-full rounded-xl border border-gray-300 px-4 py-2.5 text-sm"
                    placeholder="Base fare"
                  />
                </div>
              </div>
              <EmptyState
                title="Revenue settings shell preserved"
                description="Ride revenue and trip analytics now come from live ride data, while configurable pricing defaults can continue here."
              />
            </div>
          )}

          {activeTab === 'notifications' && (
            <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
              <div className="rounded-2xl border border-gray-200 bg-white p-5">
                <h2 className="text-lg font-semibold text-[#0F172A]">Notification Preferences</h2>
                <div className="mt-4 space-y-4">
                  <label className="flex items-center justify-between rounded-xl border border-gray-200 px-4 py-3">
                    <span className="text-sm font-medium text-[#0F172A]">Email Notifications</span>
                    <input
                      type="checkbox"
                      checked={emailNotifications}
                      onChange={(event) => setEmailNotifications(event.target.checked)}
                      className="h-4 w-4 rounded border-gray-300 text-[#2563EB] focus:ring-[#2563EB]"
                    />
                  </label>
                  <label className="flex items-center justify-between rounded-xl border border-gray-200 px-4 py-3">
                    <span className="text-sm font-medium text-[#0F172A]">SMS Notifications</span>
                    <input
                      type="checkbox"
                      checked={smsNotifications}
                      onChange={(event) => setSmsNotifications(event.target.checked)}
                      className="h-4 w-4 rounded border-gray-300 text-[#2563EB] focus:ring-[#2563EB]"
                    />
                  </label>
                </div>
              </div>
              <EmptyState
                title="Reminder delivery points preserved"
                description="Scheduled pickup reminders still target driver, admin, and owner portals while this area keeps channel-level preferences grouped together."
              />
            </div>
          )}

          {activeTab === 'security' && (
            <div className="space-y-4">
              <div className="rounded-2xl border border-red-200 bg-red-50 p-5">
                <div className="flex items-start gap-3">
                  <Shield className="mt-0.5 h-5 w-5 text-red-600" />
                  <div>
                    <div className="text-sm font-semibold text-red-900">Owner and admin permissions remain enforced</div>
                    <p className="mt-1 text-sm text-red-800">
                      Drivers cannot create master data and only see active approved values in customer, booking, and ride forms.
                    </p>
                  </div>
                </div>
              </div>
              <EmptyState
                title="Security settings shell preserved"
                description="This page keeps role boundaries visible while the backend continues using the existing JWT and role-based permissions."
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
