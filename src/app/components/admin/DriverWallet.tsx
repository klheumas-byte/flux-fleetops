import { useState } from 'react';
import {
  Wallet,
  TrendingUp,
  TrendingDown,
  DollarSign,
  Target,
  ArrowLeft,
  Download,
  Filter,
  Calendar,
  ArrowUpRight,
  ArrowDownRight,
  Plus,
  Minus,
  User,
  Phone,
  Mail,
  Truck,
  RefreshCw
} from 'lucide-react';
import { LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';

export default function DriverWallet() {
  const [dateFilter, setDateFilter] = useState('week');

  const driver = {
    id: 1,
    name: 'John Mensah',
    phone: '+233 24 123 4567',
    email: 'john.mensah@email.com',
    vehicle: 'ABC-1234',
    joinDate: '2025-01-15'
  };

  const summary = {
    weeklyTarget: 2500,
    amountPaid: 2180,
    outstandingBalance: 320,
    achievementPercentage: 87.2,
    currentWalletBalance: 1250
  };

  const previousWeek = {
    amountPaid: 1950,
    achievementPercentage: 78.0
  };

  const ledgerEntries = [
    {
      id: 1,
      date: '2026-06-02',
      time: '14:23',
      description: 'Trip Payment - Route 45',
      type: 'credit',
      debit: null,
      credit: 450,
      balance: 1250,
      reference: 'TXN-2026060200145'
    },
    {
      id: 2,
      date: '2026-06-02',
      time: '12:00',
      description: 'Fuel Purchase - Shell Station',
      type: 'debit',
      debit: 120,
      credit: null,
      balance: 800,
      reference: 'FUEL-2026060200132'
    },
    {
      id: 3,
      date: '2026-06-02',
      time: '10:15',
      description: 'Weekly Target Payment',
      type: 'debit',
      debit: 500,
      credit: null,
      balance: 920,
      reference: 'TARGET-2026060200118'
    },
    {
      id: 4,
      date: '2026-06-02',
      time: '08:30',
      description: 'Trip Payment - Route 23',
      type: 'credit',
      debit: null,
      credit: 380,
      balance: 1420,
      reference: 'TXN-2026060200095'
    },
    {
      id: 5,
      date: '2026-06-01',
      time: '18:45',
      description: 'Trip Payment - Route 67',
      type: 'credit',
      debit: null,
      credit: 290,
      balance: 1040,
      reference: 'TXN-2026060100289'
    },
    {
      id: 6,
      date: '2026-06-01',
      time: '16:20',
      description: 'Maintenance Fee',
      type: 'debit',
      debit: 85,
      credit: null,
      balance: 750,
      reference: 'MAINT-2026060100245'
    },
    {
      id: 7,
      date: '2026-06-01',
      time: '14:00',
      description: 'Trip Payment - Route 12',
      type: 'credit',
      debit: null,
      credit: 520,
      balance: 835,
      reference: 'TXN-2026060100198'
    },
    {
      id: 8,
      date: '2026-06-01',
      time: '11:30',
      description: 'Fuel Purchase - Total Station',
      type: 'debit',
      debit: 95,
      credit: null,
      balance: 315,
      reference: 'FUEL-2026060100156'
    },
    {
      id: 9,
      date: '2026-06-01',
      time: '09:00',
      description: 'Trip Payment - Route 89',
      type: 'credit',
      debit: null,
      credit: 410,
      balance: 410,
      reference: 'TXN-2026060100102'
    },
    {
      id: 10,
      date: '2026-05-31',
      time: '20:15',
      description: 'Weekly Target Payment',
      type: 'debit',
      debit: 500,
      credit: null,
      balance: 0,
      reference: 'TARGET-2026053100432'
    },
    {
      id: 11,
      date: '2026-05-31',
      time: '17:45',
      description: 'Trip Payment - Route 34',
      type: 'credit',
      debit: null,
      credit: 340,
      balance: 500,
      reference: 'TXN-2026053100387'
    },
    {
      id: 12,
      date: '2026-05-31',
      time: '15:20',
      description: 'Trip Payment - Route 56',
      type: 'credit',
      debit: null,
      credit: 280,
      balance: 160,
      reference: 'TXN-2026053100312'
    },
  ];

  const collectionHistory = [
    { date: 'Mon', collected: 420, target: 360 },
    { date: 'Tue', collected: 510, target: 360 },
    { date: 'Wed', collected: 380, target: 360 },
    { date: 'Thu', collected: 450, target: 360 },
    { date: 'Fri', collected: 490, target: 360 },
    { date: 'Sat', collected: 340, target: 360 },
    { date: 'Sun', collected: 280, target: 360 },
  ];

  const achievementTrend = [
    { week: 'W1', achievement: 82.5 },
    { week: 'W2', achievement: 85.3 },
    { week: 'W3', achievement: 78.2 },
    { week: 'W4', achievement: 87.2 },
  ];

  const calculateChange = (current: number, previous: number) => {
    const change = ((current - previous) / previous) * 100;
    return {
      value: Math.abs(change).toFixed(1),
      positive: change >= 0
    };
  };

  const totalCredit = ledgerEntries.reduce((sum, entry) => sum + (entry.credit || 0), 0);
  const totalDebit = ledgerEntries.reduce((sum, entry) => sum + (entry.debit || 0), 0);

  return (
    <div className="p-6 space-y-6">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <button className="p-2 hover:bg-gray-100 rounded-lg transition-colors">
            <ArrowLeft className="w-5 h-5 text-gray-600" />
          </button>
          <div>
            <h1 className="text-2xl font-semibold text-gray-900">Driver Wallet & Ledger</h1>
            <p className="text-gray-500 mt-1">Financial transactions and payment history</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <select
            value={dateFilter}
            onChange={(e) => setDateFilter(e.target.value)}
            className="px-4 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#2563EB] bg-white"
          >
            <option value="week">This Week</option>
            <option value="month">This Month</option>
            <option value="quarter">This Quarter</option>
            <option value="all">All Time</option>
          </select>
          <button className="px-4 py-2.5 border border-gray-300 rounded-lg hover:bg-gray-50 flex items-center gap-2">
            <Filter className="w-4 h-4" />
            Filter
          </button>
          <button className="px-4 py-2.5 border border-gray-300 rounded-lg hover:bg-gray-50 flex items-center gap-2">
            <RefreshCw className="w-4 h-4" />
            Refresh
          </button>
          <button className="px-4 py-2.5 bg-[#2563EB] text-white rounded-lg hover:bg-[#1d4ed8] flex items-center gap-2">
            <Download className="w-4 h-4" />
            Export
          </button>
        </div>
      </div>

      {/* Driver Info Card */}
      <div className="bg-gradient-to-r from-blue-600 to-purple-600 rounded-lg p-6 text-white">
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-4">
            <div className="w-16 h-16 bg-white rounded-full flex items-center justify-center text-2xl font-semibold text-blue-600">
              {driver.name.split(' ').map(n => n[0]).join('')}
            </div>
            <div>
              <h2 className="text-2xl font-semibold">{driver.name}</h2>
              <div className="flex items-center gap-4 mt-2 text-sm opacity-90">
                <span className="flex items-center gap-1.5">
                  <Truck className="w-4 h-4" />
                  {driver.vehicle}
                </span>
                <span className="flex items-center gap-1.5">
                  <Phone className="w-4 h-4" />
                  {driver.phone}
                </span>
                <span className="flex items-center gap-1.5">
                  <Mail className="w-4 h-4" />
                  {driver.email}
                </span>
              </div>
            </div>
          </div>
          <div className="text-right">
            <div className="text-sm opacity-90 mb-1">Current Wallet Balance</div>
            <div className="text-3xl font-semibold">GH₵ {summary.currentWalletBalance.toLocaleString()}</div>
            <div className="text-sm opacity-75 mt-1">Member since {driver.joinDate}</div>
          </div>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        {/* Weekly Target */}
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <div className="flex items-start justify-between mb-4">
            <div className="w-12 h-12 bg-blue-100 rounded-lg flex items-center justify-center">
              <Target className="w-6 h-6 text-blue-600" />
            </div>
          </div>
          <div className="text-3xl font-semibold text-gray-900 mb-2">
            ${summary.weeklyTarget.toLocaleString()}
          </div>
          <div className="text-sm text-gray-600">Weekly Target</div>
          <div className="text-xs text-gray-500 mt-2">Expected payment</div>
        </div>

        {/* Amount Paid */}
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <div className="flex items-start justify-between mb-4">
            <div className="w-12 h-12 bg-green-100 rounded-lg flex items-center justify-center">
              <DollarSign className="w-6 h-6 text-green-600" />
            </div>
            {(() => {
              const change = calculateChange(summary.amountPaid, previousWeek.amountPaid);
              return (
                <div className={`flex items-center gap-1 px-2 py-1 rounded ${
                  change.positive ? 'bg-green-50' : 'bg-red-50'
                }`}>
                  {change.positive ? (
                    <ArrowUpRight className="w-4 h-4 text-green-600" />
                  ) : (
                    <ArrowDownRight className="w-4 h-4 text-red-600" />
                  )}
                  <span className={`text-xs font-medium ${
                    change.positive ? 'text-green-600' : 'text-red-600'
                  }`}>
                    {change.value}%
                  </span>
                </div>
              );
            })()}
          </div>
          <div className="text-3xl font-semibold text-green-600 mb-2">
            ${summary.amountPaid.toLocaleString()}
          </div>
          <div className="text-sm text-gray-600">Amount Paid</div>
          <div className="text-xs text-gray-500 mt-2">Collected this week</div>
        </div>

        {/* Outstanding Balance */}
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <div className="flex items-start justify-between mb-4">
            <div className="w-12 h-12 bg-red-100 rounded-lg flex items-center justify-center">
              <Wallet className="w-6 h-6 text-red-600" />
            </div>
          </div>
          <div className="text-3xl font-semibold text-red-600 mb-2">
            ${summary.outstandingBalance.toLocaleString()}
          </div>
          <div className="text-sm text-gray-600">Outstanding Balance</div>
          <div className="text-xs text-gray-500 mt-2">Remaining payment</div>
        </div>

        {/* Achievement Percentage */}
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <div className="flex items-start justify-between mb-4">
            <div className="w-12 h-12 bg-purple-100 rounded-lg flex items-center justify-center">
              <TrendingUp className="w-6 h-6 text-purple-600" />
            </div>
            {(() => {
              const change = calculateChange(summary.achievementPercentage, previousWeek.achievementPercentage);
              return (
                <div className={`flex items-center gap-1 px-2 py-1 rounded ${
                  change.positive ? 'bg-green-50' : 'bg-red-50'
                }`}>
                  {change.positive ? (
                    <ArrowUpRight className="w-4 h-4 text-green-600" />
                  ) : (
                    <ArrowDownRight className="w-4 h-4 text-red-600" />
                  )}
                  <span className={`text-xs font-medium ${
                    change.positive ? 'text-green-600' : 'text-red-600'
                  }`}>
                    {change.value}%
                  </span>
                </div>
              );
            })()}
          </div>
          <div className="text-3xl font-semibold text-gray-900 mb-2">
            {summary.achievementPercentage}%
          </div>
          <div className="text-sm text-gray-600">Achievement</div>
          <div className="w-full bg-gray-200 rounded-full h-2 mt-3">
            <div
              className={`h-2 rounded-full ${
                summary.achievementPercentage >= 90 ? 'bg-green-500' :
                summary.achievementPercentage >= 75 ? 'bg-blue-500' :
                'bg-yellow-500'
              }`}
              style={{ width: `${summary.achievementPercentage}%` }}
            ></div>
          </div>
        </div>
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Collection History */}
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Collection History</h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={collectionHistory}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="date" stroke="#6b7280" />
              <YAxis stroke="#6b7280" />
              <Tooltip />
              <Legend />
              <Bar key="collected-bar-2" dataKey="collected" fill="#10B981" name="Collected" />
              <Bar key="target-bar-2" dataKey="target" fill="#94a3b8" name="Daily Target" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Achievement Trend */}
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Achievement Trend</h3>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={achievementTrend}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="week" stroke="#6b7280" />
              <YAxis stroke="#6b7280" domain={[0, 100]} />
              <Tooltip />
              <Legend />
              <Line key="achievement-line-2" type="monotone" dataKey="achievement" stroke="#2563EB" strokeWidth={3} name="Achievement %" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Transaction Ledger */}
      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <div className="p-6 border-b border-gray-200 flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">Transaction Ledger</h3>
            <p className="text-sm text-gray-500 mt-1">Complete record of all financial transactions</p>
          </div>
          <div className="flex items-center gap-4 text-sm">
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 bg-green-500 rounded"></div>
              <span className="text-gray-600">Total Credits: <span className="font-semibold text-green-600">GH₵ {totalCredit.toLocaleString()}</span></span>
            </div>
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 bg-red-500 rounded"></div>
              <span className="text-gray-600">Total Debits: <span className="font-semibold text-red-600">GH₵ {totalDebit.toLocaleString()}</span></span>
            </div>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="px-6 py-4 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                  Date & Time
                </th>
                <th className="px-6 py-4 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider">
                  Description
                </th>
                <th className="px-6 py-4 text-right text-xs font-semibold text-gray-600 uppercase tracking-wider">
                  Debit
                </th>
                <th className="px-6 py-4 text-right text-xs font-semibold text-gray-600 uppercase tracking-wider">
                  Credit
                </th>
                <th className="px-6 py-4 text-right text-xs font-semibold text-gray-600 uppercase tracking-wider">
                  Balance
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {ledgerEntries.map((entry) => (
                <tr key={entry.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex items-center gap-2">
                      <Calendar className="w-4 h-4 text-gray-400" />
                      <div>
                        <div className="text-sm font-medium text-gray-900">{entry.date}</div>
                        <div className="text-xs text-gray-500">{entry.time}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <div className={`w-8 h-8 rounded-full flex items-center justify-center ${
                        entry.type === 'credit' ? 'bg-green-100' : 'bg-red-100'
                      }`}>
                        {entry.type === 'credit' ? (
                          <Plus className="w-4 h-4 text-green-600" />
                        ) : (
                          <Minus className="w-4 h-4 text-red-600" />
                        )}
                      </div>
                      <div>
                        <div className="text-sm font-medium text-gray-900">{entry.description}</div>
                        <div className="text-xs text-gray-500">{entry.reference}</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-6 py-4 text-right whitespace-nowrap">
                    {entry.debit ? (
                      <span className="text-sm font-semibold text-red-600">
                        -${entry.debit.toLocaleString()}
                      </span>
                    ) : (
                      <span className="text-sm text-gray-400">-</span>
                    )}
                  </td>
                  <td className="px-6 py-4 text-right whitespace-nowrap">
                    {entry.credit ? (
                      <span className="text-sm font-semibold text-green-600">
                        +${entry.credit.toLocaleString()}
                      </span>
                    ) : (
                      <span className="text-sm text-gray-400">-</span>
                    )}
                  </td>
                  <td className="px-6 py-4 text-right whitespace-nowrap">
                    <span className={`text-sm font-semibold ${
                      entry.balance >= 0 ? 'text-gray-900' : 'text-red-600'
                    }`}>
                      ${entry.balance.toLocaleString()}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Table Footer */}
        <div className="px-6 py-4 border-t border-gray-200 flex items-center justify-between bg-gray-50">
          <div className="text-sm text-gray-600">
            Showing <span className="font-medium">{ledgerEntries.length}</span> transactions
          </div>
          <div className="flex items-center gap-2">
            <button className="px-3 py-1.5 border border-gray-300 rounded-lg hover:bg-white text-sm font-medium text-gray-700">
              Previous
            </button>
            <button className="px-3 py-1.5 bg-[#2563EB] text-white rounded-lg text-sm font-medium">
              1
            </button>
            <button className="px-3 py-1.5 border border-gray-300 rounded-lg hover:bg-white text-sm font-medium text-gray-700">
              2
            </button>
            <button className="px-3 py-1.5 border border-gray-300 rounded-lg hover:bg-white text-sm font-medium text-gray-700">
              Next
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
