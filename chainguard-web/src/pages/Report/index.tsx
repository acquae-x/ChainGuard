import { Navigate, useAccess } from '@umijs/max';

// 三张报表权限各不相同（老板只有 report:executive，供应链负责人只有 report:operation）。
// 静态 redirect 会把其中一方直接送进 403，这里按 access 落到本角色第一个可看的报表。
export default function ReportIndex() {
  const access = useAccess();
  if (access.canReportExecutive) return <Navigate to="/report/executive" replace />;
  if (access.canReportOperation) return <Navigate to="/report/operation" replace />;
  return <Navigate to="/report/response" replace />;
}
