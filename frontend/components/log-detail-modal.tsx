"use client"

import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Badge } from "@/components/ui/badge"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"

interface LogDetailModalProps {
  log: any
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function LogDetailModal({ log, open, onOpenChange }: LogDetailModalProps) {
  const source = log._source

  const renderValue = (value: any): string => {
    if (typeof value === "object" && value !== null) {
      return JSON.stringify(value, null, 2)
    }
    return String(value)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[80vh] bg-white">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-black">
            Log Details
            <Badge variant="outline" className="text-gray-600">
              ID: {log._id}
            </Badge>
          </DialogTitle>
        </DialogHeader>

        <ScrollArea className="h-[60vh]">
          <div className="space-y-4">
            {/* Basic Info */}
            <div>
              <h3 className="font-semibold text-black mb-2">Basic Information</h3>
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="font-medium text-gray-700">Index:</span>
                  <span className="ml-2 text-black">{log._index}</span>
                </div>
                <div>
                  <span className="font-medium text-gray-700">Score:</span>
                  <span className="ml-2 text-black">{log._score?.toFixed(4)}</span>
                </div>
                <div>
                  <span className="font-medium text-gray-700">Timestamp:</span>
                  <span className="ml-2 text-black">{new Date(source["@timestamp"]).toLocaleString()}</span>
                </div>
                <div>
                  <span className="font-medium text-gray-700">Log Level:</span>
                  <Badge className="ml-2" variant="outline">
                    {source.log_level}
                  </Badge>
                </div>
              </div>
            </div>

            <Separator />

            {/* Message */}
            <div>
              <h3 className="font-semibold text-black mb-2">Message</h3>
              <div className="bg-gray-50 p-3 rounded-md text-sm text-black font-mono">{source.message}</div>
            </div>

            <Separator />

            {/* Fields */}
            {source.fields && (
              <>
                <div>
                  <h3 className="font-semibold text-black mb-2">Fields</h3>
                  <div className="space-y-2">
                    {Object.entries(source.fields).map(([key, value]) => (
                      <div key={key} className="grid grid-cols-3 gap-2 text-sm">
                        <span className="font-medium text-gray-700">{key}:</span>
                        <span className="col-span-2 text-black font-mono break-all">{renderValue(value)}</span>
                      </div>
                    ))}
                  </div>
                </div>
                <Separator />
              </>
            )}

            {/* Other Properties */}
            <div>
              <h3 className="font-semibold text-black mb-2">Additional Properties</h3>
              <div className="space-y-2">
                {Object.entries(source)
                  .filter(([key]) => !["message", "fields", "@timestamp", "log_level"].includes(key))
                  .map(([key, value]) => (
                    <div key={key} className="grid grid-cols-3 gap-2 text-sm">
                      <span className="font-medium text-gray-700">{key}:</span>
                      <span className="col-span-2 text-black font-mono break-all">{renderValue(value)}</span>
                    </div>
                  ))}
              </div>
            </div>
          </div>
        </ScrollArea>
      </DialogContent>
    </Dialog>
  )
}
