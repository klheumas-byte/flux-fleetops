import { useState } from 'react';
import {
  Shield,
  Lock,
  Eye,
  Clock,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Activity,
  Users,
  Key,
  Smartphone,
  FileText,
  Globe,
  Monitor,
  ChevronDown,
  Download,
  Filter,
  Search,
  TrendingUp,
  UserX
} from 'lucide-react';

type SecurityTab = 'activity' | 'login-history' | 'audit-logs' | 'access-logs' | 'password-policy' | '2fa';

interface LoginAttempt {
  id: string;
  user: string;
  email: string;
  ipAddress: string;
  location: string;
  device: string;
  status: 'success' | 'failed' | 'blocked';
  timestamp: string;
  reason?: string;
}

interface AuditLog {
  id: string;
  user: string;
  action: string;
  resource: string;
  ipAddress: string;
  timestamp: string;
  status: 'success' | 'warning' | 'error';
  details: string;
}

interface ActiveSession {
  id: string;
  user: string;
  role: string;
  ipAddress: string;
  device: string;
  location: string;
  loginTime: string;
  lastActivity: string;
}

export default function Security() {
  const [activeTab, setActiveTab] = useState<SecurityTab>('activity');
  const [searchQuery, setSearchQuery] = useState('');
  const [dateRange, setDateRange] = useState('last-7-days');

  const loginHistory: LoginAttempt[] = [
    {
      id: '1',
      user: 'Admin User',
      email: 'admin@fluxfleet.com',
      ipAddress: '192.168.1.100',
      location: 'Accra, Ghana',
      device: 'Chrome on Windows',
      status: 'success',
      timestamp: '2 mins ago'
    },
    {
      id: '2',
      user: 'John Mensah',
      email: 'john@fluxfleet.com',
      ipAddress: '192.168.1.105',
      location: 'Kumasi, Ghana',
      device: 'Safari on iPhone',
      status: 'success',
      timestamp: '15 mins ago'
    },
    {
      id: '3',
      user: 'Unknown',
      email: 'admin@fluxfleet.com',
      ipAddress: '45.123.45.67',
      location: 'Lagos, Nigeria',
      device: 'Firefox on Linux',
      status: 'failed',
      timestamp: '1 hour ago',
      reason: 'Invalid password (3 attempts)'
    },
    {
      id: '4',
      user: 'Ama Boateng',
      email: 'ama@fluxfleet.com',
      ipAddress: '192.168.1.110',
      location: 'Accra, Ghana',
      device: 'Chrome on Android',
      status: 'success',
      timestamp: '3 hours ago'
    },
    {
      id: '5',
      user: 'Unknown',
      email: 'admin@fluxfleet.com',
      ipAddress: '89.234.56.78',
      location: 'London, UK',
      device: 'Chrome on Windows',
      status: 'blocked',
      timestamp: '5 hours ago',
      reason: 'Suspicious location'
    }
  ];

  const auditLogs: AuditLog[] = [
    {
      id: '1',
      user: 'Admin User',
      action: 'CREATE',
      resource: 'Vehicle Assignment',
      ipAddress: '192.168.1.100',
      timestamp: '10 mins ago',
      status: 'success',
      details: 'Assigned vehicle ABC-1234 to driver John Mensah'
    },
    {
      id: '2',
      user: 'Admin User',
      action: 'UPDATE',
      resource: 'Driver Profile',
      ipAddress: '192.168.1.100',
      timestamp: '30 mins ago',
      status: 'success',
      details: 'Updated phone number for Ama Boateng'
    },
    {
      id: '3',
      user: 'John Mensah',
      action: 'DELETE',
      resource: 'Trip Record',
      ipAddress: '192.168.1.105',
      timestamp: '1 hour ago',
      status: 'warning',
      details: 'Attempted to delete trip TRP-2001 (permission denied)'
    },
    {
      id: '4',
      user: 'Admin User',
      action: 'EXPORT',
      resource: 'Revenue Report',
      ipAddress: '192.168.1.100',
      timestamp: '2 hours ago',
      status: 'success',
      details: 'Exported monthly revenue report as PDF'
    },
    {
      id: '5',
      user: 'System',
      action: 'UPDATE',
      resource: 'Security Policy',
      ipAddress: '127.0.0.1',
      timestamp: '3 hours ago',
      status: 'success',
      details: 'Password policy updated: minimum 12 characters required'
    },
    {
      id: '6',
      user: 'Ama Boateng',
      action: 'VIEW',
      resource: 'Customer Data',
      ipAddress: '192.168.1.110',
      timestamp: '4 hours ago',
      status: 'success',
      details: 'Accessed customer profile for Kwame Asante'
    }
  ];

  const activeSessions: ActiveSession[] = [
    {
      id: '1',
      user: 'Admin User',
      role: 'Administrator',
      ipAddress: '192.168.1.100',
      device: 'Chrome on Windows 11',
      location: 'Accra, Ghana',
      loginTime: '2 hours ago',
      lastActivity: 'Just now'
    },
    {
      id: '2',
      user: 'John Mensah',
      role: 'Driver',
      ipAddress: '192.168.1.105',
      device: 'Safari on iPhone 14',
      location: 'Kumasi, Ghana',
      loginTime: '5 hours ago',
      lastActivity: '15 mins ago'
    },
    {
      id: '3',
      user: 'Ama Boateng',
      role: 'Driver',
      ipAddress: '192.168.1.110',
      device: 'Chrome on Android',
      location: 'Accra, Ghana',
      loginTime: '8 hours ago',
      lastActivity: '3 hours ago'
    }
  ];

  const failedLoginCount = loginHistory.filter(l => l.status === 'failed' || l.status === 'blocked').length;
  const activeSessionsCount = activeSessions.length;
  const recentActivitiesCount = auditLogs.length;

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'success':
        return 'bg-green-100 text-green-800 border-green-200';
      case 'failed':
      case 'error':
        return 'bg-red-100 text-red-800 border-red-200';
      case 'blocked':
        return 'bg-red-200 text-red-900 border-red-300';
      case 'warning':
        return 'bg-yellow-100 text-yellow-800 border-yellow-200';
      default:
        return 'bg-gray-100 text-gray-800 border-gray-200';
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'success':
        return <CheckCircle className="w-4 h-4" />;
      case 'failed':
      case 'error':
        return <XCircle className="w-4 h-4" />;
      case 'blocked':
        return <UserX className="w-4 h-4" />;
      case 'warning':
        return <AlertTriangle className="w-4 h-4" />;
      default:
        return null;
    }
  };

  const tabs = [
    { id: 'activity' as SecurityTab, label: 'User Activity', icon: Activity },
    { id: 'login-history' as SecurityTab, label: 'Login History', icon: Clock },
    { id: 'audit-logs' as SecurityTab, label: 'Audit Logs', icon: FileText },
    { id: 'access-logs' as SecurityTab, label: 'Access Logs', icon: Eye },
    { id: 'password-policy' as SecurityTab, label: 'Password Policy', icon: Lock },
    { id: '2fa' as SecurityTab, label: 'Two-Factor Auth', icon: Smartphone }
  ];

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-[#0F172A] flex items-center gap-3">
            <div className="w-10 h-10 bg-red-100 rounded-lg flex items-center justify-center">
              <Shield className="w-6 h-6 text-red-600" />
            </div>
            Security & Audit Center
          </h1>
          <p className="text-gray-600 mt-1">Monitor security events and access controls</p>
        </div>

        <div className="flex items-center gap-3">
          <button className="px-4 py-2.5 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 transition-all font-medium text-sm flex items-center gap-2">
            <Download className="w-4 h-4" />
            Export Logs
          </button>
        </div>
      </div>

      {/* Security Metrics */}
      <div className="grid grid-cols-3 gap-6">
        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <div className="flex items-center justify-between mb-4">
            <div className="w-12 h-12 bg-red-100 rounded-lg flex items-center justify-center">
              <AlertTriangle className="w-6 h-6 text-red-600" />
            </div>
            <span className="text-xs font-medium text-red-600 bg-red-50 px-2 py-1 rounded">Alert</span>
          </div>
          <div className="text-3xl font-bold text-[#0F172A] mb-1">{failedLoginCount}</div>
          <div className="text-sm text-gray-600 mb-3">Failed Login Attempts</div>
          <div className="flex items-center gap-1 text-xs text-red-600">
            <TrendingUp className="w-4 h-4" />
            <span>Last 24 hours</span>
          </div>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <div className="flex items-center justify-between mb-4">
            <div className="w-12 h-12 bg-green-100 rounded-lg flex items-center justify-center">
              <Users className="w-6 h-6 text-green-600" />
            </div>
            <span className="text-xs font-medium text-green-600 bg-green-50 px-2 py-1 rounded">Active</span>
          </div>
          <div className="text-3xl font-bold text-[#0F172A] mb-1">{activeSessionsCount}</div>
          <div className="text-sm text-gray-600 mb-3">Active Sessions</div>
          <div className="flex items-center gap-1 text-xs text-gray-600">
            <Monitor className="w-4 h-4" />
            <span>Currently online</span>
          </div>
        </div>

        <div className="bg-white rounded-xl border border-gray-200 p-6">
          <div className="flex items-center justify-between mb-4">
            <div className="w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center">
              <Activity className="w-6 h-6 text-blue-600" />
            </div>
            <span className="text-xs font-medium text-blue-600 bg-blue-50 px-2 py-1 rounded">Recent</span>
          </div>
          <div className="text-3xl font-bold text-[#0F172A] mb-1">{recentActivitiesCount}</div>
          <div className="text-sm text-gray-600 mb-3">Recent Activities</div>
          <div className="flex items-center gap-1 text-xs text-gray-600">
            <Clock className="w-4 h-4" />
            <span>Last hour</span>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
        <div className="border-b border-gray-200">
          <div className="flex overflow-x-auto">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.id;

              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex items-center gap-2 px-6 py-4 font-medium transition-all border-b-2 whitespace-nowrap ${
                    isActive
                      ? 'border-[#2563EB] text-[#2563EB] bg-blue-50'
                      : 'border-transparent text-gray-600 hover:text-gray-900 hover:bg-gray-50'
                  }`}
                >
                  <Icon className="w-5 h-5" />
                  {tab.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Tab Content */}
        <div className="p-6">
          {/* User Activity Tab */}
          {activeTab === 'activity' && (
            <div className="space-y-6">
              <div>
                <h2 className="text-lg font-semibold text-[#0F172A] mb-4">Active User Sessions</h2>
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead className="bg-gray-50 border-b border-gray-200">
                      <tr>
                        <th className="text-left px-4 py-3 text-xs font-semibold text-gray-700 uppercase">User</th>
                        <th className="text-left px-4 py-3 text-xs font-semibold text-gray-700 uppercase">Role</th>
                        <th className="text-left px-4 py-3 text-xs font-semibold text-gray-700 uppercase">IP Address</th>
                        <th className="text-left px-4 py-3 text-xs font-semibold text-gray-700 uppercase">Device</th>
                        <th className="text-left px-4 py-3 text-xs font-semibold text-gray-700 uppercase">Location</th>
                        <th className="text-left px-4 py-3 text-xs font-semibold text-gray-700 uppercase">Login Time</th>
                        <th className="text-left px-4 py-3 text-xs font-semibold text-gray-700 uppercase">Last Activity</th>
                        <th className="text-left px-4 py-3 text-xs font-semibold text-gray-700 uppercase">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-200">
                      {activeSessions.map((session) => (
                        <tr key={session.id} className="hover:bg-gray-50 transition-colors">
                          <td className="px-4 py-4">
                            <div className="font-medium text-[#0F172A]">{session.user}</div>
                          </td>
                          <td className="px-4 py-4">
                            <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-blue-100 text-blue-800 border border-blue-200">
                              {session.role}
                            </span>
                          </td>
                          <td className="px-4 py-4 text-gray-700 font-mono text-sm">{session.ipAddress}</td>
                          <td className="px-4 py-4 text-gray-700 text-sm">{session.device}</td>
                          <td className="px-4 py-4 text-gray-700 text-sm flex items-center gap-1">
                            <Globe className="w-4 h-4 text-gray-400" />
                            {session.location}
                          </td>
                          <td className="px-4 py-4 text-gray-700 text-sm">{session.loginTime}</td>
                          <td className="px-4 py-4 text-gray-700 text-sm">{session.lastActivity}</td>
                          <td className="px-4 py-4">
                            <button className="px-3 py-1.5 bg-red-100 text-red-700 rounded-lg hover:bg-red-200 transition-all text-xs font-medium">
                              Terminate
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* Login History Tab */}
          {activeTab === 'login-history' && (
            <div className="space-y-6">
              <div className="flex items-center gap-3">
                <div className="flex-1 relative">
                  <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search login history..."
                    className="w-full pl-10 pr-4 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-[#2563EB] focus:border-transparent transition-all"
                  />
                </div>
                <select
                  value={dateRange}
                  onChange={(e) => setDateRange(e.target.value)}
                  className="px-4 py-2.5 border border-gray-300 rounded-lg focus:ring-2 focus:ring-[#2563EB] focus:border-transparent"
                >
                  <option value="last-7-days">Last 7 Days</option>
                  <option value="last-30-days">Last 30 Days</option>
                  <option value="last-90-days">Last 90 Days</option>
                </select>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-gray-50 border-b border-gray-200">
                    <tr>
                      <th className="text-left px-4 py-3 text-xs font-semibold text-gray-700 uppercase">User</th>
                      <th className="text-left px-4 py-3 text-xs font-semibold text-gray-700 uppercase">IP Address</th>
                      <th className="text-left px-4 py-3 text-xs font-semibold text-gray-700 uppercase">Location</th>
                      <th className="text-left px-4 py-3 text-xs font-semibold text-gray-700 uppercase">Device</th>
                      <th className="text-left px-4 py-3 text-xs font-semibold text-gray-700 uppercase">Status</th>
                      <th className="text-left px-4 py-3 text-xs font-semibold text-gray-700 uppercase">Timestamp</th>
                      <th className="text-left px-4 py-3 text-xs font-semibold text-gray-700 uppercase">Details</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200">
                    {loginHistory.map((login) => (
                      <tr key={login.id} className="hover:bg-gray-50 transition-colors">
                        <td className="px-4 py-4">
                          <div>
                            <div className="font-medium text-[#0F172A]">{login.user}</div>
                            <div className="text-xs text-gray-500">{login.email}</div>
                          </div>
                        </td>
                        <td className="px-4 py-4 text-gray-700 font-mono text-sm">{login.ipAddress}</td>
                        <td className="px-4 py-4 text-gray-700 text-sm flex items-center gap-1">
                          <Globe className="w-4 h-4 text-gray-400" />
                          {login.location}
                        </td>
                        <td className="px-4 py-4 text-gray-700 text-sm">{login.device}</td>
                        <td className="px-4 py-4">
                          <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium border ${getStatusColor(login.status)}`}>
                            {getStatusIcon(login.status)}
                            {login.status.charAt(0).toUpperCase() + login.status.slice(1)}
                          </span>
                        </td>
                        <td className="px-4 py-4 text-gray-700 text-sm">{login.timestamp}</td>
                        <td className="px-4 py-4">
                          {login.reason && (
                            <div className="text-xs text-red-600">{login.reason}</div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Audit Logs Tab */}
          {activeTab === 'audit-logs' && (
            <div className="space-y-6">
              <div>
                <h2 className="text-lg font-semibold text-[#0F172A] mb-4">System Audit Trail</h2>
                <div className="space-y-3">
                  {auditLogs.map((log) => (
                    <div
                      key={log.id}
                      className="bg-gray-50 rounded-lg p-4 border border-gray-200 hover:bg-gray-100 transition-all"
                    >
                      <div className="flex items-start justify-between gap-4">
                        <div className="flex-1">
                          <div className="flex items-center gap-3 mb-2">
                            <span className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium border ${getStatusColor(log.status)}`}>
                              {getStatusIcon(log.status)}
                              {log.status.toUpperCase()}
                            </span>
                            <span className="px-2.5 py-1 bg-blue-100 text-blue-800 rounded text-xs font-semibold">
                              {log.action}
                            </span>
                            <span className="text-sm text-gray-600">{log.resource}</span>
                          </div>
                          <div className="text-sm text-gray-700 mb-2">{log.details}</div>
                          <div className="flex items-center gap-4 text-xs text-gray-500">
                            <span className="flex items-center gap-1">
                              <Users className="w-3 h-3" />
                              {log.user}
                            </span>
                            <span className="flex items-center gap-1">
                              <Globe className="w-3 h-3" />
                              {log.ipAddress}
                            </span>
                            <span className="flex items-center gap-1">
                              <Clock className="w-3 h-3" />
                              {log.timestamp}
                            </span>
                          </div>
                        </div>
                        <button className="p-2 hover:bg-white rounded-lg transition-all">
                          <Eye className="w-4 h-4 text-gray-500" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Password Policy Tab */}
          {activeTab === 'password-policy' && (
            <div className="space-y-6">
              <div className="bg-gradient-to-r from-red-50 to-orange-50 rounded-lg p-6 border border-red-200">
                <div className="flex items-start gap-4">
                  <div className="w-12 h-12 bg-red-600 rounded-lg flex items-center justify-center flex-shrink-0">
                    <Lock className="w-6 h-6 text-white" />
                  </div>
                  <div className="flex-1">
                    <h2 className="text-lg font-semibold text-[#0F172A] mb-2">Password Security Policy</h2>
                    <p className="text-sm text-gray-700">Enforce strong password requirements for all user accounts</p>
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-6">
                <div className="bg-white rounded-lg border border-gray-200 p-6">
                  <h3 className="text-sm font-semibold text-gray-900 mb-4">Current Requirements</h3>
                  <div className="space-y-3">
                    <div className="flex items-center gap-3">
                      <CheckCircle className="w-5 h-5 text-green-600" />
                      <span className="text-sm text-gray-700">Minimum 12 characters</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <CheckCircle className="w-5 h-5 text-green-600" />
                      <span className="text-sm text-gray-700">At least 1 uppercase letter</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <CheckCircle className="w-5 h-5 text-green-600" />
                      <span className="text-sm text-gray-700">At least 1 lowercase letter</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <CheckCircle className="w-5 h-5 text-green-600" />
                      <span className="text-sm text-gray-700">At least 1 number</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <CheckCircle className="w-5 h-5 text-green-600" />
                      <span className="text-sm text-gray-700">At least 1 special character</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <CheckCircle className="w-5 h-5 text-green-600" />
                      <span className="text-sm text-gray-700">Cannot reuse last 5 passwords</span>
                    </div>
                  </div>
                </div>

                <div className="bg-white rounded-lg border border-gray-200 p-6">
                  <h3 className="text-sm font-semibold text-gray-900 mb-4">Expiration & Rotation</h3>
                  <div className="space-y-4">
                    <div>
                      <label className="block text-xs font-medium text-gray-700 mb-2">Password Expiry</label>
                      <select className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-[#2563EB] focus:border-transparent">
                        <option>90 days</option>
                        <option>60 days</option>
                        <option>30 days</option>
                        <option>Never expire</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-700 mb-2">Account Lockout After</label>
                      <select className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-[#2563EB] focus:border-transparent">
                        <option>5 failed attempts</option>
                        <option>3 failed attempts</option>
                        <option>10 failed attempts</option>
                      </select>
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-700 mb-2">Lockout Duration</label>
                      <select className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-[#2563EB] focus:border-transparent">
                        <option>30 minutes</option>
                        <option>15 minutes</option>
                        <option>1 hour</option>
                        <option>Until admin unlocks</option>
                      </select>
                    </div>
                  </div>
                </div>
              </div>

              <div className="flex justify-end">
                <button className="px-6 py-2.5 bg-[#2563EB] text-white rounded-lg hover:bg-[#1d4ed8] transition-all font-medium">
                  Save Policy Changes
                </button>
              </div>
            </div>
          )}

          {/* Two-Factor Authentication Tab */}
          {activeTab === '2fa' && (
            <div className="space-y-6">
              <div className="bg-gradient-to-r from-blue-50 to-indigo-50 rounded-lg p-6 border border-blue-200">
                <div className="flex items-start gap-4">
                  <div className="w-12 h-12 bg-blue-600 rounded-lg flex items-center justify-center flex-shrink-0">
                    <Smartphone className="w-6 h-6 text-white" />
                  </div>
                  <div className="flex-1">
                    <h2 className="text-lg font-semibold text-[#0F172A] mb-2">Two-Factor Authentication (2FA)</h2>
                    <p className="text-sm text-gray-700">Add an extra layer of security to user accounts</p>
                  </div>
                  <div className="bg-green-100 px-3 py-1.5 rounded-full border border-green-200">
                    <span className="text-xs font-semibold text-green-700">Enabled</span>
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-6">
                <div className="bg-white rounded-lg border border-gray-200 p-6">
                  <h3 className="text-sm font-semibold text-gray-900 mb-4">Configuration</h3>
                  <div className="space-y-4">
                    <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                      <div>
                        <div className="font-medium text-sm text-gray-900">Require 2FA for Admins</div>
                        <div className="text-xs text-gray-600 mt-1">Mandatory for all admin accounts</div>
                      </div>
                      <div className="w-12 h-6 bg-green-500 rounded-full flex items-center px-1">
                        <div className="w-4 h-4 bg-white rounded-full ml-auto"></div>
                      </div>
                    </div>
                    <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                      <div>
                        <div className="font-medium text-sm text-gray-900">Require 2FA for Drivers</div>
                        <div className="text-xs text-gray-600 mt-1">Optional for driver accounts</div>
                      </div>
                      <div className="w-12 h-6 bg-gray-300 rounded-full flex items-center px-1">
                        <div className="w-4 h-4 bg-white rounded-full"></div>
                      </div>
                    </div>
                    <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                      <div>
                        <div className="font-medium text-sm text-gray-900">SMS Verification</div>
                        <div className="text-xs text-gray-600 mt-1">Send codes via SMS</div>
                      </div>
                      <div className="w-12 h-6 bg-green-500 rounded-full flex items-center px-1">
                        <div className="w-4 h-4 bg-white rounded-full ml-auto"></div>
                      </div>
                    </div>
                    <div className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                      <div>
                        <div className="font-medium text-sm text-gray-900">Authenticator App</div>
                        <div className="text-xs text-gray-600 mt-1">Google/Microsoft Authenticator</div>
                      </div>
                      <div className="w-12 h-6 bg-green-500 rounded-full flex items-center px-1">
                        <div className="w-4 h-4 bg-white rounded-full ml-auto"></div>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="bg-white rounded-lg border border-gray-200 p-6">
                  <h3 className="text-sm font-semibold text-gray-900 mb-4">User Enrollment Status</h3>
                  <div className="space-y-3">
                    <div className="flex items-center justify-between p-3 bg-green-50 rounded-lg border border-green-200">
                      <div>
                        <div className="font-medium text-sm text-gray-900">Admin User</div>
                        <div className="text-xs text-gray-600">admin@fluxfleet.com</div>
                      </div>
                      <span className="text-xs font-semibold text-green-700 bg-green-100 px-2 py-1 rounded">Enrolled</span>
                    </div>
                    <div className="flex items-center justify-between p-3 bg-green-50 rounded-lg border border-green-200">
                      <div>
                        <div className="font-medium text-sm text-gray-900">John Mensah</div>
                        <div className="text-xs text-gray-600">john@fluxfleet.com</div>
                      </div>
                      <span className="text-xs font-semibold text-green-700 bg-green-100 px-2 py-1 rounded">Enrolled</span>
                    </div>
                    <div className="flex items-center justify-between p-3 bg-yellow-50 rounded-lg border border-yellow-200">
                      <div>
                        <div className="font-medium text-sm text-gray-900">Ama Boateng</div>
                        <div className="text-xs text-gray-600">ama@fluxfleet.com</div>
                      </div>
                      <span className="text-xs font-semibold text-yellow-700 bg-yellow-100 px-2 py-1 rounded">Pending</span>
                    </div>
                    <div className="flex items-center justify-between p-3 bg-red-50 rounded-lg border border-red-200">
                      <div>
                        <div className="font-medium text-sm text-gray-900">Kofi Asante</div>
                        <div className="text-xs text-gray-600">kofi@fluxfleet.com</div>
                      </div>
                      <span className="text-xs font-semibold text-red-700 bg-red-100 px-2 py-1 rounded">Not Enrolled</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Access Logs Placeholder */}
          {activeTab === 'access-logs' && (
            <div className="text-center py-12">
              <div className="w-16 h-16 bg-gray-100 rounded-full flex items-center justify-center mx-auto mb-4">
                <Eye className="w-8 h-8 text-gray-400" />
              </div>
              <h3 className="text-lg font-semibold text-[#0F172A] mb-2">Access Logs</h3>
              <p className="text-gray-600">Detailed resource access logs coming soon</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
