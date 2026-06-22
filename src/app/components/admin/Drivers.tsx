import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle,
  Clock,
  Download,
  Edit,
  Eye,
  Filter,
  Loader2,
  MoreVertical,
  Phone,
  Plus,
  Search,
  Shield,
  Truck,
  UserCheck,
  UserX,
  Users,
  Wallet,
  X,
} from 'lucide-react';
import { apiRequest, ApiRequestError } from '../../lib/api';

type ApprovalStatus = 'pending' | 'approved' | 'rejected';
type AccountStatus = 'active' | 'inactive' | 'suspended';
type DriverTab = 'personal' | 'license' | 'deposit' | 'guarantor' | 'vehicle' | 'history';
type ManagedRole = 'admin' | 'driver';

interface DriverProfile {
  ghana_card_number: string | null;
  license_number: string | null;
  license_expiry: string | null;
  license_class: string | null;
  years_experience: number | null;
  can_drive_manual: boolean | null;
  can_drive_automatic: boolean | null;
  emergency_contact_name: string | null;
  emergency_contact_phone: string | null;
  deposit_required: boolean | null;
  deposit_paid: boolean | null;
  deposit_balance: number | null;
  approval_status: ApprovalStatus | null;
  assigned_vehicle_id: string | null;
  guarantor: {
    full_name: string | null;
    phone: string | null;
    relationship: string | null;
    address: string | null;
    occupation: string | null;
    ghana_card_number: string | null;
    verification_status: 'pending' | 'verified' | 'rejected' | null;
  } | null;
}

interface Driver {
  id: string;
  full_name: string;
  email: string;
  phone: string;
  role: 'driver';
  status: AccountStatus;
  last_login: string | null;
  created_at: string | null;
  updated_at: string | null;
  driver_profile: DriverProfile | null;
}

interface DriversResponse {
  success: boolean;
  message: string;
  data: {
    drivers: Driver[];
  };
}

interface ManagedUser {
  id: string;
  full_name: string;
  email: string;
  phone: string;
  role: ManagedRole;
  status: AccountStatus;
  created_at: string | null;
}

interface UsersResponse {
  success: boolean;
  message: string;
  data: {
    users: ManagedUser[];
  };
}

interface DriverResponse {
  success: boolean;
  message: string;
  data: {
    driver: Driver;
  };
}

interface DriverCreateForm {
  full_name: string;
  email: string;
  phone: string;
  password: string;
  role: ManagedRole;
  status: AccountStatus;
  ghana_card_number: string;
  license_number: string;
  license_expiry: string;
  license_class: string;
  years_experience: string;
  can_drive_manual: boolean;
  can_drive_automatic: boolean;
  emergency_contact_name: string;
  emergency_contact_phone: string;
  deposit_required: boolean;
  deposit_paid: boolean;
  deposit_balance: string;
  approval_status: ApprovalStatus;
  assigned_vehicle_id: string;
  guarantor_full_name: string;
  guarantor_phone: string;
  guarantor_relationship: string;
  guarantor_address: string;
  guarantor_occupation: string;
  guarantor_ghana_card_number: string;
  guarantor_verification_status: 'pending' | 'verified' | 'rejected';
}

const initialDriverForm: DriverCreateForm = {
  full_name: '',
  email: '',
  phone: '',
  password: '',
  role: 'driver',
  status: 'inactive',
  ghana_card_number: '',
  license_number: '',
  license_expiry: '',
  license_class: '',
  years_experience: '',
  can_drive_manual: false,
  can_drive_automatic: true,
  emergency_contact_name: '',
  emergency_contact_phone: '',
  deposit_required: false,
  deposit_paid: false,
  deposit_balance: '',
  approval_status: 'pending',
  assigned_vehicle_id: '',
  guarantor_full_name: '',
  guarantor_phone: '',
  guarantor_relationship: '',
  guarantor_address: '',
  guarantor_occupation: '',
  guarantor_ghana_card_number: '',
  guarantor_verification_status: 'pending',
};

function formatDate(value: string | null) {
  if (!value) {
    return 'Not available';
  }

  return new Date(value).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });
}

function formatApprovalStatus(status: ApprovalStatus | null) {
  return status ? status.charAt(0).toUpperCase() + status.slice(1) : 'Pending';
}

function buildDriverProfilePayload(form: DriverCreateForm) {
  const parseOptionalString = (value: string) => (value.trim() ? value.trim() : undefined);
  const parseOptionalNumber = (value: string) => (value.trim() ? Number(value) : undefined);

  return {
    ghana_card_number: parseOptionalString(form.ghana_card_number),
    license_number: parseOptionalString(form.license_number),
    license_expiry: parseOptionalString(form.license_expiry),
    license_class: parseOptionalString(form.license_class),
    years_experience: parseOptionalNumber(form.years_experience),
    can_drive_manual: form.can_drive_manual,
    can_drive_automatic: form.can_drive_automatic,
    emergency_contact_name: parseOptionalString(form.emergency_contact_name),
    emergency_contact_phone: parseOptionalString(form.emergency_contact_phone),
    deposit_required: form.deposit_required,
    deposit_paid: form.deposit_paid,
    deposit_balance: parseOptionalNumber(form.deposit_balance),
    approval_status: form.approval_status,
    assigned_vehicle_id: parseOptionalString(form.assigned_vehicle_id),
    guarantor: {
      full_name: parseOptionalString(form.guarantor_full_name),
      phone: parseOptionalString(form.guarantor_phone),
      relationship: parseOptionalString(form.guarantor_relationship),
      address: parseOptionalString(form.guarantor_address),
      occupation: parseOptionalString(form.guarantor_occupation),
      ghana_card_number: parseOptionalString(form.guarantor_ghana_card_number),
      verification_status: form.guarantor_verification_status,
    },
  };
}

