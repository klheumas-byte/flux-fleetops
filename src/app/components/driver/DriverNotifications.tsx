import NotificationCenter from '../shared/NotificationCenter';

export default function DriverNotifications({ onNavigate }: { onNavigate?: (section: string) => void }) {
  return <NotificationCenter audience="driver" onNavigate={onNavigate} />;
}
