import { ReactNode } from 'react';
import DriverSidebar from './DriverSidebar';
import DriverTopNav from './DriverTopNav';
import type { SessionUser } from '../../lib/auth-session';
import type { DriverActiveAssignment } from '../../lib/driver-api';
import PortalBackButton from '../shared/PortalBackButton';
import { useActionableNotificationCount } from '../../lib/notification-count';
import { useResponsiveSidebar } from '../../lib/responsive-sidebar';

interface DriverLayoutProps {
  children: ReactNode;
  activeSection?: string;
  onNavigate: (section: string) => void;
  onLogout: () => void;
  currentUser: SessionUser | null;
  activeAssignment: DriverActiveAssignment | null;
  showBackButton?: boolean;
  backLabel?: string;
  onBack?: () => void;
}

export default function DriverLayout({
  children,
  activeSection,
  onNavigate,
  onLogout,
  currentUser,
  activeAssignment,
  showBackButton = false,
  backLabel = 'Back',
  onBack,
}: DriverLayoutProps) {
  const sidebar = useResponsiveSidebar();
  const { actionableCount, unreadCount, actionableCounts, moduleCounts } = useActionableNotificationCount();
  const handleNavigate = (section: string) => {
    onNavigate(section);
    if (typeof window !== 'undefined' && window.innerWidth < 1024) {
      sidebar.setMobileOpen(false);
    }
  };

  return (
    <div className="flex h-dvh overflow-hidden bg-[#F8FAFC]">
      <DriverSidebar
        currentUser={currentUser}
        activeAssignment={activeAssignment}
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
      <div className={`flex h-dvh min-w-0 flex-1 flex-col overflow-hidden transition-all duration-300 ${
        sidebar.pinned ? 'lg:ml-72' : 'lg:ml-20'
      }`}>
        <DriverTopNav
          currentUser={currentUser}
          activeAssignment={activeAssignment}
          onMenuToggle={sidebar.toggle}
          onNavigate={handleNavigate}
          activeSection={activeSection}
          unreadCount={unreadCount}
        />
        <main className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-y-contain pb-[calc(4rem+env(safe-area-inset-bottom))] lg:pb-0">
          {showBackButton && onBack ? <PortalBackButton label={backLabel} onClick={onBack} /> : null}
          {children}
        </main>
      </div>
    </div>
  );
}
