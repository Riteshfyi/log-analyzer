const ADK_API_URL =
  process.env.NEXT_PUBLIC_ADK_API_URL || "http://127.0.0.1:8000"

const APP_NAME = "root"

function generateId(prefix: string): string {
  return `${prefix}_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
}

const PIPELINE_STATE_DEFAULTS: Record<string, string> = {
  mobius_logs: "",
  sse_mse_logs: "",
  wxcas_logs: "",
  all_logs: "",
  search_summary: "",
  parsed_query: "",
  extracted_ids: "",
  latest_search_results: "",
  analyze_results: "",
  sequence_diagram: "",
  sdk_logs: "",
}

export class SessionManager {
  private userId: string
  private sessionId: string
  private sessionCreated = false
  private activeController: AbortController | null = null
  private activeTimeout: ReturnType<typeof setTimeout> | null = null
  private oauthToken: string = ""

  constructor() {
    this.userId = generateId("u")
    this.sessionId = generateId("s")
  }

  setOauthToken(token: string): void {
    this.oauthToken = token
  }

  async ensureSession(): Promise<void> {
    if (this.sessionCreated) return

    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 2100000)

    try {
      const response = await fetch(
        `${ADK_API_URL}/apps/${APP_NAME}/users/${this.userId}/sessions`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            sessionId: this.sessionId,
            state: { ...PIPELINE_STATE_DEFAULTS, oauth_token: this.oauthToken },
          }),
          signal: controller.signal,
        }
      )

      clearTimeout(timeoutId)

      if (response.ok) {
        this.sessionCreated = true
      } else {
        const error = await response.text()
        throw new Error(`Failed to create session: ${error}`)
      }
    } catch (error) {
      clearTimeout(timeoutId)
      throw error
    }
  }

  async sendMessage(text: string): Promise<any[]> {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 2100000)

    this.activeController = controller
    this.activeTimeout = timeoutId

    try {
      const response = await fetch(`${ADK_API_URL}/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          appName: APP_NAME,
          userId: this.userId,
          sessionId: this.sessionId,
          newMessage: {
            role: "user",
            parts: [{ text }],
          },
        }),
        signal: controller.signal,
      })

      clearTimeout(timeoutId)
      this.activeController = null
      this.activeTimeout = null

      if (!response.ok) {
        const error = await response.text()
        throw new Error(`Query failed: ${error}`)
      }

      return response.json()
    } catch (error) {
      clearTimeout(timeoutId)
      this.activeController = null
      this.activeTimeout = null
      throw error
    }
  }

  abort(): void {
    if (this.activeTimeout) {
      clearTimeout(this.activeTimeout)
      this.activeTimeout = null
    }
    if (this.activeController) {
      this.activeController.abort()
      this.activeController = null
    }
  }

  async getSession(): Promise<{ state: Record<string, any>; events: any[] }> {
    if (!this.sessionCreated) return { state: {}, events: [] }

    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 30000)

    try {
      const response = await fetch(
        `${ADK_API_URL}/apps/${APP_NAME}/users/${this.userId}/sessions/${this.sessionId}`,
        {
          method: "GET",
          signal: controller.signal,
        }
      )

      clearTimeout(timeoutId)

      if (!response.ok) {
        console.error("Failed to get session:", await response.text())
        return { state: {}, events: [] }
      }

      const session = await response.json()
      return {
        state: session.state || {},
        events: session.events || [],
      }
    } catch (error) {
      clearTimeout(timeoutId)
      console.error("Failed to get session:", error)
      return { state: {}, events: [] }
    }
  }

  async createSessionWithContext(
    state: Record<string, any>,
    events: any[]
  ): Promise<void> {
    this.sessionId = generateId("s")
    this.sessionCreated = false

    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 60000)

    try {
      const response = await fetch(
        `${ADK_API_URL}/apps/${APP_NAME}/users/${this.userId}/sessions`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            sessionId: this.sessionId,
            state: { ...PIPELINE_STATE_DEFAULTS, ...state, oauth_token: this.oauthToken },
            events,
          }),
          signal: controller.signal,
        }
      )

      clearTimeout(timeoutId)

      if (response.ok) {
        this.sessionCreated = true
      } else {
        const error = await response.text()
        console.error("Failed to create session with context:", error)
        throw new Error(`Failed to create session with context: ${error}`)
      }
    } catch (error) {
      clearTimeout(timeoutId)
      throw error
    }
  }

  getUserId(): string {
    return this.userId
  }

  getSessionId(): string {
    return this.sessionId
  }

  async deleteSession(): Promise<void> {
    if (!this.sessionCreated) return

    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 30000)

    try {
      await fetch(
        `${ADK_API_URL}/apps/${APP_NAME}/users/${this.userId}/sessions/${this.sessionId}`,
        {
          method: "DELETE",
          signal: controller.signal,
        }
      )
      clearTimeout(timeoutId)
      this.sessionCreated = false
    } catch (error) {
      clearTimeout(timeoutId)
      console.error("Failed to delete session:", error)
    }
  }
}
