import { useState } from 'react';
import { Eye, EyeOff, Lock, Mail, Shield, TrendingUp, MapPin, Users, DollarSign, Loader2 } from 'lucide-react';
import { apiRequest, ApiRequestError } from '../lib/api';
import type { AuthUser } from '../App';

const LOGO_URL = 'https://imagedelivery.net/h9fmMoa1o2c2P55TcWJGOg/42b18599-8959-49b5-c7a2-b78a9602ce00/public';

interface LoginProps {
  onLogin: (user: AuthUser) => void;
}

interface LoginResponse {
  success: boolean;
  message: string;
  data: {
    access_token: string;
    user: AuthUser;
  };
}

export default function Login({ onLogin }: LoginProps) {
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(false);
  const [emailOrPhone, setEmailOrPhone] = useState('owner@fluxfleet.com');
  const [password, setPassword] = useState('Owner@12345');
  const [isLoading, setIsLoading] = useState(false);
  const [loginError, setLoginError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoginError('');
    setIsLoading(true);

    try {
      const response = await apiRequest<LoginResponse>('/auth/login', {
        method: 'POST',
        body: JSON.stringify({
          identifier: emailOrPhone.trim(),
          password,
        }),
      });

      localStorage.setItem('flux_token', response.data.access_token);
      localStorage.setItem('flux_user', JSON.stringify(response.data.user));
      onLogin(response.data.user);
    } catch (error) {
      if (error instanceof ApiRequestError) {
        if (error.status === 0) {
          setLoginError('The backend or database is currently unavailable. Please try again shortly.');
        } else if (error.status === 503) {
          setLoginError('The backend is online, but the database is temporarily unavailable. Please try again shortly.');
        } else {
          setLoginError(error.message);
        }
      } else {
        setLoginError('Unable to sign in right now. Please try again.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#F8FAFC] flex">
      {/* Left Side - Login Form */}
      <div className="w-full lg:w-1/2 flex items-center justify-center p-8">
        <div className="w-full max-w-md">
          {/* Logo and Header */}
          <div className="mb-8">
            <div className="flex items-center gap-3 mb-6">
              <img
                src={LOGO_URL}
                alt="Flux FleetOps"
                className="w-14 h-14 rounded-full object-cover shadow-md flex-shrink-0"
              />
              <div>
                <h1 className="text-2xl font-semibold text-[#0F172A]">Flux FleetOps</h1>
                <p className="text-sm text-gray-500">Manage. Track. Optimize.</p>
              </div>
            </div>
            <h2 className="text-3xl font-semibold text-[#0F172A] mb-2">Welcome back</h2>
            <p className="text-gray-600">Sign in to access your fleet management dashboard</p>
          </div>

          {/* Login Form */}
          <form onSubmit={handleSubmit} className="space-y-5">
            {/* Email or Phone */}
            <div>
              <label htmlFor="emailOrPhone" className="block text-sm font-medium text-gray-700 mb-2">
                Email or Phone Number
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                  <Mail className="h-5 w-5 text-gray-400" />
                </div>
                <input
                  id="emailOrPhone"
                  type="text"
                  value={emailOrPhone}
                  onChange={(e) => setEmailOrPhone(e.target.value)}
                  className="block w-full pl-10 pr-3 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-[#2563EB] focus:border-transparent transition-all bg-white"
                  placeholder="owner@fluxfleet.com or +1234567890"
                  required
                />
              </div>
            </div>

            {/* Password */}
            <div>
              <label htmlFor="password" className="block text-sm font-medium text-gray-700 mb-2">
                Password
              </label>
              <div className="relative">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                  <Lock className="h-5 w-5 text-gray-400" />
                </div>
                <input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="block w-full pl-10 pr-12 py-3 border border-gray-300 rounded-lg focus:ring-2 focus:ring-[#2563EB] focus:border-transparent transition-all bg-white"
                  placeholder="Enter your password"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute inset-y-0 right-0 pr-3 flex items-center"
                >
                  {showPassword ? (
                    <EyeOff className="h-5 w-5 text-gray-400 hover:text-gray-600" />
                  ) : (
                    <Eye className="h-5 w-5 text-gray-400 hover:text-gray-600" />
                  )}
                </button>
              </div>
            </div>

            {loginError && (
              <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                {loginError}
              </div>
            )}

            {/* Remember Me & Forgot Password */}
            <div className="flex items-center justify-between">
              <label className="flex items-center">
                <input
                  type="checkbox"
                  checked={rememberMe}
                  onChange={(e) => setRememberMe(e.target.checked)}
                  className="w-4 h-4 text-[#2563EB] border-gray-300 rounded focus:ring-[#2563EB]"
                />
                <span className="ml-2 text-sm text-gray-700">Remember me</span>
              </label>
              <a href="#" className="text-sm text-[#2563EB] hover:text-[#1d4ed8] font-medium">
                Forgot password?
              </a>
            </div>

            {/* Login Button */}
            <button
              type="submit"
              disabled={isLoading}
              className="w-full bg-[#2563EB] text-white py-3 px-4 rounded-lg hover:bg-[#1d4ed8] focus:outline-none focus:ring-2 focus:ring-[#2563EB] focus:ring-offset-2 transition-all font-medium disabled:opacity-70 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            >
              {isLoading && <Loader2 className="w-5 h-5 animate-spin" />}
              {isLoading ? 'Signing in...' : 'Sign in to Dashboard'}
            </button>
          </form>

          <div className="mt-4 rounded-xl bg-[#EFF6FF] border border-[#BFDBFE] px-4 py-3">
            <p className="text-sm font-medium text-[#1D4ED8]">Single login flow</p>
            <p className="text-xs text-[#475569] mt-1">
              The system now detects whether the account is an owner, admin, or driver and opens the right dashboard automatically.
            </p>
          </div>

          {/* Security Features */}
          <div className="mt-8 pt-6 border-t border-gray-200">
            <div className="flex items-center justify-center gap-6 text-xs text-gray-500">
              <div className="flex items-center gap-1">
                <Shield className="w-4 h-4" />
                <span>2FA Ready</span>
              </div>
              <div className="flex items-center gap-1">
                <Lock className="w-4 h-4" />
                <span>SSL Encrypted</span>
              </div>
              <div className="flex items-center gap-1">
                <Shield className="w-4 h-4" />
                <span>Session Monitoring</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Right Side - Illustration */}
      <div className="hidden lg:flex lg:w-1/2 bg-gradient-to-br from-[#0F172A] via-[#1e293b] to-[#334155] p-12 items-center justify-center relative overflow-hidden">
        {/* Background Pattern */}
        <div className="absolute inset-0 opacity-10">
          <div className="absolute top-20 left-20 w-64 h-64 bg-[#2563EB] rounded-full blur-3xl"></div>
          <div className="absolute bottom-20 right-20 w-96 h-96 bg-[#10B981] rounded-full blur-3xl"></div>
        </div>

        {/* Content */}
        <div className="relative z-10 max-w-lg">
          {/* Logo Hero */}
          <div className="flex items-center gap-4 mb-10">
            <img
              src={LOGO_URL}
              alt="Flux FleetOps"
              className="w-20 h-20 rounded-full object-cover shadow-2xl border-2 border-white/20"
            />
            <div>
              <h2 className="text-3xl font-semibold text-white leading-tight">Flux FleetOps</h2>
              <p className="text-blue-300 text-sm mt-0.5">Manage. Track. Optimize.</p>
            </div>
          </div>
          <p className="text-lg text-gray-300 mb-12">
            Manage your entire fleet with real-time tracking, revenue analytics, and operational intelligence.
          </p>

          {/* Feature Grid */}
          <div className="grid grid-cols-2 gap-6">
            {/* Fleet Tracking */}
            <div className="bg-white/10 backdrop-blur-sm rounded-xl p-6 border border-white/20">
              <div className="w-12 h-12 bg-[#2563EB] rounded-lg flex items-center justify-center mb-4">
                <MapPin className="w-6 h-6 text-white" />
              </div>
              <h3 className="text-white font-medium mb-2">Live Tracking</h3>
              <p className="text-sm text-gray-300">Real-time GPS monitoring of all vehicles</p>
            </div>

            {/* Revenue Analytics */}
            <div className="bg-white/10 backdrop-blur-sm rounded-xl p-6 border border-white/20">
              <div className="w-12 h-12 bg-[#10B981] rounded-lg flex items-center justify-center mb-4">
                <TrendingUp className="w-6 h-6 text-white" />
              </div>
              <h3 className="text-white font-medium mb-2">Revenue Analytics</h3>
              <p className="text-sm text-gray-300">Track collections and performance</p>
            </div>

            {/* Driver Management */}
            <div className="bg-white/10 backdrop-blur-sm rounded-xl p-6 border border-white/20">
              <div className="w-12 h-12 bg-[#F59E0B] rounded-lg flex items-center justify-center mb-4">
                <Users className="w-6 h-6 text-white" />
              </div>
              <h3 className="text-white font-medium mb-2">Driver Management</h3>
              <p className="text-sm text-gray-300">Complete driver & guarantor records</p>
            </div>

            {/* Wallet System */}
            <div className="bg-white/10 backdrop-blur-sm rounded-xl p-6 border border-white/20">
              <div className="w-12 h-12 bg-[#EF4444] rounded-lg flex items-center justify-center mb-4">
                <DollarSign className="w-6 h-6 text-white" />
              </div>
              <h3 className="text-white font-medium mb-2">Digital Wallets</h3>
              <p className="text-sm text-gray-300">Secure driver wallet management</p>
            </div>
          </div>

          {/* Stats */}
          <div className="mt-12 flex items-center gap-8">
            <div>
              <div className="text-3xl font-semibold text-white">99.9%</div>
              <div className="text-sm text-gray-400">Uptime SLA</div>
            </div>
            <div>
              <div className="text-3xl font-semibold text-white">500K+</div>
              <div className="text-sm text-gray-400">Trips Managed</div>
            </div>
            <div>
              <div className="text-3xl font-semibold text-white">24/7</div>
              <div className="text-sm text-gray-400">Support</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
