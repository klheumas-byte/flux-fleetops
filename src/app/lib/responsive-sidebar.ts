import { useCallback, useEffect, useRef, useState } from 'react';

const PREFERENCE_KEY = 'flux_sidebar_mode';

export function useResponsiveSidebar() {
  const [isDesktop, setIsDesktop] = useState(() => typeof window !== 'undefined' && window.matchMedia('(min-width: 1024px)').matches);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [pinned, setPinned] = useState(() => typeof window === 'undefined' || localStorage.getItem(PREFERENCE_KEY) !== 'auto');
  const [hovered, setHovered] = useState(false);
  const collapseTimer = useRef<number | undefined>();

  useEffect(() => {
    const media = window.matchMedia('(min-width: 1024px)');
    const sync = () => setIsDesktop(media.matches);
    sync(); media.addEventListener('change', sync);
    return () => media.removeEventListener('change', sync);
  }, []);

  const setMode = useCallback((nextPinned: boolean) => {
    setPinned(nextPinned);
    localStorage.setItem(PREFERENCE_KEY, nextPinned ? 'pinned' : 'auto');
    if (nextPinned) setHovered(false);
  }, []);
  const closeMobile = useCallback(() => setMobileOpen(false), []);
  const pointerEnter = useCallback(() => {
    if (!isDesktop || pinned) return;
    window.clearTimeout(collapseTimer.current);
    setHovered(true);
  }, [isDesktop, pinned]);
  const pointerLeave = useCallback(() => {
    if (!isDesktop || pinned) return;
    window.clearTimeout(collapseTimer.current);
    collapseTimer.current = window.setTimeout(() => setHovered(false), 300);
  }, [isDesktop, pinned]);
  useEffect(() => () => window.clearTimeout(collapseTimer.current), []);

  return {
    isDesktop,
    mobileOpen,
    setMobileOpen,
    closeMobile,
    pinned,
    expanded: pinned || hovered,
    toggle: () => isDesktop ? setMode(!pinned) : setMobileOpen((open) => !open),
    togglePinned: () => setMode(!pinned),
    pointerEnter,
    pointerLeave,
  };
}
