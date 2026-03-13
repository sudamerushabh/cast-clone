"use client"

import { useCallback, useRef, useState } from "react"
import { getTransactionDetail, getTransactions } from "@/lib/api"
import type {
  TransactionDetailResponse,
  TransactionSummary,
} from "@/lib/types"
import { transactionToElements } from "@/lib/cytoscape-elements"
import type cytoscape from "cytoscape"

type ElementDefinition = cytoscape.ElementDefinition

interface UseTransactionsReturn {
  transactions: TransactionSummary[]
  selectedFqn: string | null
  transactionElements: ElementDefinition[]
  isLoading: boolean
  error: string | null
  loadTransactions: (projectId: string) => Promise<void>
  selectTransaction: (projectId: string, fqn: string) => Promise<void>
  clearSelection: () => void
}

export function useTransactions(): UseTransactionsReturn {
  const [transactions, setTransactions] = useState<TransactionSummary[]>([])
  const [selectedFqn, setSelectedFqn] = useState<string | null>(null)
  const [transactionElements, setTransactionElements] = useState<ElementDefinition[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const detailCache = useRef(new Map<string, TransactionDetailResponse>())

  const loadTransactions = useCallback(async (projectId: string) => {
    setIsLoading(true)
    setError(null)
    try {
      const resp = await getTransactions(projectId)
      setTransactions(resp.transactions)
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to load transactions"
      setError(message)
      setTransactions([])
    } finally {
      setIsLoading(false)
    }
  }, [])

  const selectTransaction = useCallback(
    async (projectId: string, fqn: string) => {
      setIsLoading(true)
      setError(null)
      setSelectedFqn(fqn)
      try {
        let detail = detailCache.current.get(fqn)
        if (!detail) {
          detail = await getTransactionDetail(projectId, fqn)
          detailCache.current.set(fqn, detail)
        }

        const elements = transactionToElements(detail, fqn)
        setTransactionElements(elements)
      } catch (err) {
        const message = err instanceof Error ? err.message : "Failed to load transaction detail"
        setError(message)
        setTransactionElements([])
      } finally {
        setIsLoading(false)
      }
    },
    []
  )

  const clearSelection = useCallback(() => {
    setSelectedFqn(null)
    setTransactionElements([])
    setError(null)
  }, [])

  return {
    transactions,
    selectedFqn,
    transactionElements,
    isLoading,
    error,
    loadTransactions,
    selectTransaction,
    clearSelection,
  }
}
