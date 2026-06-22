import { ArrowLeft } from 'lucide-react';

interface PortalBackButtonProps {
  label: string;
  onClick: () => void;
}

export default function PortalBackButton({ label, onClick }: PortalBackButtonProps) {
  return (
    <div className="border-b border-gray-200 bg-white/85 px-4 py-3 backdrop-blur sm:px-6">
      <button
        type="button"
        onClick={onClick}
        className="inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-[#0F172A] transition-colors hover:bg-gray-50"
      >
        <ArrowLeft className="h-4 w-4" />
        {label}
      </button>
    </div>
  );
}
