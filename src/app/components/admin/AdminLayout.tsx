import { ReactNode, useState } from 'react';
import Sidebar from './Sidebar';
import TopNav from './TopNav';
import type { UserRole } from '../../App';
import PortalBackButton from '../shared/PortalBackButton';

interface AdminLayoutProps {
  children: ReactNode;
  userRole: Extract<UserRole, 'owner' | 'admin'>;
  activeSection?: string;
  onNavigate: (section: string) => void;
  onLogout: () => void;
  showBackButton?: boolean;
  backLabel?: string;
  onBack?: () => void;
}

export default function AdminLayout({
  children,
  userRole,
  activeSection,
  onNavigate,
  onLogout,
  showBackButton = false,
  backLabel = 'Back',
  onBack,
}: AdminLayoutProps) {
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const handleNavigate = (section: string) => {
    onNavigate(section);
    if (typeof window !== 'undefined' && window.innerWidth < 1024) {
      setSidebarOpen(false);
    }
  };

  return (
    <div className="flex min-h-screen overflow-x-hidden bg-[#F8FAFC]">
      <Sidebar
        userRole={userRole}
        activeSection={activeSection}
        onNavigate={handleNavigate}
        isOpen={sidebarOpen}
        onToggle={() => setSidebarOpen(!sidebarOpen)}
        onLogout={onLogout}
      />
      <div className={`flex min-w-0 flex-1 flex-col overflow-x-hidden transition-all duration-300 ${
        sidebarOpen ? 'lg:ml-64' : 'ml-0'
      }`}>
        <TopNav userRole={userRole} onMenuToggle={() => setSidebarOpen(!sidebarOpen)} />
        <main className="flex-1 overflow-x-hidden overflow-y-auto">
          {showBackButton && onBack ? <PortalBackButton label={backLabel} onClick={onBack} /> : null}
          {children}
        </main>
      </div>
    </div>
  );
}
