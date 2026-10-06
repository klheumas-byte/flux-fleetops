import AdminAccountability from './AdminAccountability';

export default function DriverRemittances({ onNavigate }: { onNavigate?: (page: string) => void }) {
  return <AdminAccountability remittanceWorkspace onNavigate={onNavigate} />;
}
