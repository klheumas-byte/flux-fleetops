import type { DriverDispatchJob } from './driver-api';

export type DriverDispatchSectionKey = 'upcoming' | 'active' | 'completed' | 'cancelled';

export function normalizeDriverDispatchStatus(job: DriverDispatchJob) {
  return String(job.status || 'assigned').trim().toLowerCase();
}

export function normalizeDriverDispatchWorkflowStatus(job: DriverDispatchJob) {
  return String(job.driver_workflow_status || job.status || 'assigned').trim().toLowerCase();
}

export function normalizeDriverDispatchResponseStatus(job: DriverDispatchJob) {
  return String(job.driver_response_status || 'pending').trim().toLowerCase();
}

export function getDriverDispatchActionState(job: DriverDispatchJob) {
  const status = normalizeDriverDispatchStatus(job);
  const workflowStatus = normalizeDriverDispatchWorkflowStatus(job);
  const responseStatus = normalizeDriverDispatchResponseStatus(job);
  const scheduleReady = job.schedule_valid !== false;

  return {
    status,
    workflowStatus,
    responseStatus,
    canAccept: status === 'assigned' && responseStatus === 'pending' && scheduleReady,
    canReject: status === 'assigned' && responseStatus === 'pending',
    canClarify: status === 'assigned' || status === 'accepted',
    canStart: status === 'accepted' && scheduleReady,
    canPause: status === 'in_progress' && !job.is_paused,
    canResume: status === 'in_progress' && Boolean(job.is_paused),
    canMarkGoodsLoaded: status === 'in_progress' && ['accepted', 'travelling_to_pickup'].includes(workflowStatus),
    canMarkStopCompleted: status === 'in_progress',
    canMarkDeliveryCompleted: status === 'in_progress',
    canEnd: status === 'in_progress',
  };
}

export function matchesDriverDispatchSection(job: DriverDispatchJob, section: DriverDispatchSectionKey) {
  const status = normalizeDriverDispatchStatus(job);
  if (section === 'upcoming') {
    return ['assigned', 'accepted', 'clarification_requested'].includes(status);
  }
  if (section === 'active') {
    return status === 'in_progress';
  }
  if (section === 'completed') {
    return status === 'completed';
  }
  return ['cancelled', 'rejected'].includes(status);
}