function formFromDriver(driver: Driver): DriverCreateForm {
  const profile = driver.driver_profile;
  const guarantor = profile?.guarantor;

  return {
    full_name: driver.full_name,
    email: driver.email,
    phone: driver.phone,
    password: '',
    role: 'driver',
    status: driver.status,
    ghana_card_number: profile?.ghana_card_number || '',
    license_number: profile?.license_number || '',
    license_expiry: profile?.license_expiry || '',
    license_class: profile?.license_class || '',
    years_experience:
      profile?.years_experience !== null && profile?.years_experience !== undefined
        ? String(profile.years_experience)
        : '',
    can_drive_manual: profile?.can_drive_manual ?? false,
    can_drive_automatic: profile?.can_drive_automatic ?? true,
    emergency_contact_name: profile?.emergency_contact_name || '',
    emergency_contact_phone: profile?.emergency_contact_phone || '',
    deposit_required: profile?.deposit_required ?? false,
    deposit_paid: profile?.deposit_paid ?? false,
    deposit_balance:
      profile?.deposit_balance !== null && profile?.deposit_balance !== undefined
        ? String(profile.deposit_balance)
        : '',
    approval_status: profile?.approval_status || 'pending',
    assigned_vehicle_id: profile?.assigned_vehicle_id || '',
    guarantor_full_name: guarantor?.full_name || '',
    guarantor_phone: guarantor?.phone || '',
    guarantor_relationship: guarantor?.relationship || '',
    guarantor_address: guarantor?.address || '',
    guarantor_occupation: guarantor?.occupation || '',
    guarantor_ghana_card_number: guarantor?.ghana_card_number || '',
    guarantor_verification_status: guarantor?.verification_status || 'pending',
  };
}

function StatusBadge({ status }: { status: AccountStatus }) {
  const statusConfig: Record<AccountStatus, string> = {
    active: 'bg-green-100 text-green-800',
    inactive: 'bg-gray-100 text-gray-800',
    suspended: 'bg-red-100 text-red-800',
  };

  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${statusConfig[status]}`}>
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

function ApprovalBadge({ status }: { status: ApprovalStatus | null }) {
  const value = status || 'pending';
  const statusConfig: Record<ApprovalStatus, string> = {
    pending: 'bg-yellow-100 text-yellow-800',
    approved: 'bg-green-100 text-green-800',
    rejected: 'bg-red-100 text-red-800',
  };

  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${statusConfig[value]}`}>
      {formatApprovalStatus(value)}
    </span>
  );
}

