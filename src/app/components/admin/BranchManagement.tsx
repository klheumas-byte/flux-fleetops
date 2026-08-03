import RbacConsole from './RbacConsole';

// Backward-compatible route target. Branch management now lives inside the
// unified Access Control Center rather than maintaining a second editor.
export default function BranchManagement() {
  return <RbacConsole view="branches" />;
}
