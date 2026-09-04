import { lazy, Suspense } from 'react'
import { createBrowserRouter } from 'react-router-dom'
import { AppShell } from '@/components/shell/AppShell'
import { LoadingState } from '@/components/ui/LoadingState'
import { OverviewRoute } from '@/routes/overview/OverviewRoute'
import { RegisterRoute } from '@/routes/register/RegisterRoute'
import { JobsListRoute } from '@/routes/jobs/JobsListRoute'
import { JobDetailRoute } from '@/routes/jobs/JobDetailRoute'
import { CampaignsRoute } from '@/routes/campaigns/CampaignsRoute'
import { CampaignDetailRoute } from '@/routes/campaigns/CampaignDetailRoute'
import { ParametersRoute } from '@/routes/parameters/ParametersRoute'
import { ModelsRoute } from '@/routes/models/ModelsRoute'
import { AuditRoute } from '@/routes/audit/AuditRoute'
import { AdminRoute } from '@/routes/admin/AdminRoute'
import { UsersRoute } from '@/routes/admin/UsersRoute'
import { LoginRoute } from '@/routes/login/LoginRoute'
import { ProfileRoute } from '@/routes/profile/ProfileRoute'

// Route-level code splitting for the heaviest GIS/graph/imagery dependencies
// (OpenLayers, deck.gl, Sigma.js) — see spec performance guidance.
const CatalogRoute = lazy(() => import('@/routes/catalog/CatalogRoute').then((m) => ({ default: m.CatalogRoute })))
const ReviewRoute = lazy(() => import('@/routes/review/ReviewRoute').then((m) => ({ default: m.ReviewRoute })))
const KnowledgeRoute = lazy(() => import('@/routes/knowledge/KnowledgeRoute').then((m) => ({ default: m.KnowledgeRoute })))
const CraterDetailRoute = lazy(() =>
  import('@/routes/knowledge/CraterDetailRoute').then((m) => ({ default: m.CraterDetailRoute })),
)
const GraphDetailRoute = lazy(() => import('@/routes/graphs/GraphDetailRoute').then((m) => ({ default: m.GraphDetailRoute })))

function suspended(element: React.ReactNode) {
  return <Suspense fallback={<LoadingState label="Loading workspace" />}>{element}</Suspense>
}

export const router = createBrowserRouter([
  { path: '/login', element: <LoginRoute /> },
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <OverviewRoute /> },
      { path: 'catalog', element: suspended(<CatalogRoute />) },
      { path: 'catalog/:productId', element: suspended(<CatalogRoute />) },
      { path: 'register', element: <RegisterRoute /> },
      { path: 'jobs', element: <JobsListRoute /> },
      { path: 'jobs/:id', element: <JobDetailRoute /> },
      { path: 'jobs/:id/review', element: suspended(<ReviewRoute />) },
      { path: 'knowledge', element: suspended(<KnowledgeRoute />) },
      { path: 'knowledge/craters/:id', element: suspended(<CraterDetailRoute />) },
      { path: 'campaigns', element: <CampaignsRoute /> },
      { path: 'campaigns/:id', element: <CampaignDetailRoute /> },
      { path: 'graphs', element: suspended(<GraphDetailRoute />) },
      { path: 'graphs/:id', element: suspended(<GraphDetailRoute />) },
      { path: 'parameters', element: <ParametersRoute /> },
      { path: 'models', element: <ModelsRoute /> },
      { path: 'audit', element: <AuditRoute /> },
      { path: 'admin', element: <AdminRoute /> },
      { path: 'admin/users', element: <UsersRoute /> },
      { path: 'profile', element: <ProfileRoute /> },
    ],
  },
])
