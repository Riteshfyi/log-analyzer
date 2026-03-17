"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { FileText } from "lucide-react"
import ReactMarkdown from "react-markdown"

interface AnalysisViewProps {
  analysis: string
}

export function AnalysisView({ analysis }: AnalysisViewProps) {
  if (!analysis) {
    return <div className="text-center py-8 text-gray-500">No analysis available</div>
  }

  return (

        <div className="max-w-none text-black h-full p-4">
          <ReactMarkdown
            components={{
              h1: ({ children }) => <h1 className="text-lg font-semibold text-black mb-3">{children}</h1>,
              h2: ({ children }) => <h2 className="text-base font-semibold text-black mb-2 mt-5">{children}</h2>,
              h3: ({ children }) => <h3 className="text-sm font-medium text-black mb-1.5 mt-3">{children}</h3>,
              p: ({ children }) => {
                if (!children || (Array.isArray(children) && children.every((c: any) => c === null || c === undefined || c === ""))) return null
                return <p className="text-black mb-2 leading-relaxed text-sm">{children}</p>
              },
              ul: ({ children }) => <ul className="list-disc pl-5 text-black mb-2 space-y-0.5 text-sm">{children}</ul>,
              ol: ({ children }) => <ol className="list-decimal pl-5 text-black mb-2 space-y-0.5 text-sm">{children}</ol>,
              li: ({ children }) => {
                if (!children || (typeof children === "string" && !(children as string).trim())) return null
                return <li className="text-black text-sm">{children}</li>
              },
              hr: () => <div className="mt-2" />,
              strong: ({ children }) => <strong className="font-medium text-black">{children}</strong>,
              code: ({ children }) => (
                <code className="bg-gray-100 px-1 py-0.5 rounded text-black font-mono text-sm">{children}</code>
              ),
              pre: ({ children }) => (
                <pre className="bg-gray-100 p-3 rounded text-black font-mono text-sm overflow-x-auto mb-3">
                  {children}
                </pre>
              ),
              blockquote: ({ children }) => (
                <blockquote className="border-l-4 border-gray-300 pl-4 text-gray-700 italic mb-3">
                  {children}
                </blockquote>
              ),
            }}
          >
            {analysis.replace(/^[-*]\s*$/gm, "").replace(/\n{3,}/g, "\n\n")}
          </ReactMarkdown>
        </div>

  )
}
