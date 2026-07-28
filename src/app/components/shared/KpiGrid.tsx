import type { ReactNode } from 'react';

export default function KpiGrid({ children, className = '' }: { children: ReactNode; className?: string }) {
  return (
    <div className={`grid grid-cols-2 gap-3 min-[480px]:grid-cols-3 md:grid-cols-4 md:gap-4 xl:grid-cols-6 ${className}`}>
      {children}
    </div>
  );
}

export const compactKpiCardClass =
  'min-w-0 h-full overflow-hidden rounded-xl border bg-white p-3 shadow-sm sm:p-4 [&_svg]:h-4 [&_svg]:w-4 sm:[&_svg]:h-5 sm:[&_svg]:w-5 [&_p]:break-words';
