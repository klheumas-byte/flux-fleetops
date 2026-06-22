import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  Bell,
  Check,
  CheckCircle,
  Clock,
  Filter,
  Info,
  Loader2,
  Shield,
  Trash2,
  Wrench,
  XCircle,
} from 'lucide-react';
import { apiRequest, ApiRequestError } from '../../lib/api';

type NotificationCategory = 'all' | 'maintenance' | 'collection' | 'vehicle' | 'security' | 'revenue' | 'trip' | 'customer';
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

interface NotificationMutationResponse {
  success: boolean;
}

function formatRelativeDate(value: string | null | undefined) {
  if (!value) {
    return 'Just now';
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString();
}

export default function Notifications() {
  const [activeCategory, setActiveCategory] = useState<NotificationCategory>('all');
  const [notifications, setNotifications] = useState<NotificationRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [pageError, setPageError] = useState('');

  const loadNotifications = async () => {
    const pageLoadStartedAt = performance.now();
    setIsLoading(true);
    setPageError('');
    try {
      const response = await apiRequest<NotificationsResponse>('/notifications?limit=200', {
        cacheTtlMs: 10000,
      });
      setNotifications(Array.isArray(response.data?.notifications) ? response.data.notifications : []);
      console.info('[Flux Performance] Notifications page loaded', {
        durationMs: Number((performance.now() - pageLoadStartedAt).toFixed(2)),
      });
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
    { id: 'all' as NotificationCategory, label: 'All Notifications', icon: Bell, color: 'text-gray-700' },
    { id: 'maintenance' as NotificationCategory, label: 'Maintenance Alerts', icon: Wrench, color: 'text-red-600' },
    { id: 'collection' as NotificationCategory, label: 'Collection Alerts', icon: Bell, color: 'text-blue-600' },
    { id: 'vehicle' as NotificationCategory, label: 'Vehicle Alerts', icon: AlertTriangle, color: 'text-orange-600' },
    { id: 'security' as NotificationCategory, label: 'Security Alerts', icon: Shield, color: 'text-amber-600' },
    { id: 'revenue' as NotificationCategory, label: 'Revenue Alerts', icon: CheckCircle, color: 'text-green-600' },
    { id: 'trip' as NotificationCategory, label: 'Trip Alerts', icon: Info, color: 'text-indigo-600' },
    { id: 'customer' as NotificationCategory, label: 'Customer Alerts', icon: Info, color: 'text-pink-600' },
  ];

  const filteredNotifications = useMemo(
    () =>
      notifications.filter(
        (notification) => activeCategory === 'all' || notification.category === activeCategory,
      ),
    [activeCategory, notifications],
  );

  const { unreadCount, categoryUnreadCounts } = useMemo(() => {
    const counts = categories.reduce<Record<NotificationCategory, number>>((accumulator, category) => {
      accumulator[category.id] = 0;
      return accumulator;
    }, {} as Record<NotificationCategory, number>);

    let nextUnreadCount = 0;
    for (const notification of notifications) {
      if (!notification.is_read) {
        nextUnreadCount += 1;
        counts.all += 1;
        const category = notification.category as NotificationCategory;
        if (counts[category] !== undefined) {
          counts[category] += 1;
        }
      }
    }

    return { unreadCount: nextUnreadCount, categoryUnreadCounts: counts };
  }, [categories, notifications]);

  const markAsRead = async (notificationId: string) => {
    try {
      await apiRequest<NotificationMutationResponse>(`/notifications/${notificationId}/read`, {
        method: 'PATCH',
      });
      setNotifications((current) =>
        current.map((notification) =>
          notification.id === notificationId ? { ...notification, is_read: true } : notification,
        ),
      );
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setPageError(error.message);
      } else {
        setPageError('Unable to update that notification right now.');
      }
    }
  };

  const markAllAsRead = async () => {
    try {
      await apiRequest<NotificationMutationResponse>('/notifications/read-all', {
        method: 'PATCH',
      });
      setNotifications((current) => current.map((notification) => ({ ...notification, is_read: true })));
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setPageError(error.message);
      } else {
        setPageError('Unable to mark notifications as read right now.');
      }
    }
  };

  const deleteNotification = async (notificationId: string) => {
    try {
      await apiRequest<NotificationMutationResponse>(`/notifications/${notificationId}`, {
        method: 'DELETE',
      });
      setNotifications((current) => current.filter((notification) => notification.id !== notificationId));
    } catch (error) {
      if (error instanceof ApiRequestError) {
        setPageError(error.message);
      } else {
        setPageError('Unable to delete that notification right now.');
      }
    }
  };

  const getPriorityColor = (priority: NotificationPriority) => {
    switch (priority) {
      case 'critical':
        return 'bg-red-100 text-red-800 border-red-200';
      case 'high':
        return 'bg-orange-100 text-orange-800 border-orange-200';
      case 'medium':
        return 'bg-blue-100 text-blue-800 border-blue-200';
      default:
        return 'bg-gray-100 text-gray-800 border-gray-200';
    }
  };

  const getPriorityIcon = (priority: NotificationPriority) => {
    switch (priority) {
      case 'critical':
        return <XCircle className="w-4 h-4" />;
      case 'high':
        return <AlertTriangle className="w-4 h-4" />;
      case 'medium':
        return <Info className="w-4 h-4" />;
      default:
        return <CheckCircle className="w-4 h-4" />;
    }
  };

  const getCategoryIcon = (category: string) => {
    const selectedCategory = categories.find((item) => item.id === category);
    if (!selectedCategory) {
      return <Bell className="w-5 h-5" />;
    }
    const Icon = selectedCategory.icon;
    return <Icon className="w-5 h-5" />;
  };

  const getCategoryColor = (category: string) => {
    const selectedCategory = categories.find((item) => item.id === category);
    return selectedCategory?.color || 'text-gray-600';
  };

  return (
    <div className="h-full flex bg-[#F8FAFC]">
      <div className="w-80 bg-white border-r border-gray-200 flex flex-col">
        <div className="p-6 border-b border-gray-200">
          <div className="flex items-center justify-between mb-2">
            <h1 className="text-xl font-semibold text-[#0F172A]">Notifications</h1>
            {unreadCount > 0 && (
              <span className="px-2.5 py-1 bg-red-600 text-white text-xs font-semibold rounded-full">
                {unreadCount}
              </span>
            )}
          </div>
          <p className="text-sm text-gray-600">Live system alerts from your fleet workflow</p>
        </div>

        <div className="p-4 border-b border-gray-200 space-y-2">
          <button
            onClick={() => void markAllAsRead()}
            className="w-full px-4 py-2 bg-[#2563EB] text-white rounded-lg hover:bg-[#1d4ed8] transition-all font-medium text-sm flex items-center justify-center gap-2"
          >
            <Check className="w-4 h-4" />
            Mark All as Read
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          <div className="space-y-1">
            {categories.map((category) => {
              const Icon = category.icon;
              const isActive = activeCategory === category.id;
              const count = categoryUnreadCounts[category.id];

              return (
                <button
                  key={category.id}
                  onClick={() => setActiveCategory(category.id)}
                  className={`w-full flex items-center justify-between px-4 py-3 rounded-lg transition-all ${
                    isActive
                      ? 'bg-blue-50 border-2 border-[#2563EB]'
                      : 'hover:bg-gray-50 border-2 border-transparent'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <div className={`${isActive ? 'text-[#2563EB]' : category.color}`}>
                      <Icon className="w-5 h-5" />
                    </div>
                    <span className={`text-sm font-medium ${isActive ? 'text-[#2563EB]' : 'text-gray-700'}`}>
                      {category.label}
                    </span>
                  </div>
                  {count > 0 && (
                    <span
                      className={`px-2 py-0.5 rounded-full text-xs font-semibold ${
                        isActive ? 'bg-[#2563EB] text-white' : 'bg-red-100 text-red-700'
                      }`}
                    >
                      {count}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        <div className="p-4 border-t border-gray-200 bg-gray-50">
          <div className="grid grid-cols-2 gap-4 text-center">
            <div>
              <div className="text-2xl font-bold text-[#0F172A]">{unreadCount}</div>
              <div className="text-xs text-gray-600">Unread</div>
            </div>
            <div>
              <div className="text-2xl font-bold text-[#0F172A]">{notifications.length}</div>
              <div className="text-xs text-gray-600">Total</div>
            </div>
          </div>
        </div>
      </div>

      <div className="flex-1 flex flex-col">
        <div className="bg-white border-b border-gray-200 p-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-[#0F172A]">
                {categories.find((category) => category.id === activeCategory)?.label || 'All Notifications'}
              </h2>
              <p className="text-sm text-gray-600 mt-1">
                {filteredNotifications.length} notification{filteredNotifications.length !== 1 ? 's' : ''}
              </p>
            </div>

            <button className="px-3 py-2 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-all text-sm font-medium flex items-center gap-2">
              <Filter className="w-4 h-4" />
              Filter
            </button>
          </div>
        </div>

        {pageError && (
          <div className="m-6 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {pageError}
          </div>
        )}

        <div className="flex-1 overflow-y-auto bg-gray-50">
          {isLoading ? (
            <div className="p-6 space-y-3">
              {Array.from({ length: 6 }).map((_, index) => (
                <div key={index} className="rounded-xl border-2 border-gray-200 bg-white p-5">
                  <div className="flex items-start gap-4">
                    <div className="h-10 w-10 animate-pulse rounded-lg bg-gray-100" />
                    <div className="flex-1 space-y-3">
                      <div className="h-4 w-48 animate-pulse rounded bg-gray-100" />
                      <div className="h-3 w-full animate-pulse rounded bg-gray-100" />
                      <div className="h-3 w-2/3 animate-pulse rounded bg-gray-100" />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : filteredNotifications.length > 0 ? (
            <div className="p-6 space-y-3">
              {filteredNotifications.map((notification) => (
                <div
                  key={notification.id}
                  className={`bg-white rounded-xl border-2 transition-all hover:shadow-md ${
                    notification.is_read ? 'border-gray-200' : 'border-[#2563EB] shadow-sm'
                  }`}
                >
                  <div className="p-5">
                    <div className="flex items-start gap-4 mb-3">
                      <div
                        className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 ${
                          notification.is_read ? 'bg-gray-100' : 'bg-blue-50'
                        }`}
                      >
                        <div className={getCategoryColor(notification.category)}>{getCategoryIcon(notification.category)}</div>
                      </div>

                      <div className="flex-1 min-w-0">
                        <div className="flex items-start justify-between gap-3 mb-2">
                          <div className="flex-1">
                            <div className="flex items-center gap-2 mb-1">
                              <h3 className={`font-semibold ${notification.is_read ? 'text-gray-700' : 'text-[#0F172A]'}`}>
                                {notification.title}
                              </h3>
                              {!notification.is_read && <div className="w-2 h-2 bg-[#2563EB] rounded-full"></div>}
                            </div>
                            <p className={`text-sm ${notification.is_read ? 'text-gray-500' : 'text-gray-700'}`}>
                              {notification.message}
                            </p>
                          </div>

                          <span
                            className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium border flex-shrink-0 ${getPriorityColor(
                              notification.priority,
                            )}`}
                          >
                            {getPriorityIcon(notification.priority)}
                            {notification.priority.charAt(0).toUpperCase() + notification.priority.slice(1)}
                          </span>
                        </div>

                        <div className="flex items-center justify-between mt-3 pt-3 border-t border-gray-200">
                          <div className="flex items-center gap-2 text-xs text-gray-500">
                            <Clock className="w-4 h-4" />
                            <span>{formatRelativeDate(notification.created_at)}</span>
                          </div>

                          <div className="flex items-center gap-2">
                            {!notification.is_read && (
                              <button
                                onClick={() => void markAsRead(notification.id)}
                                className="px-3 py-1.5 bg-[#2563EB] text-white rounded-lg hover:bg-[#1d4ed8] transition-all text-xs font-medium flex items-center gap-1"
                              >
                                <Check className="w-3 h-3" />
                                Mark Read
                              </button>
                            )}
                            <button
                              onClick={() => void deleteNotification(notification.id)}
                              className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded transition-all"
                              title="Delete"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="h-full flex items-center justify-center">
              <div className="text-center">
                <div className="w-16 h-16 bg-gray-100 rounded-full flex items-center justify-center mx-auto mb-4">
                  <Bell className="w-8 h-8 text-gray-400" />
                </div>
                <h3 className="text-lg font-semibold text-gray-900 mb-2">No notifications</h3>
                <p className="text-gray-600">You're all caught up!</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
