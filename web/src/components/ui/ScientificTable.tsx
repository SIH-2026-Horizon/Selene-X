import { useRef } from 'react'
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from '@tanstack/react-table'
import { useVirtualizer } from '@tanstack/react-virtual'
import clsx from 'clsx'

interface ScientificTableProps<T> {
  data: T[]
  columns: ColumnDef<T, any>[]
  getRowId: (row: T) => string
  onRowClick?: (row: T) => void
  selectedId?: string | null
  virtualize?: boolean
  rowHeight?: number
  maxHeight?: number
}

export function ScientificTable<T>({
  data,
  columns,
  getRowId,
  onRowClick,
  selectedId,
  virtualize = false,
  rowHeight = 40,
  maxHeight = 480,
}: ScientificTableProps<T>) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getRowId: (row) => getRowId(row),
  })

  const rows = table.getRowModel().rows

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => rowHeight,
    overscan: 12,
    enabled: virtualize,
  })

  const virtualItems = virtualize ? virtualizer.getVirtualItems() : null

  return (
    <div
      ref={scrollRef}
      className="scrollbar-hairline overflow-auto border border-hairline"
      style={{ maxHeight: virtualize ? maxHeight : undefined }}
    >
      <table className="w-full border-collapse text-caption">
        <thead className="sticky top-0 z-10 bg-surface-soft">
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <th
                  key={header.id}
                  className="border-b border-hairline px-3 py-2 text-left text-micro font-medium uppercase tracking-wide text-mute"
                >
                  {header.isPlaceholder
                    ? null
                    : flexRender(header.column.columnDef.header, header.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody
          style={
            virtualize
              ? { display: 'block', position: 'relative', height: virtualizer.getTotalSize() }
              : undefined
          }
        >
          {(virtualItems ?? rows.map((_, i) => ({ index: i, key: i, start: 0 }))).map((virtualRow) => {
            const row = rows[virtualRow.index]
            const isSelected = selectedId != null && row.id === selectedId
            return (
              <tr
                key={row.id}
                onClick={() => onRowClick?.(row.original)}
                style={
                  virtualize
                    ? {
                        display: 'flex',
                        position: 'absolute',
                        top: 0,
                        left: 0,
                        width: '100%',
                        height: rowHeight,
                        transform: `translateY(${virtualRow.start}px)`,
                      }
                    : undefined
                }
                className={clsx(
                  'border-b border-hairline last:border-b-0',
                  onRowClick && 'cursor-pointer hover:bg-surface-soft',
                  isSelected && 'bg-surface-card',
                )}
              >
                {row.getVisibleCells().map((cell) => (
                  <td
                    key={cell.id}
                    className={clsx('px-3 py-2 tabular-nums', virtualize && 'flex flex-1 items-center')}
                  >
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
