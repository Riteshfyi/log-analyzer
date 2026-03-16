import { LogCard } from "./log-card";

export function LogsView({ results }: { results: any }) {

  return (
           <div className="space-y-4">
          {results?.map((hit: any, index: number) => (
            <LogCard key={hit._id || index} log={hit} />
          ))}
        </div>
  )
}