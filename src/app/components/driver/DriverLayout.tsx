import { ReactNode, useState } from 'react';
import DriverSidebar from './DriverSidebar';
import DriverTopNav from './DriverTopNav';
import type { SessionUser } from '../../lib/auth-session';
import type { DriverActiveAssignment } from '../../lib/driver-api';

interface DriverLayoutProps {
  children: ReactNode;
  activeSection?: string;
  onNavigate: (section: string) => void;
  onLogout: () => void;
  currentUser: SessionUser | null;
  activeAssignment: DriverActiveAssignment | null;
}

export default function DriverLayout({
  children,
  activeSection,
  onNavigate,
  onLogout,
  currentUser,
  activeAssignment,
}: DriverLayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const handleNavigate = (section: string) => {
    onNavigate(section);
    if (typeof window !== 'undefined' && window.innerWidth < 1024) {
      setSidebarOpen(false);
    }
  };

  return (
    <div className="flex min-h-screen overflow-x-hidden bg-[#F8FAFC]">
      <DriverSidebar
        currentUser={currentUser}
        activeAssignment={activeAssignment}
        activeSection={activeSection}
        onNavigate={handleNavigate}
        isOpen={sidebarOpen}
        onToggle={() => setSidebarOpen(!sidebarOpen)}
        onLogout={onLogout}
      />
      <div className={`flex min-w-0 flex-1 flex-col overflow-x-hidden transition-all duration-300 ${
        sidebarOpen ? 'lg:ml-64' : 'ml-0'
      }`}>
        <DriverTopNav
          currentUser={currentUser}
          activeAssignment={activeAssignment}
          onMenuToggle={() => setSidebarOpen(!sidebarOpen)}
        />
        <main className="flex-1 overflow-x-hidden overflow-y-auto">
          {children}
        </main>
      </div>
    </div>
  );
}
