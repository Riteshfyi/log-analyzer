"use client"

import { useState, useEffect } from "react"
import { SearchForm } from "@/components/search-form"
import { ChatPanel, type ChatMessage } from "@/components/chat-panel"
import { SessionManager } from "@/lib/session-manager"
import { Card } from "@/components/ui/card"

const FIELD_LABELS: Record<string, string> = {
  "fields.WEBEX_TRACKINGID.keyword": "Tracking ID",
  "fields.mobiusCallId.keyword": "Mobius Call ID",
  "fields.USER_ID.keyword": "User ID",
  "fields.DEVICE_ID.keyword": "Device ID",
  "fields.WEBEX_MEETING_ID.keyword": "Meeting ID",
  "fields.LOCUS_ID.keyword": "Locus ID",
  "fields.sipCallId.keyword": "SIP Call ID",
  "callId.keyword": "Call ID",
  "traceId.keyword": "Trace ID",
  sessionId: "Session ID",
  message: "Global Search",
}

function formatSearchLabel(params: any): string {
  const parts: string[] = []

  if (params.searchField && params.searchValue) {
    const field = FIELD_LABELS[params.searchField] || params.searchField
    parts.push(`${field}: ${params.searchValue}`)
  }

  if (params.uploadedFile) {
    parts.push(`Uploaded: ${params.uploadedFile.name}`)
  }

  const envLabels = (params.environments || []).map((e: string) =>
    e === "prod" ? "Production" : "Integration"
  )
  if (envLabels.length) parts.push(envLabels.join(", "))

  const regions = (params.regions || []).map((r: string) => r.toUpperCase())
  if (regions.length) parts.push(regions.join(", "))

  return parts.join(" · ") || "Analysis"
}

function extractChatResponse(events: any[]): string {
  if (!Array.isArray(events)) return ""
  for (let i = events.length - 1; i >= 0; i--) {
    const event = events[i]
    if (event.author === "chat_agent") {
      const text = event.content?.parts?.[0]?.text
      if (text) return text
    }
  }
  return ""
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError"
}

function makeId(): string {
  return `${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
}

export default function HomePage() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [hasToken, setHasToken] = useState(false)
  const [oauthToken, setOauthToken] = useState("")
  const [authError, setAuthError] = useState("")
  const [sessionManager] = useState(() => new SessionManager())

  useEffect(() => {
    const hash = window.location.hash
    console.log("[Auth] Page loaded, hash:", hash ? hash.substring(0, 50) + "..." : "(none)")
    if (!hash) return

    const params = new URLSearchParams(hash.substring(1))

    const token = params.get("access_token")
    if (token) {
      console.log("[Auth] Bearer token received, length:", token.length)
      console.log("[Auth] Token preview:", token.substring(0, 20) + "...")
      setOauthToken(token)
      setHasToken(true)
      sessionManager.setOauthToken(token)
      console.log("[Auth] Token set in SessionManager, auth complete")
      window.history.replaceState(null, "", window.location.pathname)
      return
    }

    const error = params.get("error")
    if (error) {
      console.error("[Auth] OAuth error:", decodeURIComponent(error))
      setAuthError(decodeURIComponent(error))
      window.history.replaceState(null, "", window.location.pathname)
    }
  }, [sessionManager])

  const appendMessage = (role: "user" | "assistant", content: string) => {
    setMessages((prev) => [...prev, { id: makeId(), role, content }])
  }

  const handleStop = async () => {
    if (!loading) return

    sessionManager.abort()

    try {
      const { state, events } = await sessionManager.getSession()

      const conversationEvents = events.filter(
        (e: any) => e.author === "user" || e.author === "chat_agent"
      )

      if (
        conversationEvents.length > 0 &&
        conversationEvents[conversationEvents.length - 1].author === "user"
      ) {
        conversationEvents.pop()
      }

      await sessionManager.deleteSession()
      await sessionManager.createSessionWithContext(state, conversationEvents)
    } catch (error) {
      console.error("Stop: failed to transfer session context:", error)
      try {
        await sessionManager.deleteSession()
      } catch {
        /* best effort */
      }
    }

    setLoading(false)
  }

  const handleSearch = async (searchParams: any) => {
    setLoading(true)
    try {
      const restParams = searchParams
      await sessionManager.ensureSession()

      appendMessage("user", formatSearchLabel(restParams))

      const events = await sessionManager.sendMessage(
        JSON.stringify(restParams)
      )
      const response = extractChatResponse(events)
      appendMessage(
        "assistant",
        response ||
          "The analysis pipeline completed but no chat response was generated."
      )
    } catch (error) {
      if (isAbortError(error)) return
      console.error("Search failed:", error)
      appendMessage(
        "assistant",
        "An error occurred while processing your search. Please try again."
      )
    } finally {
      setLoading(false)
    }
  }

  const handleSendMessage = async (text: string) => {
    setLoading(true)
    appendMessage("user", text)
    try {
      await sessionManager.ensureSession()
      const events = await sessionManager.sendMessage(text)
      const response = extractChatResponse(events)
      appendMessage(
        "assistant",
        response || "No response from the assistant."
      )
    } catch (error) {
      if (isAbortError(error)) return
      console.error("Chat failed:", error)
      appendMessage(
        "assistant",
        "An error occurred. Please try again."
      )
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="h-screen flex flex-row gap-0 overflow-hidden">
      <div className="w-1/4 p-3 overflow-y-auto">
        <SearchForm
          onSearch={handleSearch}
          loading={loading}
          isAuthenticated={hasToken}
          authError={authError}
        />
      </div>
      <div className="flex flex-1 p-3">
        <Card className="border-gray-200 flex flex-1 overflow-hidden relative">
          <ChatPanel
            messages={messages}
            loading={loading}
            chatDisabled={!hasToken}
            onSendMessage={handleSendMessage}
            onStop={handleStop}
          />
        </Card>
      </div>
    </div>
  )
}
