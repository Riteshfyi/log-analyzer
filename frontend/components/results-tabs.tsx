"use client"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { AnalysisView } from "@/components/analysis-view"
import { ChartsView } from "@/components/charts-view"
import { LogsView } from "@/components/logs-view"
import { ChatView } from "@/components/chat-view"

interface ResultsTabsProps {
  results: any
  analysis: string
  mermaidCode: string
  chatResponse: string
}

export function ResultsTabs({ results, analysis, mermaidCode , chatResponse}: ResultsTabsProps) {
  console.log("ResultsTabs received mermaidCode:", mermaidCode); // Debug log
  
  return (
    <div className="w-full h-full overflow-hidden">
      <Tabs defaultValue="analysis" className="h-full">
      <TabsList className="grid w-full grid-cols-3 bg-gray-100">
          <TabsTrigger value="analysis" className="text-black data-[state=active]:bg-white">
          Analysis
        </TabsTrigger>

        <TabsTrigger value="logs" className="text-black data-[state=active]:bg-white">
          Raw Logs
        </TabsTrigger>

        <TabsTrigger value="charts" className="text-black data-[state=active]:bg-white">
          Charts
        </TabsTrigger>
      </TabsList>
      <TabsContent value="analysis" className="h-full overflow-y-auto">
        <AnalysisView analysis={analysis} />
      </TabsContent>

      <TabsContent value="logs" className="h-full overflow-y-auto">
        <LogsView results={results} />
      </TabsContent>


      <TabsContent value="charts" className="h-full overflow-y-auto">
        <ChartsView plantUMLCode={mermaidCode} />
      </TabsContent>

      <TabsContent value="chat" className="h-full overflow-y-auto">
        <ChatView chatResponse={chatResponse} />
      </TabsContent>
      
    </Tabs>
    </div>
    
  )
}
