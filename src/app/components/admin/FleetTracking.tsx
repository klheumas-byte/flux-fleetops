import { useState } from 'react';
import {
  MapPin,
  Navigation,
  Truck,
  Users,
  Activity,
  TrendingUp,
  Zap,
  Circle,
  Route,
  Clock,
  DollarSign,
  Filter,
  Layers,
  Maximize2
} from 'lucide-react';

export default function FleetTracking() {
  const [selectedVehicle, setSelectedVehicle] = useState<string | null>('ABC-1234');
  const [mapView, setMapView] = useState<'standard' | 'satellite' | 'heat'>('standard');

  const vehicles = [
    {
      id: 'ABC-1234',
      driver: 'John Mensah',
      status: 'active',
      speed: 45,
      location: { lat: 5.6037, lng: -0.1870, name: 'Accra Central' },
      destination: 'Tema Station',
      tripProgress: 65,
      revenue: 145,
      distance: 24.5,
      eta: '12 min'
    },
    {
      id: 'XYZ-5678',
      driver: 'Mary Asante',
      status: 'active',
      speed: 38,
      location: { lat: 5.5560, lng: -0.1969, name: 'Kaneshie' },
      destination: 'Circle',
      tripProgress: 40,
      revenue: 95,
      distance: 18.2,
      eta: '18 min'
    },
    {
      id: 'DEF-9012',
      driver: 'Kwame Osei',
      status: 'idle',
      speed: 0,
      location: { lat: 5.6145, lng: -0.2055, name: 'Legon' },
      destination: null,
      tripProgress: 0,
      revenue: 320,
      distance: 45.8,
      eta: null
    },
    {
      id: 'GHI-3456',
      driver: 'Ama Adjei',
      status: 'active',
      speed: 52,
      location: { lat: 5.6500, lng: -0.1650, name: 'Airport Residential' },
      destination: 'Osu',
      tripProgress: 80,
      revenue: 210,
      distance: 32.1,
      eta: '8 min'
    },
    {
      id: 'JKL-7890',
      driver: 'Kofi Boateng',
      status: 'active',
      speed: 42,
      location: { lat: 5.5800, lng: -0.2200, name: 'Dansoman' },
      destination: 'Makola',
      tripProgress: 55,
      revenue: 175,
      distance: 28.4,
      eta: '15 min'
    },
    {
      id: 'MNO-2468',
      driver: 'Grace Owusu',
      status: 'idle',
      speed: 0,
      location: { lat: 5.6300, lng: -0.1750, name: 'East Legon' },
      destination: null,
      tripProgress: 0,
      revenue: 280,
      distance: 38.9,
      eta: null
    },
  ];

  const stats = [
    {
      label: 'Active Drivers',
      value: '4',
      total: '6',
      icon: Users,
      color: 'bg-green-500',
      change: '+2 from yesterday'
    },
    {
      label: 'Vehicles Online',
      value: '6',
      total: '6',
      icon: Truck,
      color: 'bg-blue-500',
      change: '100% fleet online'
    },
    {
      label: 'Trips In Progress',
      value: '4',
      icon: Activity,
      color: 'bg-amber-500',
      change: 'Real-time tracking'
    },
    {
      label: "Today's Distance",
      value: '188 km',
      icon: TrendingUp,
      color: 'bg-purple-500',
      change: '+12% vs yesterday'
    },
  ];

  const activeTrips = vehicles.filter(v => v.status === 'active');

  return (
    <div className="p-6 space-y-4">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Fleet Tracking</h1>
          <p className="text-gray-500 mt-1">Real-time vehicle and driver monitoring</p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 px-3 py-2 bg-white rounded-lg border border-gray-200">
            <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></div>
            <span className="text-sm font-medium text-gray-700">Live Tracking</span>
          </div>
          <button className="px-4 py-2 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 flex items-center gap-2">
            <Filter className="w-4 h-4" />
            Filters
          </button>
          <button className="px-4 py-2 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 flex items-center gap-2">
            <Layers className="w-4 h-4" />
            Layers
          </button>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {stats.map((stat, index) => {
          const Icon = stat.icon;
          return (
            <div key={index} className="bg-white rounded-lg border border-gray-200 p-5">
              <div className="flex items-start justify-between mb-3">
                <div className={`w-10 h-10 ${stat.color} rounded-lg flex items-center justify-center`}>
                  <Icon className="w-5 h-5 text-white" />
                </div>
              </div>
              <div className="text-2xl font-semibold text-gray-900 mb-1">
                {stat.value}
                {stat.total && <span className="text-sm text-gray-500 ml-1">/ {stat.total}</span>}
              </div>
              <div className="text-sm text-gray-600 mb-2">{stat.label}</div>
              <div className="text-xs text-gray-500">{stat.change}</div>
            </div>
          );
        })}
      </div>

      {/* Main Tracking Interface */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        {/* Map Area */}
        <div className="lg:col-span-3 bg-white rounded-lg border border-gray-200 overflow-hidden">
          {/* Map Controls */}
          <div className="p-4 border-b border-gray-200 flex items-center justify-between bg-gray-50">
            <div className="flex items-center gap-2">
              <button
                onClick={() => setMapView('standard')}
                className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
                  mapView === 'standard'
                    ? 'bg-[#2563EB] text-white'
                    : 'bg-white text-gray-700 hover:bg-gray-100'
                }`}
              >
                Map
              </button>
              <button
                onClick={() => setMapView('satellite')}
                className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
                  mapView === 'satellite'
                    ? 'bg-[#2563EB] text-white'
                    : 'bg-white text-gray-700 hover:bg-gray-100'
                }`}
              >
                Satellite
              </button>
              <button
                onClick={() => setMapView('heat')}
                className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
                  mapView === 'heat'
                    ? 'bg-[#2563EB] text-white'
                    : 'bg-white text-gray-700 hover:bg-gray-100'
                }`}
              >
                Heat Map
              </button>
            </div>
            <button className="p-2 hover:bg-gray-200 rounded-lg">
              <Maximize2 className="w-4 h-4 text-gray-600" />
            </button>
          </div>

          {/* Map Display */}
          <div className="relative h-[600px] bg-gradient-to-br from-blue-50 to-green-50">
            {/* Map Background Pattern */}
            <svg className="absolute inset-0 w-full h-full opacity-20" xmlns="http://www.w3.org/2000/svg">
              <defs>
                <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
                  <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#94a3b8" strokeWidth="0.5"/>
                </pattern>
              </defs>
              <rect width="100%" height="100%" fill="url(#grid)" />
            </svg>

            {/* Vehicle Markers */}
            {vehicles.map((vehicle, index) => (
              <div
                key={vehicle.id}
                className={`absolute cursor-pointer transition-all ${
                  selectedVehicle === vehicle.id ? 'z-20 scale-110' : 'z-10'
                }`}
                style={{
                  top: `${15 + index * 95}px`,
                  left: `${100 + index * 120}px`,
                }}
                onClick={() => setSelectedVehicle(vehicle.id)}
              >
                {/* Vehicle Marker */}
                <div className="relative">
                  <div
                    className={`w-12 h-12 rounded-full flex items-center justify-center shadow-lg ${
                      vehicle.status === 'active'
                        ? 'bg-green-500 animate-pulse'
                        : 'bg-gray-400'
                    }`}
                  >
                    <Truck className="w-6 h-6 text-white" />
                  </div>
                  {vehicle.status === 'active' && (
                    <div className="absolute -top-1 -right-1 w-4 h-4 bg-blue-500 rounded-full border-2 border-white flex items-center justify-center">
                      <Navigation className="w-2.5 h-2.5 text-white" />
                    </div>
                  )}
                  {/* Speed Indicator */}
                  {vehicle.speed > 0 && (
                    <div className="absolute -bottom-6 left-1/2 transform -translate-x-1/2 bg-white px-2 py-1 rounded shadow-md border border-gray-200 whitespace-nowrap">
                      <span className="text-xs font-medium text-gray-900">{vehicle.speed} km/h</span>
                    </div>
                  )}
                </div>

                {/* Info Popup */}
                {selectedVehicle === vehicle.id && (
                  <div className="absolute top-14 left-1/2 transform -translate-x-1/2 bg-white rounded-lg shadow-xl border border-gray-200 p-4 w-72 z-30">
                    <div className="flex items-start justify-between mb-3">
                      <div>
                        <div className="font-semibold text-gray-900">{vehicle.id}</div>
                        <div className="text-sm text-gray-600">{vehicle.driver}</div>
                      </div>
                      <div className={`px-2 py-1 rounded text-xs font-medium ${
                        vehicle.status === 'active'
                          ? 'bg-green-100 text-green-800'
                          : 'bg-gray-100 text-gray-800'
                      }`}>
                        {vehicle.status}
                      </div>
                    </div>

                    <div className="space-y-2 text-sm">
                      <div className="flex items-center gap-2">
                        <MapPin className="w-4 h-4 text-gray-400" />
                        <span className="text-gray-600">Location:</span>
                        <span className="font-medium text-gray-900">{vehicle.location.name}</span>
                      </div>

                      {vehicle.destination && (
                        <>
                          <div className="flex items-center gap-2">
                            <Route className="w-4 h-4 text-gray-400" />
                            <span className="text-gray-600">To:</span>
                            <span className="font-medium text-gray-900">{vehicle.destination}</span>
                          </div>

                          <div className="flex items-center gap-2">
                            <Clock className="w-4 h-4 text-gray-400" />
                            <span className="text-gray-600">ETA:</span>
                            <span className="font-medium text-gray-900">{vehicle.eta}</span>
                          </div>

                          <div className="w-full bg-gray-200 rounded-full h-2 mt-2">
                            <div
                              className="bg-[#2563EB] h-2 rounded-full transition-all"
                              style={{ width: `${vehicle.tripProgress}%` }}
                            ></div>
                          </div>
                        </>
                      )}

                      <div className="pt-2 border-t border-gray-200 grid grid-cols-2 gap-2">
                        <div>
                          <div className="text-xs text-gray-500">Distance Today</div>
                          <div className="font-semibold text-gray-900">{vehicle.distance} km</div>
                        </div>
                        <div>
                          <div className="text-xs text-gray-500">Revenue Today</div>
                          <div className="font-semibold text-gray-900">GH₵ {vehicle.revenue}</div>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* Route Line */}
                {vehicle.status === 'active' && vehicle.destination && (
                  <svg className="absolute top-0 left-0 pointer-events-none" style={{ width: '200px', height: '150px' }}>
                    <path
                      d={`M 24 24 Q 100 ${60 + index * 10} 180 120`}
                      stroke="#2563EB"
                      strokeWidth="2"
                      strokeDasharray="5,5"
                      fill="none"
                      opacity="0.6"
                    />
                  </svg>
                )}
              </div>
            ))}

            {/* Map Legend */}
            <div className="absolute bottom-4 left-4 bg-white rounded-lg shadow-lg border border-gray-200 p-4">
              <h4 className="text-sm font-semibold text-gray-900 mb-3">Legend</h4>
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <div className="w-3 h-3 bg-green-500 rounded-full"></div>
                  <span className="text-xs text-gray-600">Active Vehicle</span>
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-3 h-3 bg-gray-400 rounded-full"></div>
                  <span className="text-xs text-gray-600">Idle Vehicle</span>
                </div>
                <div className="flex items-center gap-2">
                  <div className="w-3 h-3 border-2 border-blue-500 rounded-full"></div>
                  <span className="text-xs text-gray-600">Route Path</span>
                </div>
              </div>
            </div>

            {/* Map Scale */}
            <div className="absolute bottom-4 right-4 bg-white rounded-lg shadow-lg border border-gray-200 px-3 py-2">
              <div className="text-xs text-gray-600">Scale: 1 km</div>
              <div className="w-20 h-1 bg-gray-800 mt-1"></div>
            </div>
          </div>
        </div>

        {/* Active Trips Sidebar */}
        <div className="lg:col-span-1">
          <div className="bg-white rounded-lg border border-gray-200 h-full overflow-hidden flex flex-col">
            <div className="p-4 border-b border-gray-200 bg-gray-50">
              <h3 className="text-lg font-semibold text-gray-900">Active Trips</h3>
              <p className="text-sm text-gray-500">{activeTrips.length} in progress</p>
            </div>

            <div className="flex-1 overflow-y-auto">
              {activeTrips.map((trip) => (
                <div
                  key={trip.id}
                  className={`p-4 border-b border-gray-200 cursor-pointer transition-colors ${
                    selectedVehicle === trip.id
                      ? 'bg-blue-50 border-l-4 border-l-[#2563EB]'
                      : 'hover:bg-gray-50'
                  }`}
                  onClick={() => setSelectedVehicle(trip.id)}
                >
                  <div className="flex items-start justify-between mb-2">
                    <div>
                      <div className="font-semibold text-gray-900 text-sm">{trip.id}</div>
                      <div className="text-xs text-gray-600">{trip.driver}</div>
                    </div>
                    <div className="flex items-center gap-1 text-green-600">
                      <Circle className="w-2 h-2 fill-current" />
                      <span className="text-xs font-medium">{trip.speed} km/h</span>
                    </div>
                  </div>

                  <div className="space-y-1.5 text-xs">
                    <div className="flex items-center gap-1.5">
                      <MapPin className="w-3 h-3 text-gray-400 flex-shrink-0" />
                      <span className="text-gray-900 truncate">{trip.location.name}</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      <Navigation className="w-3 h-3 text-blue-500 flex-shrink-0" />
                      <span className="text-gray-900 truncate">{trip.destination}</span>
                    </div>
                  </div>

                  <div className="mt-2 w-full bg-gray-200 rounded-full h-1.5">
                    <div
                      className="bg-[#2563EB] h-1.5 rounded-full"
                      style={{ width: `${trip.tripProgress}%` }}
                    ></div>
                  </div>

                  <div className="mt-2 flex items-center justify-between text-xs">
                    <div className="flex items-center gap-1 text-gray-500">
                      <Clock className="w-3 h-3" />
                      <span>ETA {trip.eta}</span>
                    </div>
                    <div className="flex items-center gap-1 text-gray-900 font-medium">
                      <DollarSign className="w-3 h-3" />
                      <span>GH₵ {trip.revenue}</span>
                    </div>
                  </div>
                </div>
              ))}

              {/* Idle Vehicles */}
              <div className="p-4 bg-gray-50">
                <h4 className="text-sm font-semibold text-gray-900 mb-3">Idle Vehicles</h4>
                <div className="space-y-2">
                  {vehicles.filter(v => v.status === 'idle').map((vehicle) => (
                    <div
                      key={vehicle.id}
                      className="p-3 bg-white rounded-lg border border-gray-200 cursor-pointer hover:border-gray-300"
                      onClick={() => setSelectedVehicle(vehicle.id)}
                    >
                      <div className="flex items-center justify-between">
                        <div>
                          <div className="text-sm font-medium text-gray-900">{vehicle.id}</div>
                          <div className="text-xs text-gray-600">{vehicle.driver}</div>
                        </div>
                        <div className="px-2 py-1 bg-gray-100 rounded text-xs font-medium text-gray-700">
                          Idle
                        </div>
                      </div>
                      <div className="mt-2 text-xs text-gray-500">
                        <MapPin className="w-3 h-3 inline mr-1" />
                        {vehicle.location.name}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Fleet Performance Summary */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <div className="flex items-center gap-3 mb-4">
            <div className="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center">
              <Route className="w-5 h-5 text-blue-600" />
            </div>
            <div>
              <h3 className="text-sm font-medium text-gray-600">Total Distance</h3>
              <p className="text-2xl font-semibold text-gray-900">188.4 km</p>
            </div>
          </div>
          <div className="text-sm text-gray-500">Across all active vehicles</div>
        </div>

        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <div className="flex items-center gap-3 mb-4">
            <div className="w-10 h-10 bg-green-100 rounded-lg flex items-center justify-center">
              <DollarSign className="w-5 h-5 text-green-600" />
            </div>
            <div>
              <h3 className="text-sm font-medium text-gray-600">Total Revenue</h3>
              <p className="text-2xl font-semibold text-gray-900">GH₵ 1,225</p>
            </div>
          </div>
          <div className="text-sm text-gray-500">Today's collections so far</div>
        </div>

        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <div className="flex items-center gap-3 mb-4">
            <div className="w-10 h-10 bg-amber-100 rounded-lg flex items-center justify-center">
              <Zap className="w-5 h-5 text-amber-600" />
            </div>
            <div>
              <h3 className="text-sm font-medium text-gray-600">Avg Speed</h3>
              <p className="text-2xl font-semibold text-gray-900">44 km/h</p>
            </div>
          </div>
          <div className="text-sm text-gray-500">Fleet average speed</div>
        </div>
      </div>
    </div>
  );
}
