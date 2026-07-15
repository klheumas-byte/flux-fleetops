import NotificationCenter from '../shared/NotificationCenter';

export default function Notifications({ onNavigate }: { onNavigate?: (section: string) => void }) {
  return <NotificationCenter audience="admin" onNavigate={onNavigate} />;
}