export default function Drivers() {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedStatus, setSelectedStatus] = useState('all');
  const [drivers, setDrivers] = useState<Driver[]>([]);
  const [adminUsers, setAdminUsers] = useState<ManagedUser[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [pageError, setPageError] = useState('');
  const [selectedDriver, setSelectedDriver] = useState<Driver | null>(null);
  const [isProfileModalOpen, setIsProfileModalOpen] = useState(false);
  const [profileMode, setProfileMode] = useState<'view' | 'edit' | 'create'>('view');
  const [activeTab, setActiveTab] = useState<DriverTab>('personal');
  const [driverForm, setDriverForm] = useState<DriverCreateForm>(initialDriverForm);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState('');
  const [actionError, setActionError] = useState('');

  const storedUser = localStorage.getItem('flux_user');
  const currentRole = storedUser ? JSON.parse(storedUser).role : null;

  const loadDrivers = async () => {
    setIsLoading(true);
    setPageError('');

    try {
      const driverRequest = apiRequest<DriversResponse>('/drivers');
      const usersRequest =
        currentRole === 'owner' ? apiRequest<UsersResponse>('/users') : Promise.resolve(null);

      const [driverResponse, usersResponse] = await Promise.all([driverRequest, usersRequest]);
      setDrivers(driverResponse.data.drivers);
      if (usersResponse?.data?.users) {
        setAdminUsers(usersResponse.data.users.filter((user) => user.role === 'admin'));
      } else {
        setAdminUsers([]);
      }
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setPageError(error.message);
      } else {
        setPageError('Unable to load drivers right now.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadDrivers();
  }, [currentRole]);

  const stats = useMemo(() => {
    const activeDrivers = drivers.filter((driver) => driver.status === 'active').length;
    const pendingDrivers = drivers.filter(
      (driver) => (driver.driver_profile?.approval_status || 'pending') === 'pending',
    ).length;
    const suspendedDrivers = drivers.filter((driver) => driver.status === 'suspended').length;
    const approvedDrivers = drivers.filter(
      (driver) => driver.driver_profile?.approval_status === 'approved',
    ).length;

    return [
      { label: 'Total Drivers', value: drivers.length, color: 'bg-blue-500', icon: Users },
      { label: 'Active Drivers', value: activeDrivers, color: 'bg-green-500', icon: CheckCircle },
      { label: 'Pending Approval', value: pendingDrivers, color: 'bg-yellow-500', icon: Clock },
      { label: 'Suspended', value: suspendedDrivers, color: 'bg-red-500', icon: UserX },
      { label: 'Approved', value: approvedDrivers, color: 'bg-purple-500', icon: UserCheck },
    ];
  }, [drivers]);

  const filteredDrivers = useMemo(
    () =>
      drivers.filter((driver) => {
        const approvalStatus = driver.driver_profile?.approval_status || 'pending';
        const statusMatch =
          selectedStatus === 'all' ||
          driver.status === selectedStatus ||
          approvalStatus === selectedStatus;
        const guarantorName = driver.driver_profile?.guarantor?.full_name || '';
        const licenseNumber = driver.driver_profile?.license_number || '';
        const assignedVehicle = driver.driver_profile?.assigned_vehicle_id || '';
        const query = searchQuery.toLowerCase();

        const searchMatch =
          driver.full_name.toLowerCase().includes(query) ||
          driver.phone.toLowerCase().includes(query) ||
          licenseNumber.toLowerCase().includes(query) ||
          guarantorName.toLowerCase().includes(query) ||
          assignedVehicle.toLowerCase().includes(query);

        return statusMatch && searchMatch;
      }),
    [drivers, searchQuery, selectedStatus],
  );

  const openCreateModal = () => {
    setProfileMode('create');
    setSelectedDriver(null);
    setDriverForm({
      ...initialDriverForm,
      role: 'driver',
      status: currentRole === 'owner' ? 'active' : 'inactive',
    });
    setActiveTab('personal');
    setFormError('');
    setIsProfileModalOpen(true);
  };

  const openDriverModal = async (driverId: string, mode: 'view' | 'edit') => {
    setFormError('');
    setActionError('');
    setIsProfileModalOpen(true);
    setProfileMode(mode);
    setActiveTab('personal');

    try {
      const response = await apiRequest<DriverResponse>(`/drivers/${driverId}`);
      const driver = response.data.driver;
      setSelectedDriver(driver);
      setDriverForm(formFromDriver(driver));
    } catch (error) {
      setIsProfileModalOpen(false);
      if (error instanceof ApiRequestError) {
        setActionError(error.message);
      } else {
        setActionError('Unable to load driver profile right now.');
      }
    }
  };

  const closeModal = () => {
    setIsProfileModalOpen(false);
    setSelectedDriver(null);
    setDriverForm(initialDriverForm);
    setFormError('');
    setActiveTab('personal');
  };

  const updateFormField = <K extends keyof DriverCreateForm>(field: K, value: DriverCreateForm[K]) => {
    setDriverForm((current) => ({
      ...current,
      [field]: value,
    }));
  };

  const handleProfileSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setIsSubmitting(true);
    setFormError('');

    try {
      if (profileMode === 'create') {
        const payload: Record<string, unknown> = {
          full_name: driverForm.full_name.trim(),
          email: driverForm.email.trim(),
          phone: driverForm.phone.trim(),
          password: driverForm.password,
          role: currentRole === 'owner' ? driverForm.role : 'driver',
          status: driverForm.status,
        };

        if ((payload.role as ManagedRole) === 'driver') {
          payload.driver_profile = buildDriverProfilePayload(driverForm);
        }

        await apiRequest('/users', {
          method: 'POST',
          body: JSON.stringify(payload),
        });
      } else if (selectedDriver) {
        await apiRequest(`/drivers/${selectedDriver.id}/profile`, {
          method: 'PATCH',
          body: JSON.stringify({
            driver_profile: buildDriverProfilePayload(driverForm),
          }),
        });
      }

      closeModal();
      await loadDrivers();
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setFormError(error.message);
      } else {
        setFormError('Unable to save driver details right now.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleApprovalAction = async (driverId: string, approval_status: ApprovalStatus) => {
    setActionError('');
    try {
      await apiRequest(`/drivers/${driverId}/approval-status`, {
        method: 'PATCH',
        body: JSON.stringify({ approval_status }),
      });
      await loadDrivers();
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setActionError(error.message);
      } else {
        setActionError('Unable to update approval status right now.');
      }
    }
  };

  const handleStatusAction = async (driverId: string, status: AccountStatus) => {
    setActionError('');
    try {
      await apiRequest(`/drivers/${driverId}/status`, {
        method: 'PATCH',
        body: JSON.stringify({ status }),
      });
      await loadDrivers();
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setActionError(error.message);
      } else {
        setActionError('Unable to update driver status right now.');
      }
    }
  };

  if (currentRole === 'driver') {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Drivers do not have access to Driver Management.
        </div>
      </div>
    );
  }

  const pendingApprovals = drivers.filter(
    (driver) => (driver.driver_profile?.approval_status || 'pending') === 'pending',
  ).length;

  const tabs: { id: DriverTab; label: string }[] = [
    { id: 'personal', label: 'Personal Info' },
    { id: 'license', label: 'License' },
    { id: 'deposit', label: 'Deposit' },
    { id: 'guarantor', label: 'Guarantor' },
    { id: 'vehicle', label: 'Vehicle' },
    { id: 'history', label: 'History' },
  ];
  const showDriverTabs = profileMode !== 'create' || driverForm.role === 'driver';

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">
            {currentRole === 'owner' ? 'User & Driver Management' : 'Driver Management'}
          </h1>
          <p className="text-gray-500 mt-1">
            {currentRole === 'owner'
              ? 'Create admins or drivers and manage embedded guarantor records'
              : 'Manage drivers and embedded guarantor records'}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button className="px-4 py-2.5 border border-gray-300 rounded-lg hover:bg-gray-50 flex items-center gap-2 font-medium text-gray-700">
            <Download className="w-5 h-5" />
            Export
          </button>
          <button
            onClick={openCreateModal}
            className="px-4 py-2.5 bg-[#2563EB] text-white rounded-lg hover:bg-[#1d4ed8] flex items-center gap-2 font-medium"
          >
            <Plus className="w-5 h-5" />
            {currentRole === 'owner' ? 'Add User' : 'Add Driver'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
        {stats.map((stat, index) => {
          const Icon = stat.icon;
          return (
            <div key={index} className="bg-white rounded-lg border border-gray-200 p-5">
              <div className="flex items-start justify-between mb-3">
                <div className={`w-10 h-10 ${stat.color} rounded-lg flex items-center justify-center`}>
                  <Icon className="w-5 h-5 text-white" />
                </div>
              </div>
              <div className="text-2xl font-semibold text-gray-900 mb-1">{stat.value}</div>
              <div className="text-sm text-gray-600">{stat.label}</div>
            </div>
          );
        })}
      </div>

      {currentRole === 'owner' && (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-gray-900">Admin Users</h2>
              <p className="text-sm text-gray-500 mt-1">Owner-created admin accounts</p>
            </div>
            <div className="text-sm text-gray-500">
              Total admins: <span className="font-semibold text-gray-900">{adminUsers.length}</span>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="px-6 py-4 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">Name</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">Email</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">Phone</th>
                  <th className="px-6 py-4 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {adminUsers.map((adminUser) => (
                  <tr key={adminUser.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-6 py-4">
                      <div className="font-medium text-gray-900">{adminUser.full_name}</div>
                    </td>
                    <td className="px-6 py-4 text-gray-700">{adminUser.email}</td>
                    <td className="px-6 py-4 text-gray-700">{adminUser.phone}</td>
                    <td className="px-6 py-4">
                      <StatusBadge status={adminUser.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {adminUsers.length === 0 && (
              <div className="px-6 py-10 text-sm text-gray-500 text-center">
                No admin users created yet.
              </div>
            )}
          </div>
        </div>
      )}

      {pendingApprovals > 0 && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 flex items-start gap-3">
          <Clock className="w-5 h-5 text-yellow-600 mt-0.5" />
          <div className="flex-1">
            <h3 className="text-sm font-semibold text-yellow-900">
              {pendingApprovals} Driver{pendingApprovals > 1 ? 's' : ''} Pending Approval
            </h3>
            <p className="text-sm text-yellow-700 mt-1">
              Review and approve pending driver applications to activate them.
            </p>
          </div>
        </div>
      )}

      <div className="bg-white rounded-lg border border-gray-200 p-4">
        <div className="flex flex-col lg:flex-row gap-4">
          <div className="flex-1">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
              <input
                type="text"
                placeholder="Search by name, phone, license, guarantor, or vehicle..."
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                className="w-full pl-10 pr-4 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent"
              />
            </div>
          </div>

          <div className="flex gap-2">
            <select
              value={selectedStatus}
              onChange={(event) => setSelectedStatus(event.target.value)}
              className="px-4 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:border-transparent bg-white"
            >
              <option value="all">All Status</option>
              <option value="active">Active</option>
              <option value="inactive">Inactive</option>
              <option value="suspended">Suspended</option>
              <option value="pending">Pending Approval</option>
              <option value="approved">Approved</option>
              <option value="rejected">Rejected</option>
            </select>

            <button className="px-4 py-2.5 border border-gray-300 rounded-lg hover:bg-gray-50 flex items-center gap-2">
              <Filter className="w-4 h-4" />
              More Filters
            </button>
          </div>
        </div>
      </div>

      {pageError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {pageError}
        </div>
      )}

      {actionError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {actionError}
        </div>
      )}

      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        {isLoading ? (
          <div className="px-6 py-16 flex items-center justify-center gap-3 text-gray-500">
            <Loader2 className="w-5 h-5 animate-spin" />
            <span>Loading drivers...</span>
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-gray-50 border-b border-gray-200">
                  <tr>
                    <th className="px-6 py-4 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                      Driver
                    </th>
                    <th className="px-6 py-4 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                      License Number
                    </th>
                    <th className="px-6 py-4 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                      Approval Status
                    </th>
                    <th className="px-6 py-4 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                      Account Status
                    </th>
                    <th className="px-6 py-4 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                      Deposit Paid
                    </th>
                    <th className="px-6 py-4 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                      Guarantor
                    </th>
                    <th className="px-6 py-4 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                      Assigned Vehicle
                    </th>
                    <th className="px-6 py-4 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {filteredDrivers.map((driver) => {
                    const approvalStatus = driver.driver_profile?.approval_status || 'pending';
                    const depositPaid = driver.driver_profile?.deposit_paid ? 'Yes' : 'No';
                    const guarantorName = driver.driver_profile?.guarantor?.full_name || 'Not set';
                    const assignedVehicle = driver.driver_profile?.assigned_vehicle_id || 'Unassigned';
                    const initials = driver.full_name
                      .split(' ')
                      .map((name) => name[0])
                      .join('')
                      .slice(0, 2);

                    return (
                      <tr key={driver.id} className="hover:bg-gray-50 transition-colors">
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-3">
                            <div className="w-12 h-12 bg-gradient-to-br from-blue-500 to-purple-500 rounded-full flex items-center justify-center text-white font-semibold">
                              {initials}
                            </div>
                            <div>
                              <div className="font-semibold text-gray-900">{driver.full_name}</div>
                              <div className="flex items-center gap-2 text-xs text-gray-500 mt-1">
                                <Phone className="w-3 h-3" />
                                <span>{driver.phone}</span>
                              </div>
                            </div>
                          </div>
                        </td>
                        <td className="px-6 py-4 text-sm text-gray-900">
                          {driver.driver_profile?.license_number || 'Not set'}
                        </td>
                        <td className="px-6 py-4">
                          <ApprovalBadge status={approvalStatus} />
                        </td>
                        <td className="px-6 py-4">
                          <StatusBadge status={driver.status} />
                        </td>
                        <td className="px-6 py-4 text-sm text-gray-900">{depositPaid}</td>
                        <td className="px-6 py-4 text-sm text-gray-900">{guarantorName}</td>
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-2 text-sm text-gray-900">
                            <Truck className="w-4 h-4 text-gray-400" />
                            <span>{assignedVehicle}</span>
                          </div>
                        </td>
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-2">
                            {approvalStatus === 'pending' && (
                              <>
                                <button
                                  onClick={() => void handleApprovalAction(driver.id, 'approved')}
                                  className="p-2 bg-green-50 hover:bg-green-100 rounded-lg transition-colors"
                                  title="Approve"
                                >
                                  <UserCheck className="w-4 h-4 text-green-600" />
                                </button>
                                <button
                                  onClick={() => void handleApprovalAction(driver.id, 'rejected')}
                                  className="p-2 bg-red-50 hover:bg-red-100 rounded-lg transition-colors"
                                  title="Reject"
                                >
                                  <UserX className="w-4 h-4 text-red-600" />
                                </button>
                              </>
                            )}
                            <button
                              onClick={() => void openDriverModal(driver.id, 'view')}
                              className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
                              title="View Profile"
                            >
                              <Eye className="w-4 h-4 text-gray-600" />
                            </button>
                            <button
                              onClick={() => void openDriverModal(driver.id, 'edit')}
                              className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
                              title="Edit Profile"
                            >
                              <Edit className="w-4 h-4 text-gray-600" />
                            </button>
                            <button
                              onClick={() =>
                                void handleStatusAction(
                                  driver.id,
                                  driver.status === 'active' ? 'suspended' : 'active',
                                )
                              }
                              className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
                              title={driver.status === 'active' ? 'Suspend Driver' : 'Activate Driver'}
                            >
                              <MoreVertical className="w-4 h-4 text-gray-600" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div className="px-6 py-4 border-t border-gray-200 flex items-center justify-between bg-gray-50">
              <div className="text-sm text-gray-600">
                Showing <span className="font-medium">{filteredDrivers.length}</span> of{' '}
                <span className="font-medium">{drivers.length}</span> drivers
              </div>
              <div className="flex items-center gap-2">
                <button className="px-3 py-1.5 border border-gray-300 rounded-lg hover:bg-white text-sm font-medium text-gray-700">
                  Previous
                </button>
                <button className="px-3 py-1.5 bg-[#2563EB] text-white rounded-lg text-sm font-medium">
                  1
                </button>
                <button className="px-3 py-1.5 border border-gray-300 rounded-lg hover:bg-white text-sm font-medium text-gray-700">
                  Next
                </button>
              </div>
            </div>
          </>
        )}
      </div>

      {isProfileModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 px-4">
          <div className="w-full max-w-5xl h-[90vh] rounded-2xl bg-white shadow-2xl border border-gray-200 overflow-hidden flex flex-col">
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
              <div>
                <h2 className="text-xl font-semibold text-gray-900">
                  {profileMode === 'create'
                    ? currentRole === 'owner'
                      ? 'Add User'
                      : 'Add Driver'
                    : profileMode === 'edit'
                      ? 'Edit Driver'
                      : 'Driver Profile'}
                </h2>
                <p className="text-sm text-gray-500 mt-1">
                  {profileMode === 'create'
                    ? currentRole === 'owner'
                      ? 'Create an admin or driver account.'
                      : 'Create a driver with embedded guarantor details.'
                    : 'Review and manage driver records with embedded guarantor information.'}
                </p>
              </div>
              <button
                onClick={closeModal}
                className="p-2 rounded-lg hover:bg-gray-100 transition-colors"
                aria-label="Close driver modal"
              >
                <X className="w-5 h-5 text-gray-500" />
              </button>
            </div>

            <form onSubmit={handleProfileSubmit} className="flex flex-1 min-h-0 flex-col">
              <div className="border-b border-gray-200 bg-gray-50 px-6">
                <div className="flex overflow-x-auto">
                  {(showDriverTabs ? tabs : tabs.filter((tab) => tab.id === 'personal')).map((tab) => (
                    <button
                      key={tab.id}
                      type="button"
                      onClick={() => setActiveTab(tab.id)}
                      className={`px-4 py-3 text-sm font-medium whitespace-nowrap border-b-2 ${
                        activeTab === tab.id
                          ? 'border-[#2563EB] text-[#2563EB]'
                          : 'border-transparent text-gray-500 hover:text-gray-700'
                      }`}
                    >
                      {tab.label}
                    </button>
                    ))}
                </div>
              </div>

              <div className="flex-1 min-h-0 overflow-y-auto px-6 py-5">
                {formError && (
                  <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                    {formError}
                  </div>
                )}

                {activeTab === 'personal' && (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {profileMode === 'create' && (
                      <>
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-2">Role</label>
                          <select
                            value={driverForm.role}
                            onChange={(event) => updateFormField('role', event.target.value as ManagedRole)}
                            className="w-full px-3 py-2.5 border border-gray-300 rounded-lg bg-white"
                          >
                            {currentRole === 'owner' && <option value="admin">Admin</option>}
                            <option value="driver">Driver</option>
                          </select>
                        </div>
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-2">Status</label>
                          <select
                            value={driverForm.status}
                            onChange={(event) =>
                              updateFormField('status', event.target.value as AccountStatus)
                            }
                            className="w-full px-3 py-2.5 border border-gray-300 rounded-lg bg-white"
                          >
                            <option value="active">Active</option>
                            <option value="inactive">Inactive</option>
                            <option value="suspended">Suspended</option>
                          </select>
                        </div>
                      </>
                    )}
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">Full Name</label>
                      <input
                        value={driverForm.full_name}
                        onChange={(event) => updateFormField('full_name', event.target.value)}
                        readOnly={profileMode !== 'create'}
                        className="w-full px-3 py-2.5 border border-gray-300 rounded-lg bg-white"
                        required
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">Email</label>
                      <input
                        type="email"
                        value={driverForm.email}
                        onChange={(event) => updateFormField('email', event.target.value)}
                        readOnly={profileMode !== 'create'}
                        className="w-full px-3 py-2.5 border border-gray-300 rounded-lg bg-white"
                        required
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">Phone</label>
                      <input
                        value={driverForm.phone}
                        onChange={(event) => updateFormField('phone', event.target.value)}
                        readOnly={profileMode !== 'create'}
                        className="w-full px-3 py-2.5 border border-gray-300 rounded-lg bg-white"
                        required
                      />
                    </div>
                    {profileMode === 'create' && (
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">Password</label>
                        <input
                          type="password"
                          value={driverForm.password}
                          onChange={(event) => updateFormField('password', event.target.value)}
                          className="w-full px-3 py-2.5 border border-gray-300 rounded-lg bg-white"
                          required
                        />
                      </div>
                    )}
                    {showDriverTabs && (
                      <>
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-2">Ghana Card Number</label>
                          <input
                            value={driverForm.ghana_card_number}
                            onChange={(event) => updateFormField('ghana_card_number', event.target.value)}
                            readOnly={profileMode === 'view'}
                            className="w-full px-3 py-2.5 border border-gray-300 rounded-lg bg-white"
                          />
                        </div>
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-2">Emergency Contact Name</label>
                          <input
                            value={driverForm.emergency_contact_name}
                            onChange={(event) => updateFormField('emergency_contact_name', event.target.value)}
                            readOnly={profileMode === 'view'}
                            className="w-full px-3 py-2.5 border border-gray-300 rounded-lg bg-white"
                          />
                        </div>
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-2">Emergency Contact Phone</label>
                          <input
                            value={driverForm.emergency_contact_phone}
                            onChange={(event) => updateFormField('emergency_contact_phone', event.target.value)}
                            readOnly={profileMode === 'view'}
                            className="w-full px-3 py-2.5 border border-gray-300 rounded-lg bg-white"
                          />
                        </div>
                      </>
                    )}
                  </div>
                )}

                {showDriverTabs && activeTab === 'license' && (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">License Number</label>
                      <input
                        value={driverForm.license_number}
                        onChange={(event) => updateFormField('license_number', event.target.value)}
                        readOnly={profileMode === 'view'}
                        className="w-full px-3 py-2.5 border border-gray-300 rounded-lg bg-white"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">License Expiry</label>
                      <input
                        type="date"
                        value={driverForm.license_expiry}
                        onChange={(event) => updateFormField('license_expiry', event.target.value)}
                        readOnly={profileMode === 'view'}
                        className="w-full px-3 py-2.5 border border-gray-300 rounded-lg bg-white"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">License Class</label>
                      <input
                        value={driverForm.license_class}
                        onChange={(event) => updateFormField('license_class', event.target.value)}
                        readOnly={profileMode === 'view'}
                        className="w-full px-3 py-2.5 border border-gray-300 rounded-lg bg-white"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">Years Experience</label>
                      <input
                        type="number"
                        value={driverForm.years_experience}
                        onChange={(event) => updateFormField('years_experience', event.target.value)}
                        readOnly={profileMode === 'view'}
                        className="w-full px-3 py-2.5 border border-gray-300 rounded-lg bg-white"
                      />
                    </div>
                    <label className="flex items-center gap-2 text-sm text-gray-700">
                      <input
                        type="checkbox"
                        checked={driverForm.can_drive_manual}
                        onChange={(event) => updateFormField('can_drive_manual', event.target.checked)}
                        disabled={profileMode === 'view'}
                      />
                      Can drive manual
                    </label>
                    <label className="flex items-center gap-2 text-sm text-gray-700">
                      <input
                        type="checkbox"
                        checked={driverForm.can_drive_automatic}
                        onChange={(event) => updateFormField('can_drive_automatic', event.target.checked)}
                        disabled={profileMode === 'view'}
                      />
                      Can drive automatic
                    </label>
                  </div>
                )}

                {showDriverTabs && activeTab === 'deposit' && (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <label className="flex items-center gap-2 text-sm text-gray-700">
                      <input
                        type="checkbox"
                        checked={driverForm.deposit_required}
                        onChange={(event) => updateFormField('deposit_required', event.target.checked)}
                        disabled={profileMode === 'view'}
                      />
                      Deposit required
                    </label>
                    <label className="flex items-center gap-2 text-sm text-gray-700">
                      <input
                        type="checkbox"
                        checked={driverForm.deposit_paid}
                        onChange={(event) => updateFormField('deposit_paid', event.target.checked)}
                        disabled={profileMode === 'view'}
                      />
                      Deposit paid
                    </label>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">Deposit Balance</label>
                      <input
                        type="number"
                        step="0.01"
                        value={driverForm.deposit_balance}
                        onChange={(event) => updateFormField('deposit_balance', event.target.value)}
                        readOnly={profileMode === 'view'}
                        className="w-full px-3 py-2.5 border border-gray-300 rounded-lg bg-white"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">Approval Status</label>
                      <select
                        value={driverForm.approval_status}
                        onChange={(event) => updateFormField('approval_status', event.target.value as ApprovalStatus)}
                        disabled={profileMode === 'view'}
                        className="w-full px-3 py-2.5 border border-gray-300 rounded-lg bg-white"
                      >
                        <option value="pending">Pending</option>
                        <option value="approved">Approved</option>
                        <option value="rejected">Rejected</option>
                      </select>
                    </div>
                  </div>
                )}

                {showDriverTabs && activeTab === 'guarantor' && (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">Guarantor Full Name</label>
                      <input
                        value={driverForm.guarantor_full_name}
                        onChange={(event) => updateFormField('guarantor_full_name', event.target.value)}
                        readOnly={profileMode === 'view'}
                        className="w-full px-3 py-2.5 border border-gray-300 rounded-lg bg-white"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">Guarantor Phone</label>
                      <input
                        value={driverForm.guarantor_phone}
                        onChange={(event) => updateFormField('guarantor_phone', event.target.value)}
                        readOnly={profileMode === 'view'}
                        className="w-full px-3 py-2.5 border border-gray-300 rounded-lg bg-white"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">Relationship</label>
                      <input
                        value={driverForm.guarantor_relationship}
                        onChange={(event) => updateFormField('guarantor_relationship', event.target.value)}
                        readOnly={profileMode === 'view'}
                        className="w-full px-3 py-2.5 border border-gray-300 rounded-lg bg-white"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">Occupation</label>
                      <input
                        value={driverForm.guarantor_occupation}
                        onChange={(event) => updateFormField('guarantor_occupation', event.target.value)}
                        readOnly={profileMode === 'view'}
                        className="w-full px-3 py-2.5 border border-gray-300 rounded-lg bg-white"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">Ghana Card Number</label>
                      <input
                        value={driverForm.guarantor_ghana_card_number}
                        onChange={(event) => updateFormField('guarantor_ghana_card_number', event.target.value)}
                        readOnly={profileMode === 'view'}
                        className="w-full px-3 py-2.5 border border-gray-300 rounded-lg bg-white"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">Verification Status</label>
                      <select
                        value={driverForm.guarantor_verification_status}
                        onChange={(event) =>
                          updateFormField(
                            'guarantor_verification_status',
                            event.target.value as 'pending' | 'verified' | 'rejected',
                          )
                        }
                        disabled={profileMode === 'view'}
                        className="w-full px-3 py-2.5 border border-gray-300 rounded-lg bg-white"
                      >
                        <option value="pending">Pending</option>
                        <option value="verified">Verified</option>
                        <option value="rejected">Rejected</option>
                      </select>
                    </div>
                    <div className="md:col-span-2">
                      <label className="block text-sm font-medium text-gray-700 mb-2">Address</label>
                      <textarea
                        value={driverForm.guarantor_address}
                        onChange={(event) => updateFormField('guarantor_address', event.target.value)}
                        readOnly={profileMode === 'view'}
                        className="w-full px-3 py-2.5 border border-gray-300 rounded-lg bg-white min-h-[100px]"
                      />
                    </div>
                  </div>
                )}

                {showDriverTabs && activeTab === 'vehicle' && (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">Assigned Vehicle ID</label>
                      <input
                        value={driverForm.assigned_vehicle_id}
                        onChange={(event) => updateFormField('assigned_vehicle_id', event.target.value)}
                        readOnly={profileMode === 'view'}
                        className="w-full px-3 py-2.5 border border-gray-300 rounded-lg bg-white"
                      />
                      <p className="text-xs text-gray-500 mt-2">
                        Vehicle assignment is stored here, but full assignment workflows are still out of scope.
                      </p>
                    </div>
                    <div className="rounded-xl border border-gray-200 bg-gray-50 p-4">
                      <div className="flex items-start gap-3">
                        <Shield className="w-5 h-5 text-blue-600 mt-0.5" />
                        <div>
                          <h4 className="text-sm font-semibold text-gray-900">Vehicle Tab</h4>
                          <p className="text-sm text-gray-600 mt-1">
                            This section is ready for display and record maintenance only. Full assignment flows will come later.
                          </p>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {showDriverTabs && activeTab === 'history' && (
                  <div className="space-y-4">
                    <div className="rounded-xl border border-gray-200 bg-gray-50 p-4">
                      <h4 className="text-sm font-semibold text-gray-900 mb-3">Profile History</h4>
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
                        <div>
                          <div className="text-gray-500">Created</div>
                          <div className="font-medium text-gray-900">{formatDate(selectedDriver?.created_at || null)}</div>
                        </div>
                        <div>
                          <div className="text-gray-500">Updated</div>
                          <div className="font-medium text-gray-900">{formatDate(selectedDriver?.updated_at || null)}</div>
                        </div>
                        <div>
                          <div className="text-gray-500">Last Login</div>
                          <div className="font-medium text-gray-900">{formatDate(selectedDriver?.last_login || null)}</div>
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              <div className="shrink-0 border-t border-gray-200 bg-gray-50 px-6 py-4">
                <div className="flex items-center justify-between">
                  {selectedDriver && profileMode !== 'create' ? (
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() =>
                          void handleApprovalAction(
                            selectedDriver.id,
                            driverForm.approval_status === 'approved' ? 'rejected' : 'approved',
                          )
                        }
                        className="px-3 py-2 border border-gray-300 rounded-lg hover:bg-white text-sm font-medium text-gray-700"
                      >
                        {driverForm.approval_status === 'approved' ? 'Reject Driver' : 'Approve Driver'}
                      </button>
                      <button
                        type="button"
                        onClick={() =>
                          void handleStatusAction(
                            selectedDriver.id,
                            selectedDriver.status === 'active' ? 'suspended' : 'active',
                          )
                        }
                        className="px-3 py-2 border border-gray-300 rounded-lg hover:bg-white text-sm font-medium text-gray-700"
                      >
                        {selectedDriver.status === 'active' ? 'Suspend Driver' : 'Activate Driver'}
                      </button>
                    </div>
                  ) : (
                    <div />
                  )}
                  <div className="flex items-center gap-3">
                    <button
                      type="button"
                      onClick={closeModal}
                      className="px-4 py-2.5 border border-gray-300 rounded-lg hover:bg-white text-sm font-medium text-gray-700"
                    >
                      Cancel
                    </button>
                    {profileMode !== 'view' && (
                      <button
                        type="submit"
                        disabled={isSubmitting}
                        className="px-4 py-2.5 bg-[#2563EB] text-white rounded-lg hover:bg-[#1d4ed8] disabled:opacity-70 disabled:cursor-not-allowed flex items-center gap-2 font-medium"
                      >
                        {isSubmitting && <Loader2 className="w-4 h-4 animate-spin" />}
                        {isSubmitting
                          ? profileMode === 'create'
                            ? currentRole === 'owner'
                              ? 'Creating User...'
                              : 'Creating Driver...'
                            : 'Saving Profile...'
                          : profileMode === 'create'
                            ? currentRole === 'owner'
                              ? 'Add User'
                              : 'Add Driver'
                            : 'Save Changes'}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
