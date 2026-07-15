import { ReactNode } from 'react';
import Sidebar from './Sidebar';
import TopNav from './TopNav';
import type { UserRole } from '../../App';
import PortalBackButton from '../shared/PortalBackButton';
import { useActionableNotificationCount } from '../../lib/notification-count';
import { useResponsiveSidebar } from '../../lib/responsive-sidebar';

interface AdminLayoutProps {
  children: ReactNode;
  userRole: Extract<UserRole, 'owner' | 'admin' | 'dispatcher' | 'customer_service'>;
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
  const sidebar = useResponsiveSidebar();
  const { actionableCount, actionableCounts, moduleCounts } = useActionableNotificationCount();
  const handleNavigate = (section: string) => {
    onNavigate(section);
    if (typeof window !== 'undefined' && window.innerWidth < 1024) {
      sidebar.setMobileOpen(false);
    }
  };

  return (
    <div className="flex min-h-screen overflow-x-hidden bg-[#F8FAFC]">
      <Sidebar
        userRole={userRole}
        activeSection={activeSection}
        onNavigate={handleNavigate}
        isOpen={sidebar.mobileOpen}
        onToggle={sidebar.closeMobile}
        onLogout={onLogout}
        actionableCount={actionableCount}
        actionableBadgeTone={actionableCounts.highest_priority}
        moduleCounts={moduleCounts}
        isCollapsed={sidebar.isDesktop && !sidebar.expanded}
        isPinned={sidebar.pinned}
        onPinToggle={sidebar.togglePinned}
        onPointerEnter={sidebar.pointerEnter}
        onPointerLeave={sidebar.pointerLeave}
      />
      <div className={`flex min-w-0 flex-1 flex-col overflow-x-hidden transition-all duration-300 ${
        sidebar.pinned ? 'lg:ml-72' : 'lg:ml-20'
      }`}>
        <TopNav userRole={userRole} onMenuToggle={sidebar.toggle} onNavigate={handleNavigate} actionableCount={actionableCount} />
        <main className="flex-1 overflow-x-hidden overflow-y-auto">
          {showBackButton && onBack ? <PortalBackButton label={backLabel} onClick={onBack} /> : null}
          {children}
        </main>
      </div>
    </div>
  );
}
