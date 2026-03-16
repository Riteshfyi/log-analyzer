"use client"

import type React from "react"
import { useRef, useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Send, Square, Bot, User, Loader2 } from "lucide-react"
import ReactMarkdown from "react-markdown"

export interface ChatMessage {
  id: string
  role: "user" | "assistant"
  content: string
}

interface ChatPanelProps {
  messages: ChatMessage[]
  loading: boolean
  chatDisabled?: boolean
  onSendMessage: (message: string) => void
  onStop: () => void
}

const markdownComponents = {
  h1: ({ children }: any) => (
    <h1 className="text-xl font-bold text-black mb-3">{children}</h1>
  ),
  h2: ({ children }: any) => (
    <h2 className="text-lg font-semibold text-black mb-2 mt-4">{children}</h2>
  ),
  h3: ({ children }: any) => (
    <h3 className="text-base font-medium text-black mb-1.5 mt-3">{children}</h3>
  ),
  p: ({ children }: any) => (
    <p className="text-black mb-2 leading-relaxed text-sm">{children}</p>
  ),
  ul: ({ children }: any) => (
    <ul className="list-disc list-inside text-black mb-2 space-y-0.5 text-sm">{children}</ul>
  ),
  ol: ({ children }: any) => (
    <ol className="list-decimal list-inside text-black mb-2 space-y-0.5 text-sm">{children}</ol>
  ),
  li: ({ children }: any) => <li className="text-black text-sm">{children}</li>,
  code: ({ children, className }: any) => {
    const isBlock = className?.includes("language-")
    if (isBlock) {
      return (
        <code className="text-xs">{children}</code>
      )
    }
    return (
      <code className="bg-white/60 px-1 py-0.5 rounded text-black font-mono text-xs">
        {children}
      </code>
    )
  },
  pre: ({ children }: any) => (
    <pre className="bg-gray-200 p-3 rounded-lg text-black font-mono text-xs overflow-x-auto mb-2">
      {children}
    </pre>
  ),
  blockquote: ({ children }: any) => (
    <blockquote className="border-l-3 border-gray-400 pl-3 text-gray-600 italic mb-2 text-sm">
      {children}
    </blockquote>
  ),
  strong: ({ children }: any) => (
    <strong className="font-semibold text-black">{children}</strong>
  ),
  table: ({ children }: any) => (
    <div className="overflow-x-auto mb-2">
      <table className="min-w-full text-xs border-collapse">{children}</table>
    </div>
  ),
  th: ({ children }: any) => (
    <th className="border border-gray-300 bg-gray-200 px-2 py-1 text-left font-semibold text-black">
      {children}
    </th>
  ),
  td: ({ children }: any) => (
    <td className="border border-gray-300 px-2 py-1 text-black">{children}</td>
  ),
}

export function ChatPanel({ messages, loading, chatDisabled, onSendMessage, onStop }: ChatPanelProps) {
  const [input, setInput] = useState("")
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, loading])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = input.trim()
    if (!trimmed || loading || chatDisabled) return
    onSendMessage(trimmed)
    setInput("")
  }

  if (messages.length === 0 && !loading) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center text-gray-400">
        <div className="w-16 h-16 rounded-full bg-gray-100 flex items-center justify-center mb-4">
          <Bot className="h-8 w-8 text-gray-400" />
        </div>
        <p className="text-lg font-medium text-gray-500">Log Analyzer</p>
        <p className="text-sm mt-1 text-gray-400">
          Select search parameters and start analysis
        </p>
        <p className="text-xs mt-3 text-gray-400 max-w-xs text-center">
          Or type a message below to start chatting
        </p>

        <div className="absolute bottom-0 left-0 right-0 border-t border-gray-200 p-4 bg-white">
          <form onSubmit={handleSubmit} className="flex gap-2">
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={chatDisabled ? "Sign in with Webex to chat..." : "Ask a question or paste a tracking ID..."}
              disabled={chatDisabled}
              className="border-gray-300 text-sm"
            />
            <Button
              type="submit"
              disabled={chatDisabled || !input.trim()}
              className="bg-[#00BCEB] text-white hover:bg-[#00BCEB99] px-4"
            >
              <Send className="h-4 w-4" />
            </Button>
          </form>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full w-full flex flex-col">
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`flex gap-2.5 max-w-[85%] ${
                msg.role === "user" ? "flex-row-reverse" : ""
              }`}
            >
              <div
                className={`w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5 ${
                  msg.role === "user" ? "bg-[#00BCEB]" : "bg-gray-200"
                }`}
              >
                {msg.role === "user" ? (
                  <User className="h-3.5 w-3.5 text-white" />
                ) : (
                  <Bot className="h-3.5 w-3.5 text-gray-600" />
                )}
              </div>

              <div
                className={`rounded-2xl px-4 py-2.5 ${
                  msg.role === "user"
                    ? "bg-[#00BCEB] text-white"
                    : "bg-gray-100 text-black"
                }`}
              >
                {msg.role === "user" ? (
                  <p className="text-sm whitespace-pre-wrap leading-relaxed">
                    {msg.content}
                  </p>
                ) : (
                  <div className="prose prose-sm max-w-none">
                    <ReactMarkdown components={markdownComponents}>
                      {msg.content}
                    </ReactMarkdown>
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex justify-start">
            <div className="flex gap-2.5 items-start">
              <div className="w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5 bg-gray-200">
                <Bot className="h-3.5 w-3.5 text-gray-600" />
              </div>
              <div className="bg-gray-100 rounded-2xl px-4 py-3">
                <div className="flex items-center gap-2 text-gray-500">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  <span className="text-sm">Analyzing...</span>
                </div>
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <div className="border-t border-gray-200 p-4">
        <form onSubmit={handleSubmit} className="flex gap-2">
          <Input
            value={input}
            onChange={(e) => setInput(e.target.value)}
              placeholder={chatDisabled ? "Sign in with Webex to chat..." : "Ask about the analysis..."}
            disabled={loading || chatDisabled}
            className="border-gray-300 text-sm"
          />
          {loading ? (
            <Button
              type="button"
              onClick={onStop}
              className="bg-red-500 text-white hover:bg-red-600 px-4"
            >
              <Square className="h-4 w-4" />
            </Button>
          ) : (
            <Button
              type="submit"
              disabled={chatDisabled || !input.trim()}
              className="bg-[#00BCEB] text-white hover:bg-[#00BCEB99] px-4"
            >
              <Send className="h-4 w-4" />
            </Button>
          )}
        </form>
      </div>
    </div>
  )
}
