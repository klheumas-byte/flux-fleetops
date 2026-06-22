import { ChangeEvent, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle,
  Loader2,
  Upload,
  XCircle,
} from 'lucide-react';
import { apiRequest, ApiRequestError } from '../../lib/api';
import type { SessionUser } from '../../lib/auth-session';
import type { DriverActiveAssignment } from '../../lib/driver-api';

type FaultSeverity = 'low' | 'medium' | 'high' | 'critical';

interface FaultCategoryOption {
  id: string;
  name: string;
  code: string;
  status: 'active' | 'inactive';
}

interface FaultComponentOption {
  id: string;
  category_id: string;
  name: string;
  code: string;
  status: 'active' | 'inactive';
}

interface FaultOptionsResponse {
  success: boolean;
  data: {
    categories: FaultCategoryOption[];
    components: FaultComponentOption[];
  };
}

interface FaultMutationResponse {
  success: boolean;
  data: {
    fault: {
      id: string;
    };
  };
}

interface ReportFaultProps {
  currentUser: SessionUser | null;
  activeAssignment: DriverActiveAssignment | null;
}

interface FaultFormState {
  category_id: string;
  component_id: string;
  severity: FaultSeverity;
  description: string;
  photos: string[];
}

const initialFormState: FaultFormState = {
  category_id: '',
  component_id: '',
  severity: 'medium',
  description: '',
  photos: [],
};

