import type { UserRole } from '../../App';
import CustomerWorkspace from '../customer/CustomerWorkspace';

interface CustomersProps {
  userRole: Extract<UserRole, 'owner' | 'admin'>;
}

export default function Customers({ userRole }: CustomersProps) {
  return <CustomerWorkspace portal={userRole} />;
}
