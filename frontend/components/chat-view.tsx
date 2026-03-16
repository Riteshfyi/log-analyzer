"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { FileText } from "lucide-react"
import ReactMarkdown from "react-markdown"

interface ChatViewProps {
  chatResponse: string
}

export function ChatView({ chatResponse }: ChatViewProps) {
  if (!chatResponse) {
    return <div className="text-center py-8 text-gray-500">No chat response available</div>
  }

  return (

        <div className="prose prose-sm max-w-none text-black h-full p-4">
          <ReactMarkdown
            components={{
              h1: ({ children }) => <h1 className="text-2xl font-bold text-black mb-4">{children}</h1>,
              h2: ({ children }) => <h2 className="text-xl font-semibold text-black mb-3 mt-6">{children}</h2>,
              h3: ({ children }) => <h3 className="text-lg font-medium text-black mb-2 mt-4">{children}</h3>,
              p: ({ children }) => <p className="text-black mb-3 leading-relaxed">{children}</p>,
              ul: ({ children }) => <ul className="list-disc list-inside text-black mb-3 space-y-1">{children}</ul>,
              ol: ({ children }) => <ol className="list-decimal list-inside text-black mb-3 space-y-1">{children}</ol>,
              li: ({ children }) => <li className="text-black">{children}</li>,
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
            {chatResponse}
          </ReactMarkdown>
        </div>

  )
}
