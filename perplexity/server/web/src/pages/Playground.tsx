import { useEffect, useState } from 'react'
import { useChat } from 'hooks/useChat'
import { ChatInput } from 'components/playground/ChatInput'
import { ChatContainer } from 'components/playground/ChatContainer'
import { TokenInput } from 'components/playground/TokenInput'

export function Playground() {
  const {
    messages,
    isLoading,
    isStreaming,
    error,
    models,
    selectedModel,
    apiToken,
    setSelectedModel,
    saveApiToken,
    loadModels,
    sendMessage,
    clearChat,
  } = useChat()

  const [isHeaderVisible, setIsHeaderVisible] = useState(true)
  const isConnected = models.length > 0

  // Auto-load models if token exists (don't retry on error)
  useEffect(() => {
    if (apiToken && models.length === 0 && !isLoading && !error) {
      loadModels()
    }
  }, [apiToken, models.length, isLoading, error, loadModels])

  return (
    <div className="h-screen text-gray-200 font-sans flex flex-col overflow-hidden relative px-4 md:px-6">
      {/* Header - fixed height with animation */}
      <header
        className={`flex-shrink-0 border-gray-800 overflow-hidden transition-all duration-300 ease-in-out ${
          isHeaderVisible
            ? 'pt-4 md:pt-6 border-b-4 max-h-[500px] opacity-100'
            : 'py-0 border-b-0 max-h-0 opacity-0'
        }`}
      >
        <div className="max-w-6xl mx-auto">
          <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4 mb-4">
            <div>
              <h1 className="text-3xl md:text-5xl font-black uppercase tracking-tighter leading-none text-white mix-blend-difference">
                Perplexity
                <br />
                <span className="text-transparent bg-clip-text bg-gradient-to-r from-neon-pink to-neon-blue">
                  API Playground
                </span>
              </h1>
              <p className="font-mono text-gray-400 text-sm mt-1">/// OAI_COMPATIBLE_V1</p>
            </div>
            <a
              href="/admin/"
              className="font-mono text-xs uppercase text-gray-400 hover:text-acid border-2 border-gray-600 hover:border-acid px-3 py-2 transition-colors"
            >
              &larr; Admin Panel
            </a>
          </div>

          {/* Token Input */}
          <div className="mb-4">
            <TokenInput
              token={apiToken}
              onSave={saveApiToken}
              onConnect={loadModels}
              isConnected={isConnected}
              isLoading={isLoading && models.length === 0}
            />
          </div>

          {/* Error display */}
          {error && !isConnected && (
            <div className="mt-4 bg-danger/20 border-2 border-danger text-danger font-mono text-sm px-4 py-2">
              {error}
            </div>
          )}
        </div>
      </header>

      {/* Header Toggle Button - Below header */}
      <div className="flex justify-center flex-shrink-0 z-50 relative -mt-[2px] mb-1">
        <button
          onClick={() => setIsHeaderVisible(!isHeaderVisible)}
          className="bg-concrete border-2 border-t-0 border-gray-600 hover:border-acid text-gray-400 hover:text-acid px-8 py-0.5 rounded-b-lg transition-colors shadow-lg"
          title={isHeaderVisible ? 'Collapse Header' : 'Expand Header'}
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
            strokeWidth={3}
            stroke="currentColor"
            className={`w-3 h-3 transition-transform duration-300 ${
              isHeaderVisible ? 'rotate-180' : 'rotate-0'
            }`}
          >
            <path
              strokeLinecap="square"
              strokeLinejoin="miter"
              d="M19.5 8.25l-7.5 7.5-7.5-7.5"
            />
          </svg>
        </button>
      </div>

      {/* Chat Area - fills remaining space */}
      <main className="flex-1 flex flex-col max-w-6xl mx-auto w-full min-h-0">
        {/* Chat messages - scrollable */}
        <ChatContainer messages={messages} isStreaming={isStreaming} isLoading={isLoading} />

        {/* Input - fixed at bottom */}
        <div className="flex-shrink-0">
          <ChatInput
            onSend={sendMessage}
            onClear={messages.length > 0 ? clearChat : undefined}
            disabled={!isConnected || isLoading}
            placeholder={
              !isConnected ? 'Connect with API token first...' : 'Type your message...'
            }
            models={models}
            selectedModel={selectedModel}
            onSelectModel={setSelectedModel}
          />
        </div>
      </main>
    </div>
  )
}
