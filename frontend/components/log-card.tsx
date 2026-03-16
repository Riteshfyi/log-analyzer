"use client"

import { useState } from "react"
import { Card, CardContent, CardHeader } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { LogDetailModal } from "@/components/log-detail-modal"
import { Calendar, Server, AlertCircle, Eye } from "lucide-react"

interface LogCardProps {
  log: any
}

export function LogCard({ log }: LogCardProps) {
  const [showDetail, setShowDetail] = useState(false)
  const source = log._source

  const getLogLevelColor = (level: string) => {
    switch (level?.toUpperCase()) {
      case "ERROR":
        return "bg-red-100 text-red-800 border-red-200"
      case "WARN":
        return "bg-yellow-100 text-yellow-800 border-yellow-200"
      case "INFO":
        return "bg-blue-100 text-blue-800 border-blue-200"
      case "DEBUG":
        return "bg-gray-100 text-gray-800 border-gray-200"
      default:
        return "bg-gray-100 text-gray-800 border-gray-200"
    }
  }

  return (
    <>
      <Card className="border-gray-200 hover:border-gray-300 transition-colors">
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-2">
              <Badge className={getLogLevelColor(source.log_level)}>{source.log_level || "UNKNOWN"}</Badge>
              <Badge variant="outline" className="text-gray-600">
                Score: {log._score?.toFixed(2)}
              </Badge>
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowDetail(true)}
              className="text-black border-gray-300 hover:bg-gray-50"
            >
              <Eye className="h-4 w-4 mr-1" />
              Details
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="text-sm text-black line-clamp-2">{source.message}</div>

          <div className="flex flex-wrap gap-4 text-xs text-gray-600">
            <div className="flex items-center gap-1">
              <Calendar className="h-3 w-3" />
              {new Date(source["@timestamp"]).toLocaleString()}
            </div>
            <div className="flex items-center gap-1">
              <Server className="h-3 w-3" />
              {source.hostname}
            </div>
            {source.environment && (
              <div className="flex items-center gap-1">
                <AlertCircle className="h-3 w-3" />
                {source.environment}
              </div>
            )}
          </div>

          {source.tags && (
            <div className="flex flex-wrap gap-1">
              {[...(Array.isArray(source.tags) ? source.tags : [source.tags])].map((tag: string, index: number) => (
                <Badge key={index} variant="secondary" className="text-xs">
                  {tag}
                </Badge>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <LogDetailModal log={log} open={showDetail} onOpenChange={setShowDetail} />
    </>
  )
}
