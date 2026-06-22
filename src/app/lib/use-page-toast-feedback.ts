import { useEffect, useRef } from 'react';
import { toast } from 'sonner';

export function usePageToastFeedback(errorMessage?: string, noticeMessage?: string) {
  const lastErrorRef = useRef('');
  const lastNoticeRef = useRef('');

  useEffect(() => {
    const nextError = (errorMessage || '').trim();
    if (!nextError || nextError === lastErrorRef.current) {
      return;
    }

    lastErrorRef.current = nextError;
    toast.error(nextError, {
      position: 'bottom-right',
      id: `page-error:${nextError}`,
    });
  }, [errorMessage]);

  useEffect(() => {
    const nextNotice = (noticeMessage || '').trim();
    if (!nextNotice || nextNotice === lastNoticeRef.current) {
      return;
    }

    lastNoticeRef.current = nextNotice;
    toast.success(nextNotice, {
      position: 'bottom-right',
      id: `page-notice:${nextNotice}`,
    });
  }, [noticeMessage]);
}
