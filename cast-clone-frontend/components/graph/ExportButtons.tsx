"use client"

import * as React from "react"
import { ImageIcon, FileJson, FileType } from "lucide-react"
import type cytoscape from "cytoscape"

import { Button } from "@/components/ui/button"

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  setTimeout(() => {
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }, 100)
}

function downloadDataUrl(dataUrl: string, filename: string) {
  const a = document.createElement("a")
  a.href = dataUrl
  a.download = filename
  document.body.appendChild(a)
  a.click()
  setTimeout(() => {
    document.body.removeChild(a)
  }, 100)
}

interface ExportButtonsProps {
  cy: cytoscape.Core | null
}

export function ExportButtons({ cy }: ExportButtonsProps) {
  function handleExportPng() {
    if (!cy) return
    const dataUrl = cy.png({ full: true, scale: 2, bg: "#ffffff" })
    downloadDataUrl(dataUrl, "graph-export.png")
  }

  function handleExportSvg() {
    if (!cy) return
    const svgContent = (cy as unknown as { svg: (opts: object) => string }).svg({
      full: true,
      bg: "#ffffff",
    })
    const blob = new Blob([svgContent], { type: "image/svg+xml;charset=utf-8" })
    downloadBlob(blob, "graph-export.svg")
  }

  function handleExportJson() {
    if (!cy) return
    const elements = cy.json().elements
    const json = JSON.stringify(elements, null, 2)
    const blob = new Blob([json], { type: "application/json" })
    downloadBlob(blob, "graph-export.json")
  }

  const disabled = !cy

  return (
    <div className="flex items-center gap-0.5">
      <Button
        variant="ghost"
        size="sm"
        className="size-7 p-0"
        onClick={handleExportPng}
        disabled={disabled}
        title="Export as PNG"
        aria-label="Export graph as PNG"
      >
        <ImageIcon className="size-4" />
      </Button>
      <Button
        variant="ghost"
        size="sm"
        className="size-7 p-0"
        onClick={handleExportSvg}
        disabled={disabled}
        title="Export as SVG"
        aria-label="Export graph as SVG"
      >
        <FileType className="size-4" />
      </Button>
      <Button
        variant="ghost"
        size="sm"
        className="size-7 p-0"
        onClick={handleExportJson}
        disabled={disabled}
        title="Export as JSON"
        aria-label="Export graph as JSON"
      >
        <FileJson className="size-4" />
      </Button>
    </div>
  )
}
