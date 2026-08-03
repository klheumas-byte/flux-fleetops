import { useEffect, useRef, useState } from 'react';
import { MoreHorizontal, X } from 'lucide-react';

export type MobileNavItem = {
  id: string;
  label: string;
  icon: any;
  badge?: string;
};

type MobileNavGroup = {
  id: string;
  title: string;
  items: MobileNavItem[];
};

export default function MobileBottomNav({
  activeSection,
  primaryItems,
  groups,
  onNavigate,
  onLogout,
}: {
  activeSection: string;
  primaryItems: MobileNavItem[];
  groups: MobileNavGroup[];
  onNavigate: (section: string) => void;
  onLogout?: () => void;
}) {
  const [moreOpen, setMoreOpen] = useState(false);
  const activeRef = useRef<HTMLButtonElement>(null);
  const activeIsInMore = !primaryItems.some((item) => item.id === activeSection);

  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: 'nearest', inline: 'center' });
  }, [activeSection]);

  useEffect(() => {
    if (!moreOpen) return;
    const close = (event: KeyboardEvent) => event.key === 'Escape' && setMoreOpen(false);
    document.addEventListener('keydown', close);
    return () => document.removeEventListener('keydown', close);
  }, [moreOpen]);

  const navigate = (section: string) => {
    onNavigate(section);
    setMoreOpen(false);
  };

  return (
    <>
      <nav
        aria-label="Mobile navigation"
        className="fixed inset-x-0 bottom-0 z-50 border-t border-slate-200 bg-white/95 pb-[env(safe-area-inset-bottom)] shadow-[0_-8px_24px_rgba(15,23,42,0.08)] backdrop-blur lg:hidden"
      >
        <div className="scrollbar-none flex snap-x snap-mandatory overflow-x-auto overscroll-x-contain px-1">
          {primaryItems.map((item) => {
            const Icon = item.icon;
            const active = activeSection === item.id;
            return (
              <button
                key={item.id}
                ref={active ? activeRef : undefined}
                type="button"
                onClick={() => navigate(item.id)}
                aria-current={active ? 'page' : undefined}
                className={`relative flex min-h-16 min-w-[4.5rem] snap-center flex-col items-center justify-center gap-1 rounded-lg px-2 text-[11px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
                  active ? 'bg-blue-50 text-blue-700' : 'text-slate-500 active:bg-slate-100'
                }`}
              >
                <Icon className="h-5 w-5" />
                <span className="max-w-[4rem] truncate">{item.label}</span>
                {item.badge && <span className="absolute right-2 top-1 min-w-4 rounded-full bg-orange-500 px-1 text-[9px] leading-4 text-white">{item.badge}</span>}
              </button>
            );
          })}
          <button
            type="button"
            onClick={() => setMoreOpen(true)}
            aria-expanded={moreOpen}
            aria-current={activeIsInMore ? 'page' : undefined}
            className={`flex min-h-16 min-w-[4.5rem] snap-center flex-col items-center justify-center gap-1 rounded-lg px-2 text-[11px] font-medium ${(moreOpen || activeIsInMore) ? 'bg-blue-50 text-blue-700' : 'text-slate-500'}`}
          >
            <MoreHorizontal className="h-5 w-5" />
            More
          </button>
        </div>
      </nav>

      {moreOpen && (
        <div className="fixed inset-0 z-[60] lg:hidden" role="dialog" aria-modal="true" aria-label="More navigation">
          <button type="button" className="absolute inset-0 bg-slate-950/45" onClick={() => setMoreOpen(false)} aria-label="Close navigation" />
          <div className="absolute inset-x-0 bottom-0 max-h-[78dvh] overflow-y-auto rounded-t-2xl bg-white pb-[calc(1rem+env(safe-area-inset-bottom))] shadow-2xl">
            <div className="sticky top-0 z-10 flex items-center justify-between border-b bg-white px-4 py-3">
              <div><h2 className="font-semibold text-slate-900">More</h2><p className="text-xs text-slate-500">All pages available in this workspace</p></div>
              <button type="button" onClick={() => setMoreOpen(false)} className="rounded-lg p-2 text-slate-500 hover:bg-slate-100" aria-label="Close"><X className="h-5 w-5" /></button>
            </div>
            <div className="space-y-5 p-4">
              {groups.map((group) => (
                <section key={group.id}>
                  <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-slate-400">{group.title}</h3>
                  <div className="grid grid-cols-3 gap-2 min-[430px]:grid-cols-4">
                    {group.items.map((item) => {
                      const Icon = item.icon;
                      const active = activeSection === item.id;
                      return <button key={item.id} type="button" onClick={() => navigate(item.id)} className={`relative flex min-h-20 min-w-0 flex-col items-center justify-center gap-2 rounded-xl border p-2 text-center text-xs font-medium ${active ? 'border-blue-300 bg-blue-50 text-blue-700' : 'border-slate-200 text-slate-600'}`}><Icon className="h-5 w-5"/><span className="line-clamp-2">{item.label}</span>{item.badge && <span className="absolute right-1 top-1 rounded-full bg-orange-500 px-1.5 text-[9px] text-white">{item.badge}</span>}</button>;
                    })}
                  </div>
                </section>
              ))}
              {onLogout && <button type="button" onClick={onLogout} className="w-full rounded-xl border border-red-200 px-4 py-3 text-sm font-medium text-red-600">Logout</button>}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
