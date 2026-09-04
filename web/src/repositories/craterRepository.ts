import { seleneApi, type ApiRequestOptions } from '@/services/api/client'
import type { ApiKnowledgeEntity, ApiSemanticGraph } from '@/services/api/contracts'
import type { Crater, CraterObservations } from '@/types/crater'
import { graphFromApi, knowledgeNodeFromApi } from './knowledgeRepository'

export interface CraterSearchPage {
  items: Crater[]
  nextCursor: string | null
}

export const craterRepository = {
  async listCraters(options?: ApiRequestOptions): Promise<Crater[]> {
    const page = await seleneApi.get<{ items: ApiKnowledgeEntity[]; next_cursor: string | null }>('knowledge/entities', {
      ...options,
      query: { entity_type: 'CRATER', limit: 100 },
    })
    return page.items.map(knowledgeNodeFromApi)
  },

  async getCrater(id: string, options?: ApiRequestOptions): Promise<Crater> {
    return knowledgeNodeFromApi(await seleneApi.get<ApiKnowledgeEntity>(`knowledge/craters/${encodeURIComponent(id)}`, options))
  },

  async getObservations(craterId: string, filters: { cursor?: string | null; limit?: number } = {}, options?: ApiRequestOptions): Promise<CraterObservations> {
    return graphFromApi(await seleneApi.get<ApiSemanticGraph>(`knowledge/craters/${encodeURIComponent(craterId)}/observations`, { ...options, query: { cursor: filters.cursor, limit: filters.limit ?? 50 } }))
  },

  /** Bounded transparent lexical lookup; the semantic API owns pagination. */
  async searchCraters(query: string, options?: ApiRequestOptions): Promise<CraterSearchPage> {
    const graph = await seleneApi.get<ApiSemanticGraph>('knowledge/query', {
      ...options,
      query: { query, entity_type: 'CRATER', limit: 10 },
    })
    return {
      items: graph.nodes.map(knowledgeNodeFromApi),
      nextCursor: graph.next_cursor,
    }
  },
}