function formatDateTime(value: Date) {
  return value.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

function CategorySvgIcon({ categoryName }: { categoryName: string }) {
  const commonProps = {
    viewBox: '0 0 48 48',
    fill: 'none',
    xmlns: 'http://www.w3.org/2000/svg',
    className: 'h-9 w-9',
  };

  switch (categoryName.toLowerCase()) {
    case 'engine':
      return (
        <svg {...commonProps}>
          <rect x="10" y="16" width="28" height="16" rx="4" stroke="currentColor" strokeWidth="2.4" />
          <path d="M16 16V12M32 16V12M14 32V36M34 32V36M8 22H10M38 22H40M18 22H30M20 26H28" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
          <circle cx="24" cy="24" r="3.5" stroke="currentColor" strokeWidth="2.4" />
        </svg>
      );
    case 'electrical':
      return (
        <svg {...commonProps}>
          <rect x="12" y="14" width="24" height="20" rx="4" stroke="currentColor" strokeWidth="2.4" />
          <path d="M18 20H30M18 26H26M20 10V14M28 10V14M18 34V38M30 34V38" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
          <path d="M24 18L20.5 24H25L22 30" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case 'transmission':
      return (
        <svg {...commonProps}>
          <path d="M16 12V34M16 14H28C31.3137 14 34 16.6863 34 20C34 23.3137 31.3137 26 28 26H20" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
          <circle cx="16" cy="36" r="3" stroke="currentColor" strokeWidth="2.4" />
          <circle cx="16" cy="12" r="3" fill="currentColor" />
          <circle cx="28" cy="14" r="2.5" fill="currentColor" />
          <circle cx="28" cy="26" r="2.5" fill="currentColor" />
        </svg>
      );
    case 'suspension':
      return (
        <svg {...commonProps}>
          <path d="M16 11V20M32 11V20M14 22L18 28L14 34M34 22L30 28L34 34M18 28H30" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M20 14H28M20 18H28" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
        </svg>
      );
    case 'brakes':
      return (
        <svg {...commonProps}>
          <circle cx="24" cy="24" r="12" stroke="currentColor" strokeWidth="2.4" />
          <circle cx="24" cy="24" r="4.5" stroke="currentColor" strokeWidth="2.4" />
          <path d="M31 17L35 21M17 31L13 27M18 16L14 20M30 32L34 28" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
        </svg>
      );
    case 'tyres':
      return (
        <svg {...commonProps}>
          <circle cx="24" cy="24" r="12" stroke="currentColor" strokeWidth="2.4" />
          <circle cx="24" cy="24" r="5" stroke="currentColor" strokeWidth="2.4" />
          <path d="M24 12V17M24 31V36M12 24H17M31 24H36M16.5 16.5L20 20M28 28L31.5 31.5M31.5 16.5L28 20M20 28L16.5 31.5" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
        </svg>
      );
    case 'cooling system':
      return (
        <svg {...commonProps}>
          <path d="M24 11C24 11 16 20 16 26C16 30.4183 19.5817 34 24 34C28.4183 34 32 30.4183 32 26C32 20 24 11 24 11Z" stroke="currentColor" strokeWidth="2.4" strokeLinejoin="round" />
          <path d="M13 20H8M40 20H35M15 14L11.5 10.5M33 14L36.5 10.5" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
          <path d="M21 27C21 28.6569 22.3431 30 24 30" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
        </svg>
      );
    case 'fuel system':
      return (
        <svg {...commonProps}>
          <path d="M16 12H28C30.2091 12 32 13.7909 32 16V34H16V12Z" stroke="currentColor" strokeWidth="2.4" strokeLinejoin="round" />
          <path d="M20 18H28M36 18V27C36 29.2091 34.2091 31 32 31H30M36 18L33 15" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M22 26H26" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
        </svg>
      );
    case 'body damage':
      return (
        <svg {...commonProps}>
          <path d="M10 28L14 20C15.2 17.6 17.6 16 20.3 16H27.7C30.4 16 32.8 17.6 34 20L38 28V32H34V30H14V32H10V28Z" stroke="currentColor" strokeWidth="2.4" strokeLinejoin="round" />
          <circle cx="17" cy="29" r="2.5" fill="currentColor" />
          <circle cx="31" cy="29" r="2.5" fill="currentColor" />
          <path d="M22 20L28 26" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
        </svg>
      );
    case 'interior':
      return (
        <svg {...commonProps}>
          <path d="M16 15V29C16 31.2091 17.7909 33 20 33H30V27H22V15H16Z" stroke="currentColor" strokeWidth="2.4" strokeLinejoin="round" />
          <path d="M22 15H28C30.2091 15 32 16.7909 32 19V33" stroke="currentColor" strokeWidth="2.4" strokeLinejoin="round" />
          <path d="M14 33H34" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
        </svg>
      );
    default:
      return (
        <svg {...commonProps}>
          <circle cx="24" cy="24" r="10" stroke="currentColor" strokeWidth="2.4" />
          <path d="M24 18V24L28 28" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
  }
}

export default function ReportFault({ currentUser, activeAssignment }: ReportFaultProps) {
  const [categories, setCategories] = useState<FaultCategoryOption[]>([]);
  const [components, setComponents] = useState<FaultComponentOption[]>([]);
  const [formState, setFormState] = useState<FaultFormState>(initialFormState);
  const [previewUrls, setPreviewUrls] = useState<string[]>([]);
  const [pageError, setPageError] = useState('');
  const [formError, setFormError] = useState('');
  const [successMessage, setSuccessMessage] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const assignedVehicleLabel = activeAssignment?.vehicle
    ? `${activeAssignment.vehicle.registration_number} ${activeAssignment.vehicle.make || ''} ${activeAssignment.vehicle.model || ''}`.trim()
    : 'No assigned vehicle';

  const availableComponents = useMemo(
    () => components.filter((component) => component.category_id === formState.category_id),
    [components, formState.category_id],
  );

  const selectedCategory = categories.find((category) => category.id === formState.category_id) || null;

  useEffect(() => {
    const loadOptions = async () => {
      setIsLoading(true);
      setPageError('');
      try {
        const response = await apiRequest<FaultOptionsResponse>('/faults/options');
        const nextCategories = Array.isArray(response.data?.categories) ? response.data.categories : [];
        const nextComponents = Array.isArray(response.data?.components) ? response.data.components : [];
        setCategories(nextCategories);
        setComponents(nextComponents);
        setFormState((current) => ({
          ...current,
          category_id: current.category_id || nextCategories[0]?.id || '',
        }));
      } catch (error) {
        if (error instanceof ApiRequestError) {
          setPageError(error.message);
        } else {
          setPageError('Unable to load fault reporting options right now.');
        }
      } finally {
        setIsLoading(false);
      }
    };

    void loadOptions();
  }, []);

  useEffect(() => {
    if (!formState.category_id) {
      return;
    }
    if (availableComponents.some((component) => component.id === formState.component_id)) {
      return;
    }
    setFormState((current) => ({
      ...current,
      component_id: availableComponents[0]?.id || '',
    }));
  }, [availableComponents, formState.category_id, formState.component_id]);

  const resetForm = () => {
    setFormError('');
    setSuccessMessage('');
    setPreviewUrls([]);
    setFormState({
      ...initialFormState,
      category_id: categories[0]?.id || '',
      component_id: '',
    });
  };

  const handlePhotoUpload = (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files || []);
    if (!files.length) {
      return;
    }

    Promise.all(
      files.map(
        (file) =>
          new Promise<string>((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(typeof reader.result === 'string' ? reader.result : '');
            reader.onerror = () => reject(new Error('Unable to read image file.'));
            reader.readAsDataURL(file);
          }),
      ),
    )
      .then((results) => {
        const nextPhotos = results.filter(Boolean);
        setPreviewUrls((current) => [...current, ...nextPhotos]);
        setFormState((current) => ({
          ...current,
          photos: [...current.photos, ...nextPhotos],
        }));
      })
      .catch(() => {
        setFormError('Unable to read one or more selected images.');
      });
  };

  const handleRemovePhoto = (index: number) => {
    setPreviewUrls((current) => current.filter((_, currentIndex) => currentIndex !== index));
    setFormState((current) => ({
      ...current,
      photos: current.photos.filter((_, currentIndex) => currentIndex !== index),
    }));
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!activeAssignment?.vehicle_id) {
      setFormError('You need an active assigned vehicle before reporting a fault.');
      return;
    }

    setIsSubmitting(true);
    setFormError('');
    setSuccessMessage('');

    try {
      await apiRequest<FaultMutationResponse>('/faults', {
        method: 'POST',
        body: JSON.stringify({
          vehicle_id: activeAssignment.vehicle_id,
          driver_id: currentUser?.id,
          category_id: formState.category_id,
          component_id: formState.component_id,
          severity: formState.severity,
          description: formState.description,
          photos: formState.photos,
        }),
      });
      setSuccessMessage('Fault report submitted successfully.');
      setPreviewUrls([]);
      setFormState({
        ...initialFormState,
        category_id: categories[0]?.id || '',
        component_id: '',
      });
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setFormError(error.message);
      } else {
        setFormError('Unable to submit fault report right now.');
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!activeAssignment) {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          You need an active vehicle assignment before you can report a fault.
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 p-4 sm:p-6">
      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-gradient-to-r from-[#0F172A] via-[#14213D] to-[#1E3A8A]">
        <div className="flex flex-col gap-6 px-5 py-6 sm:px-6 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-2xl">
            <div className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-blue-100">
              Fault Reporting
            </div>
            <h1 className="mt-4 text-2xl font-semibold text-white sm:text-3xl">Report Vehicle Fault</h1>
            <p className="mt-2 max-w-xl text-sm text-blue-100 sm:text-base">
              Log vehicle issues quickly with fleet-grade detail so admins can review, prioritize, and route them into maintenance.
            </p>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3 lg:min-w-[420px]">
            <HeaderStat label="Vehicle" value={activeAssignment.vehicle?.registration_number || 'Assigned'} />
            <HeaderStat label="Driver" value={currentUser?.full_name || 'Driver'} />
            <HeaderStat label="Reported" value={new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })} />
          </div>
        </div>
      </div>

      {pageError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {pageError}
        </div>
      )}

      <div className="rounded-2xl border border-gray-200 bg-white shadow-sm">
        <div className="border-b border-gray-200 px-6 py-4">
          <h2 className="text-lg font-semibold text-[#0F172A]">Fault Report Form</h2>
          <p className="mt-1 text-sm text-gray-600">
            Assigned vehicle, driver, and report time are captured automatically.
          </p>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center gap-3 px-6 py-16 text-gray-500">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span>Loading fault form...</span>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-6 px-6 py-5">
            {successMessage && (
              <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700">
                {successMessage}
              </div>
            )}

            {formError && (
              <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                {formError}
              </div>
            )}

            <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
              <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
                <div className="text-xs font-semibold uppercase tracking-wide text-gray-500">Assigned Vehicle</div>
                <div className="mt-1 text-sm font-medium text-[#0F172A]">{assignedVehicleLabel}</div>
              </div>
              <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
                <div className="text-xs font-semibold uppercase tracking-wide text-gray-500">Driver Name</div>
                <div className="mt-1 text-sm font-medium text-[#0F172A]">{currentUser?.full_name || 'Driver'}</div>
              </div>
              <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
                <div className="text-xs font-semibold uppercase tracking-wide text-gray-500">Date / Time</div>
                <div className="mt-1 text-sm font-medium text-[#0F172A]">{formatDateTime(new Date())}</div>
              </div>
            </div>

            <div>
              <label className="mb-3 block text-sm font-medium text-gray-700">Category</label>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
                {categories.map((category) => {
                  const isSelected = formState.category_id === category.id;
                  return (
                    <button
                      key={category.id}
                      type="button"
                      onClick={() =>
                        setFormState((current) => ({
                          ...current,
                          category_id: category.id,
                          component_id: '',
                        }))
                      }
                      className={`group relative flex min-h-[138px] flex-col items-start justify-between rounded-2xl border bg-white p-4 text-left transition-all ${
                        isSelected
                          ? 'border-[#2563EB] ring-2 ring-[#2563EB]/15'
                          : 'border-slate-200 hover:border-slate-300 hover:shadow-sm'
                      }`}
                    >
                      <div
                        className={`rounded-2xl p-3 transition-all ${
                          isSelected
                            ? 'bg-blue-50 text-[#2563EB]'
                            : 'bg-slate-100 text-slate-600 group-hover:bg-slate-200'
                        }`}
                      >
                        <CategorySvgIcon categoryName={category.name} />
                      </div>
                      <div className="mt-4 pr-8">
                        <div className={`text-sm font-semibold ${isSelected ? 'text-[#0F172A]' : 'text-slate-800'}`}>
                          {category.name}
                        </div>
                        <div className="mt-1 text-xs text-slate-500">Select fault area</div>
                      </div>
                      {isSelected && (
                        <div className="absolute right-3 top-3 flex h-6 w-6 items-center justify-center rounded-full bg-[#2563EB] text-white">
                          <CheckCircle className="h-4 w-4" />
                        </div>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div>
                <label className="mb-2 block text-sm font-medium text-gray-700">Component</label>
                <select
                  required
                  value={formState.component_id}
                  onChange={(event) =>
                    setFormState((current) => ({ ...current, component_id: event.target.value }))
                  }
                  className="w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                >
                  <option value="">Choose component...</option>
                  {availableComponents.map((component) => (
                    <option key={component.id} value={component.id}>
                      {component.name}
                    </option>
                  ))}
                </select>
                {selectedCategory && (
                  <div className="mt-2 text-xs text-gray-500">
                    Components shown for {selectedCategory.name}.
                  </div>
                )}
              </div>
            </div>

            <div>
              <label className="mb-2 block text-sm font-medium text-gray-700">Severity</label>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
                {(['low', 'medium', 'high', 'critical'] as FaultSeverity[]).map((severity) => (
                  <button
                    key={severity}
                    type="button"
                    onClick={() => setFormState((current) => ({ ...current, severity }))}
                    className={`rounded-xl border px-4 py-3 text-left transition-all ${
                      formState.severity === severity
                        ? severity === 'critical'
                          ? 'border-red-500 bg-red-50 text-red-900'
                          : severity === 'high'
                            ? 'border-orange-500 bg-orange-50 text-orange-900'
                            : severity === 'medium'
                              ? 'border-amber-500 bg-amber-50 text-amber-900'
                              : 'border-slate-500 bg-slate-50 text-slate-900'
                        : 'border-gray-200 bg-white text-gray-700 hover:border-gray-300'
                    }`}
                  >
                    <div className="font-semibold capitalize">{severity}</div>
                    <div className="mt-1 text-xs">
                      {severity === 'critical'
                        ? 'Stop operating if unsafe'
                        : severity === 'high'
                          ? 'Needs urgent admin review'
                          : severity === 'medium'
                            ? 'Should be checked soon'
                            : 'Minor issue to monitor'}
                    </div>
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label className="mb-2 block text-sm font-medium text-gray-700">Description</label>
              <textarea
                required
                value={formState.description}
                onChange={(event) =>
                  setFormState((current) => ({ ...current, description: event.target.value }))
                }
                className="min-h-[140px] w-full rounded-lg border border-gray-300 px-4 py-2.5 focus:border-transparent focus:ring-2 focus:ring-[#2563EB]"
                placeholder="Describe the fault, what happened, when it started, and any warning signs you noticed."
              />
            </div>

            <div>
              <label className="mb-2 block text-sm font-medium text-gray-700">Photos</label>
              <label className="flex cursor-pointer flex-col items-center justify-center rounded-2xl border border-dashed border-gray-300 bg-slate-50 px-4 py-8 text-center transition-all hover:border-[#2563EB] hover:bg-blue-50/30">
                <Upload className="mb-3 h-5 w-5 text-gray-500" />
                <span className="text-sm font-medium text-gray-700">Upload one or more images</span>
                <span className="mt-1 text-xs text-gray-500">Multiple photos supported</span>
                <input type="file" accept="image/*" multiple className="hidden" onChange={handlePhotoUpload} />
              </label>

              {previewUrls.length > 0 && (
                <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-4">
                  {previewUrls.map((photo, index) => (
                    <div key={`${photo}-${index}`} className="relative overflow-hidden rounded-xl border border-gray-200 bg-white">
                      <img src={photo} alt={`Fault preview ${index + 1}`} className="h-32 w-full object-cover" />
                      <button
                        type="button"
                        onClick={() => handleRemovePhoto(index)}
                        className="absolute right-2 top-2 rounded-full bg-black/70 p-1 text-white transition-all hover:bg-black"
                      >
                        <XCircle className="h-4 w-4" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {formState.severity === 'critical' && (
              <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                Critical faults notify the admin and owner. Stop using the vehicle immediately if the issue affects safety.
              </div>
            )}

            <div className="flex flex-col gap-3 border-t border-gray-200 pt-4 sm:flex-row sm:justify-end">
              <button
                type="button"
                onClick={resetForm}
                className="rounded-lg border border-gray-300 px-4 py-2.5 font-medium text-gray-700 transition-all hover:bg-gray-50"
              >
                Clear Form
              </button>
              <button
                type="submit"
                disabled={isSubmitting}
                className="flex items-center justify-center gap-2 rounded-lg bg-[#DC2626] px-4 py-2.5 font-medium text-white transition-all hover:bg-[#B91C1C] disabled:cursor-not-allowed disabled:opacity-70"
              >
                {isSubmitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <AlertTriangle className="h-4 w-4" />}
                {isSubmitting ? 'Submitting...' : 'Submit Fault Report'}
              </button>
            </div>
          </form>
        )}
      </div>

      <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        Safety first: for braking, steering, tyre blowout, or other dangerous faults, stop driving and contact the admin immediately.
      </div>
    </div>
  );
}

function HeaderStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/10 px-4 py-3 backdrop-blur-sm">
      <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-blue-100">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold text-white">{value}</div>
    </div>
  );
}
