"use client"

import * as React from "react"
import { ChevronDown, Loader2, Route, Search } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { cn } from "@/lib/utils"
import type { TransactionSummary } from "@/lib/types"

interface TransactionSelectorProps {
  transactions: TransactionSummary[]
  selectedFqn: string | null
  isLoading: boolean
  onSelect: (fqn: string) => void
}

export function TransactionSelector({
  transactions,
  selectedFqn,
  isLoading,
  onSelect,
}: TransactionSelectorProps) {
  const [open, setOpen] = React.useState(false)
  const [filter, setFilter] = React.useState("")
  const containerRef = React.useRef<HTMLDivElement>(null)

  React.useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setOpen(false)
      }
    }
    if (open) {
      document.addEventListener("mousedown", handleClickOutside)
      return () => document.removeEventListener("mousedown", handleClickOutside)
    }
  }, [open])

  const filtered = React.useMemo(() => {
    if (!filter) return transactions
    const lowerFilter = filter.toLowerCase()
    return transactions.filter(
      (t) =>
        t.name.toLowerCase().includes(lowerFilter) ||
        t.fqn.toLowerCase().includes(lowerFilter) ||
        t.kind.toLowerCase().includes(lowerFilter)
    )
  }, [transactions, filter])

  const selectedTxn = transactions.find((t) => t.fqn === selectedFqn)

  return (
    <div ref={containerRef} className="relative">
      <Button
        variant="outline"
        size="default"
        className="w-72 justify-between gap-2"
        onClick={() => setOpen((prev) => !prev)}
        disabled={isLoading && transactions.length === 0}
      >
        <div className="flex items-center gap-2 truncate">
          {isLoading ? (
            <Loader2 className="size-3.5 animate-spin" />
          ) : (
            <Route className="size-3.5 shrink-0" />
          )}
          <span className="truncate">
            {selectedTxn ? selectedTxn.name : "Select transaction..."}
          </span>
        </div>
        <ChevronDown className="size-3.5 shrink-0 opacity-50" />
      </Button>

      {open ? (
        <div className="absolute left-0 top-full z-50 mt-1 w-96 rounded-md border bg-popover shadow-lg">
          <div className="border-b p-2">
            <div className="relative">
              <Search className="absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Filter transactions..."
                className="h-7 pl-7 text-xs"
                autoFocus
              />
            </div>
          </div>

          <ScrollArea className="max-h-72">
            {filtered.length === 0 ? (
              <div className="px-3 py-6 text-center text-xs text-muted-foreground">
                {transactions.length === 0
                  ? "No transactions discovered"
                  : "No matching transactions"}
              </div>
            ) : (
              <div className="p-1">
                {filtered.map((txn) => (
                  <button
                    key={txn.fqn}
                    className={cn(
                      "flex w-full items-start gap-2 rounded-sm px-2 py-1.5 text-left text-xs transition-colors hover:bg-accent",
                      txn.fqn === selectedFqn && "bg-accent"
                    )}
                    onClick={() => {
                      onSelect(txn.fqn)
                      setOpen(false)
                      setFilter("")
                    }}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium">{txn.name}</div>
                      <div className="mt-0.5 truncate text-muted-foreground">
                        {txn.kind} &middot; {txn.fqn}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            )}
          </ScrollArea>
        </div>
      ) : null}
    </div>
  )
}
