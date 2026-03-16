"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Activity } from "lucide-react";
import { useEffect, useRef, useState } from "react";
interface ChartsViewProps {
  plantUMLCode: string;
}

export function ChartsView({ plantUMLCode }: ChartsViewProps) {
  console.log("chartsview", plantUMLCode); // Debug log
  const diagramRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const renderDiagram = async () => {
      if (!plantUMLCode || !diagramRef.current) return;

      setLoading(true);
      setError(null);

      try {
        diagramRef.current.innerHTML = "";

        // Use POST request with caching via browser cache
        console.log("Sending PlantUML to Kroki via POST");
        
        const response = await fetch('https://kroki.io/plantuml/svg', {
          method: 'POST',
          headers: {
            'Content-Type': 'text/plain',
            'Accept': 'image/svg+xml'
          },
          body: plantUMLCode.trim(), // Send raw PlantUML code
          cache: 'force-cache' // Let browser handle caching
        });

        if (!response.ok) {
          const errorText = await response.text();
          console.error("Kroki error response:", response.status, errorText);
          throw new Error(`Kroki error: ${response.status} - ${errorText}`);
        }

        const svg = await response.text();
        
        // Validate that we got actual SVG
        if (!svg.includes('<svg')) {
          throw new Error('Invalid SVG response from Kroki');
        }

        diagramRef.current.innerHTML = svg;
        
        // Constrain SVG size to fit container
        const svgElement = diagramRef.current.querySelector('svg');
        if (svgElement) {
          svgElement.style.maxWidth = '100%';
          svgElement.style.height = 'auto';
        }
        
        console.log("Diagram rendered successfully");

      } catch (err) {
        console.error("PlantUML rendering error:", err);
        const errorMessage = err instanceof Error ? err.message : "Unknown error";
        setError(errorMessage);
        
        // Show error with raw code for debugging
        if (diagramRef.current) {
          diagramRef.current.innerHTML = `
            <div class="text-red-500 p-4 border border-red-200 rounded">
              <p class="font-semibold">Error rendering diagram:</p>
              <p class="text-sm mt-1">${errorMessage}</p>
              <div class="mt-2 text-xs text-gray-600">
                <p><strong>Code length:</strong> ${plantUMLCode.length} characters</p>
                <p><strong>Starts correctly:</strong> ${plantUMLCode.trim().startsWith('@startuml') ? 'Yes' : 'No'}</p>
                <p><strong>Ends correctly:</strong> ${plantUMLCode.trim().endsWith('@enduml') ? 'Yes' : 'No'}</p>
              </div>
              <details class="mt-2">
                <summary class="cursor-pointer text-xs text-blue-600 hover:text-blue-800">
                  View Raw PlantUML Code (copy this to test in Kroki)
                </summary>
                <pre class="mt-1 text-xs bg-gray-100 p-2 rounded overflow-auto max-h-40 whitespace-pre-wrap">${plantUMLCode}</pre>
              </details>
              <div class="mt-2">
                <a 
                  href="https://kroki.io/examples.html" 
                  target="_blank" 
                  class="text-xs text-blue-600 hover:text-blue-800 underline"
                >
                  Test in Kroki interface →
                </a>
              </div>
            </div>
          `;
        }
      } finally {
        setLoading(false);
      }
    };

    renderDiagram();
  }, [plantUMLCode]);

  if (!plantUMLCode) {
    return (
      <div className="text-center py-8 text-gray-500">
        <p>No diagram data available</p>
      </div>
    );
  }

  return (
    <div className="py-2">
      <div className="w-full">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Activity className="h-5 w-5" />
              Sequence Diagram
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="w-full overflow-auto h-full">
              {loading && (
                <div className="flex justify-center items-center py-8">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
                  <span className="ml-2 text-gray-600">Rendering diagram...</span>
                </div>
              )}
              
              {!loading && !error && (
                <div ref={diagramRef} className="flex justify-center max-w-full" style={{ maxHeight: '100%' }} />
              )}
              
              {!loading && error && (
                <div ref={diagramRef} className="max-w-full" />
              )}
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}