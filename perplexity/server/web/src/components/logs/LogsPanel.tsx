import { useLogs, RefreshInterval } from 'hooks/useLogs'

interface LogsPanelProps {
  adminToken: string
}

const INTERVAL_OPTIONS: { value: RefreshInterval; label: string }[] = [
  { value: 5, label: '5s' },
  { value: 10, label: '10s' },
  { value: 15, label: '15s' },
]

function getLineClass(line: string): string {
  if (line.includes(' - ERROR - ') || line.includes(' ERROR ')) {
    return 'text-red-400'
  }
  if (line.includes(' - WARNING - ') || line.includes(' WARNING ')) {
    return 'text-yellow-400'
  }
  if (line.includes(' - DEBUG - ') || line.includes(' DEBUG ')) {
    return 'text-gray-500'
  }
  return 'text-gray-300'
}

function highlightMatch(line: string, query: string): JSX.Element {
  if (!query) {
    return <>{line}</>
  }

  const lowerLine = line.toLowerCase()
  const lowerQuery = query.toLowerCase()
  const index = lowerLine.indexOf(lowerQuery)

  if (index === -1) {
    return <>{line}</>
  }

  return (
    <>
      {line.slice(0, index)}
      <span className="bg-yellow-500/30">{line.slice(index, index + query.length)}</span>
      {line.slice(index + query.length)}
    </>
  )
}

export function LogsPanel({ adminToken }: LogsPanelProps) {
  const {
    filteredLines,
    totalLines,
    fileSize,
    isLoading,
    error,
    searchQuery,
    setSearchQuery,
    refreshInterval,
    setRefreshInterval,
    isAutoRefresh,
    setIsAutoRefresh,
    refresh,
    lastUpdate,
  } = useLogs(adminToken)

  return (
    <div className="space-y-4">
      {/* Controls Bar */}
      <div className="flex flex-col gap-4 rounded border-2 border-gray-700 bg-gray-900 p-4 md:flex-row md:items-center md:justify-between">
        {/* Auto Refresh Controls */}
        <div className="flex items-center gap-4">
          <span className="font-mono text-xs uppercase text-gray-400">Auto_Refresh:</span>
          <div className="flex">
            <button
              onClick={() => setIsAutoRefresh(true)}
              className={`border-2 px-3 py-1 font-mono text-xs transition-colors ${
                isAutoRefresh
                  ? 'border-acid bg-acid/10 text-acid'
                  : 'border-gray-600 text-gray-400 hover:border-gray-400'
              }`}
            >
              ON
            </button>
            <button
              onClick={() => setIsAutoRefresh(false)}
              className={`-ml-0.5 border-2 px-3 py-1 font-mono text-xs transition-colors ${
                !isAutoRefresh
                  ? 'border-acid bg-acid/10 text-acid'
                  : 'border-gray-600 text-gray-400 hover:border-gray-400'
              }`}
            >
              OFF
            </button>
          </div>

          {/* Interval Selector */}
          <select
            value={refreshInterval}
            onChange={(e) => setRefreshInterval(Number(e.target.value) as RefreshInterval)}
            disabled={!isAutoRefresh}
            className={`border-2 bg-gray-900 px-2 py-1 font-mono text-xs ${
              isAutoRefresh
                ? 'border-gray-600 text-gray-200'
                : 'cursor-not-allowed border-gray-700 text-gray-600'
            }`}
          >
            {INTERVAL_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </div>

        {/* Search and Manual Refresh */}
        <div className="flex items-center gap-4">
          <div className="relative">
            <input
              type="text"
              placeholder="Filter logs..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-48 border-2 border-gray-600 bg-gray-800 px-3 py-1 font-mono text-sm text-gray-200 placeholder-gray-500 focus:border-acid focus:outline-none"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 font-mono text-gray-500 hover:text-gray-300"
              >
                x
              </button>
            )}
          </div>

          <button
            onClick={refresh}
            disabled={isAutoRefresh || isLoading}
            className={`border-2 px-4 py-1 font-mono text-xs uppercase transition-colors ${
              isAutoRefresh || isLoading
                ? 'cursor-not-allowed border-gray-700 text-gray-600'
                : 'border-acid text-acid hover:bg-acid/10'
            }`}
          >
            {isLoading ? 'Loading...' : 'Refresh'}
          </button>
        </div>
      </div>

      {/* Log Content */}
      {error ? (
        <div className="flex h-96 flex-col items-center justify-center rounded border-2 border-red-500/50 bg-gray-900">
          <div className="mb-2 font-mono text-red-400">ERROR</div>
          <div className="font-mono text-sm text-gray-400">{error}</div>
          <button
            onClick={refresh}
            className="mt-4 border-2 border-red-400 px-4 py-2 font-mono text-sm text-red-400 hover:bg-red-400/10"
          >
            RETRY
          </button>
        </div>
      ) : isLoading && filteredLines.length === 0 ? (
        <div className="flex h-96 items-center justify-center rounded border-2 border-gray-700 bg-gray-900">
          <div className="animate-pulse font-mono text-acid">LOADING_LOGS...</div>
        </div>
      ) : filteredLines.length === 0 ? (
        <div className="flex h-96 items-center justify-center rounded border-2 border-gray-700 bg-gray-900">
          <div className="font-mono text-gray-500">
            {searchQuery ? 'NO_MATCHING_LOGS' : 'NO_LOGS_FOUND'}
          </div>
        </div>
      ) : (
        <div className="h-96 overflow-y-auto whitespace-pre-wrap rounded border-2 border-gray-700 bg-gray-900 p-4 font-mono text-sm">
          {filteredLines.map((line, i) => (
            <div key={i} className={getLineClass(line)}>
              {highlightMatch(line, searchQuery)}
            </div>
          ))}
        </div>
      )}

      {/* Status Bar */}
      <div className="flex justify-between font-mono text-xs text-gray-500">
        <span>
          SHOWING: {filteredLines.length} / {totalLines} lines
          {searchQuery && ` (filtered)`}
        </span>
        <span className="flex gap-4">
          <span>FILE_SIZE: {(fileSize / 1024).toFixed(1)} KB</span>
          {lastUpdate && <span>LAST_UPDATE: {lastUpdate}</span>}
        </span>
      </div>
    </div>
  )
}
