"use client"

import { useState, useEffect } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { AlertCircle, CheckCircle, RefreshCw, Server } from "lucide-react"

interface ConnectionStatusProps {
  apiUrl: string
  onRetry?: () => void
}

export function ConnectionStatus({ apiUrl, onRetry }: ConnectionStatusProps) {
  const [status, setStatus] = useState<"checking" | "connected" | "disconnected">("checking")
  const [lastCheck, setLastCheck] = useState<Date>(new Date())

  const checkConnection = async () => {
    setStatus("checking")
    try {
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), 5000)

      const response = await fetch(`${apiUrl}/health`, {
        method: "GET",
        signal: controller.signal,
      })

      clearTimeout(timeoutId)
      setStatus(response.ok ? "connected" : "disconnected")
    } catch (error) {
      setStatus("disconnected")
    }
    setLastCheck(new Date())
  }

  useEffect(() => {
    checkConnection()
    const interval = setInterval(checkConnection, 30000) // Check every 30 seconds
    return () => clearInterval(interval)
  }, [apiUrl])

  const handleRetry = () => {
    checkConnection()
    onRetry?.()
  }

  return (
    <Card className="border-gray-200 mb-6">
      <CardContent className="p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Server className="h-5 w-5 text-gray-600" />
            <div>
              <div className="flex items-center gap-2">
                <span className="text-sm font-medium text-black">ADK API Server</span>
                <Badge
                  className={
                    status === "connected"
                      ? "bg-green-100 text-green-800 border-green-200"
                      : status === "disconnected"
                        ? "bg-red-100 text-red-800 border-red-200"
                        : "bg-yellow-100 text-yellow-800 border-yellow-200"
                  }
                >
                  {status === "connected" && <CheckCircle className="h-3 w-3 mr-1" />}
                  {status === "disconnected" && <AlertCircle className="h-3 w-3 mr-1" />}
                  {status === "checking" && <RefreshCw className="h-3 w-3 mr-1 animate-spin" />}
                  {status === "connected" ? "Connected" : status === "disconnected" ? "Disconnected" : "Checking..."}
                </Badge>
              </div>
              <div className="text-xs text-gray-500">
                {apiUrl} • Last checked: {lastCheck.toLocaleTimeString()}
              </div>
            </div>
          </div>

          {status === "disconnected" && (
            <Button
              variant="outline"
              size="sm"
              onClick={handleRetry}
              className="text-black border-gray-300 bg-transparent"
            >
              <RefreshCw className="h-4 w-4 mr-1" />
              Retry
            </Button>
          )}
        </div>

        {status === "disconnected" && (
          <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-md">
            <p className="text-sm text-red-800">
              <strong>Connection Failed:</strong> Cannot connect to the ADK API server.
            </p>
            <p className="text-xs text-red-600 mt-1">
              Please ensure the server is running with: <code className="bg-red-100 px-1 rounded">adk api_server</code>
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
