import { useState } from 'react'

/** Matches the backend's shared `Page[T]` response shape (see docs/api/README.md). */
export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface PageParams {
  page: number
  page_size: number
}

const DEFAULT_PAGE_SIZE = 20

/**
 * Local (0-indexed for MUI X Data Grid, 1-indexed for the API) pagination
 * state shared by every list page, so page-size defaults and the
 * off-by-one translation live in exactly one place.
 */
export function usePaginationParams(initialPageSize = DEFAULT_PAGE_SIZE) {
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState(initialPageSize)

  return {
    page,
    pageSize,
    setPage,
    setPageSize,
    apiParams: { page: page + 1, page_size: pageSize } satisfies PageParams,
  }
}
