"use client"

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Terminal, CheckCircle } from "lucide-react"

export function SetupInstructions() {
  return (
    <Card className="border-gray-200 mb-6">
      <CardHeader>
        <CardTitle className="text-black flex items-center gap-2">
          <Terminal className="h-5 w-5" />
          ADK API Server Setup
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-3">
          <div className="flex items-start gap-3">
            <Badge className="bg-blue-100 text-blue-800 border-blue-200 mt-0.5">1</Badge>
            <div>
              <p className="text-sm text-black font-medium">Navigate to your agent directory</p>
              <code className="text-xs bg-gray-100 px-2 py-1 rounded text-black block mt-1">
                cd /path/to/your/agent/directory
              </code>
            </div>
          </div>

          <div className="flex items-start gap-3">
            <Badge className="bg-blue-100 text-blue-800 border-blue-200 mt-0.5">2</Badge>
            <div>
              <p className="text-sm text-black font-medium">Start the ADK API server</p>
              <code className="text-xs bg-gray-100 px-2 py-1 rounded text-black block mt-1">adk api_server</code>
            </div>
          </div>

          <div className="flex items-start gap-3">
            <Badge className="bg-green-100 text-green-800 border-green-200 mt-0.5">
              <CheckCircle className="h-3 w-3" />
            </Badge>
            <div>
              <p className="text-sm text-black font-medium">Server should be running on http://localhost:8000</p>
              <p className="text-xs text-gray-600 mt-1">The connection status above will show "Connected" when ready</p>
            </div>
          </div>
        </div>

        <div className="mt-4 p-3 bg-yellow-50 border border-yellow-200 rounded-md">
          <p className="text-sm text-yellow-800">
            <strong>Note:</strong> Make sure your agent is named "root_agent" or update the agent name in the
            configuration.
          </p>
        </div>
      </CardContent>
    </Card>
  )
}
