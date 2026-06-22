interface AccessDeniedProps {
  title?: string;
  message?: string;
}

export default function AccessDenied({
  title = 'Access denied',
  message = 'You do not have permission to view this page.',
}: AccessDeniedProps) {
  return (
    <div className="p-6">
      <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
        <div className="font-semibold text-red-900">{title}</div>
        <div className="mt-1">{message}</div>
      </div>
    </div>
  );
}
