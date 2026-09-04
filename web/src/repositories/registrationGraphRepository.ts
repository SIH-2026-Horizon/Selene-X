import { seleneApi, type ApiRequestOptions } from '@/services/api/client'
import type { ApiRegistrationGraph } from '@/services/api/contracts'
import type { RegistrationGraph } from '@/types/graph'

export const registrationGraphRepository = {
  async getGraph(
    centerId?: string,
    centerType?: 'run' | 'product',
    filters: { cursor?: string | null; limit?: number } = {},
    options?: ApiRequestOptions,
  ): Promise<RegistrationGraph> {
    const graph = await seleneApi.get<ApiRegistrationGraph>('registration-graphs', {
      ...options,
      query: { center_id: centerId, center_type: centerType, cursor: filters.cursor, limit: filters.limit ?? 100 },
    })
    return {
      nodes: graph.nodes,
      edges: graph.edges,
      nextCursor: graph.next_cursor,
      childCollectionsTruncated: graph.child_collections_truncated ?? [],
    }
  },
}
