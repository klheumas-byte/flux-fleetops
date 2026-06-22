import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  Bell,
  Check,
  CheckCircle,
  Clock,
  Info,
  Loader2,
  Trash2,
} from 'lucide-react';
import { apiRequest, ApiRequestError } from '../../lib/api';

type NotificationCategory =
  | 'all'
  | 'maintenance'
  | 'collection'
  | 'vehicle'
  | 'security'
  | 'revenue'
  | 'trip'
  | 'customer';
type NotificationPriority = 'critical' | 'high' | 'medium' | 'low';

interface NotificationRecord {
  id: string;
  title: string;
  message: string;
  category: Exclude<NotificationCategory, 'all'> | string;
  priority: NotificationPriority;
  is_read: boolean;
  created_at: string | null;
}

interface NotificationsResponse {
  success: boolean;
  data: {
    notifications: NotificationRecord[];
  };
}

function formatRelativeDate(value: string | null | undefined) {
  if (!value) return 'Just now';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

export default function DriverNotifications() {
  const [notifications, setNotifications] = useState<NotificationRecord[]>([]);
  const [activeCategory, setActiveCategory] = useState<NotificationCategory>('all');
  const [isLoading, setIsLoading] = useState(true);
  const [pageError, setPageError] = useState('');

  const loadNotifications = async () => {
    setIsLoading(true);
    setPageError('');
    try {
      const response = await apiRequest<NotificationsResponse>('/notifications');
      setNotifications(Array.isArray(response.data?.notifications) ? response.data.notifications : []);
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setPageError(error.message);
      } else {
        setPageError('Unable to load notifications right now.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void loadNotifications();
  }, []);

  const categories = [
    { id: 'all' as NotificationCategory, label: 'All' },
    { id: 'trip' as NotificationCategory, label: 'Trip' },
    { id: 'customer' as NotificationCategory, label: 'Customer' },
    { id: 'maintenance' as NotificationCategory, label: 'Maintenance' },
    { id: 'collection' as NotificationCategory, label: 'Collection' },
  ];

  const filteredNotifications = useMemo(
    () =>
      notifications.filter(
        (notification) => activeCategory === 'all' || notification.category === activeCategory,
      ),
    [activeCategory, notifications],
  );

  const unreadCount = notifications.filter((notification) => !notification.is_read).length;

  const mutateNotification = async (path: string, nextState: (items: NotificationRecord[]) => NotificationRecord[]) => {
    try {
      await apiRequest(path, { method: path.includes('/read') ? 'PATCH' : 'DELETE' });
      setNotifications((current) => nextState(current));
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setPageError(error.message);
      } else {
        setPageError('Unable to update notifications right now.');
      }
    }
  };

  const getPriorityColor = (priority: NotificationPriority) => {
    switch (priority) {
      case 'critical':
        return 'bg-red-100 text-red-800';
      case 'high':
        return 'bg-orange-100 text-orange-800';
      case 'medium':
        return 'bg-blue-100 text-blue-800';
      default:
        return 'bg-gray-100 text-gray-700';
    }
  };

  return (
    <div className="space-y-6 p-4 md:p-6">
      <div className="rounded-2xl bg-gradient-to-r from-[#0F172A] to-[#2563EB] p-6 text-white">
        <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <h1 className="text-2xl font-semibold">Driver Notifications</h1>
            <p className="mt-1 text-sm text-blue-100">Booking reminders and operational alerts land here.</p>
          </div>
          <button
            onClick={() =>
              void mutateNotification('/notifications/read-all', (items) =>
                items.map((notification) => ({ ...notification, is_read: true })),
              )
            }
            className="inline-flex items-center gap-2 rounded-xl bg-white/15 px-4 py-2.5 text-sm font-medium hover:bg-white/25"
          >
            <Check className="h-4 w-4" />
            Mark All Read
          </button>
        </div>
      </div>

      {pageError && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {pageError}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {categories.map((category) => (
          <button
            key={category.id}
            onClick={() => setActiveCategory(category.id)}
            className={`rounded-full px-4 py-2 text-sm font-medium ${
              activeCategory === category.id ? 'bg-[#2563EB] text-white' : 'bg-white text-gray-700'
            } border border-gray-200`}
          >
            {category.label}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <div className="rounded-2xl border border-gray-200 bg-white p-5">
          <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-xl bg-blue-100 text-blue-600">
            <Bell className="h-5 w-5" />
          </div>
          <div className="text-3xl font-semibold text-[#0F172A]">{notifications.length}</div>
          <div className="mt-1 text-sm text-gray-500">Total Notifications</div>
        </div>
        <div className="rounded-2xl border border-gray-200 bg-white p-5">
          <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-xl bg-amber-100 text-amber-600">
            <AlertTriangle className="h-5 w-5" />
          </div>
          <div className="text-3xl font-semibold text-[#0F172A]">{unreadCount}</div>
          <div className="mt-1 text-sm text-gray-500">Unread Alerts</div>
        </div>
        <div className="rounded-2xl border border-gray-200 bg-white p-5">
          <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-xl bg-emerald-100 text-emerald-600">
            <CheckCircle className="h-5 w-5" />
          </div>
          <div className="text-3xl font-semibold text-[#0F172A]">
            {notifications.filter((notification) => notification.is_read).length}
          </div>
          <div className="mt-1 text-sm text-gray-500">Read Alerts</div>
        </div>
      </div>

      <div className="rounded-2xl border border-gray-200 bg-white">
        {isLoading ? (
          <div className="flex min-h-[260px] items-center justify-center gap-3 text-gray-500">
            <Loader2 className="h-5 w-5 animate-spin" />
            <span>Loading notifications...</span>
          </div>
        ) : filteredNotifications.length ? (
          <div className="divide-y divide-gray-200">
            {filteredNotifications.map((notification) => (
              <div key={notification.id} className="px-5 py-4">
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div className="space-y-2">
                    <div className="flex items-center gap-2">
                      <div className={`rounded-full px-2.5 py-1 text-xs font-medium ${getPriorityColor(notification.priority)}`}>
                        {notification.priority}
                      </div>
                      {!notification.is_read && <span className="h-2 w-2 rounded-full bg-[#2563EB]"></span>}
                    </div>
                    <div className="text-base font-semibold text-[#0F172A]">{notification.title}</div>
                    <div className="text-sm text-gray-600">{notification.message}</div>
                    <div className="flex items-center gap-2 text-xs text-gray-500">
                      <Clock className="h-4 w-4" />
                      {formatRelativeDate(notification.created_at)}
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    {!notification.is_read && (
                      <button
                        onClick={() =>
                          void mutateNotification(`/notifications/${notification.id}/read`, (items) =>
                            items.map((item) =>
                              item.id === notification.id ? { ...item, is_read: true } : item,
                            ),
                          )
                        }
                        className="inline-flex items-center gap-1 rounded-lg bg-[#2563EB] px-3 py-2 text-xs font-medium text-white"
                      >
                        <Check className="h-3.5 w-3.5" />
                        Read
                      </button>
                    )}
                    <button
                      onClick={() =>
                        void mutateNotification(`/notifications/${notification.id}`, (items) =>
                          items.filter((item) => item.id !== notification.id),
                        )
                      }
                      className="rounded-lg p-2 text-gray-400 hover:bg-red-50 hover:text-red-600"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="px-6 py-16 text-center text-gray-500">
            <Info className="mx-auto mb-4 h-8 w-8 text-gray-300" />
            You're all caught up.
          </div>
        )}
      </div>
    </div>
  );
}
