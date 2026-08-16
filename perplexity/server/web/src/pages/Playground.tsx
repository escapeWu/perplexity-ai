import { useEffect, useState } from 'react'
import { ChatContainer } from 'components/playground/ChatContainer'
import { ChatInput } from 'components/playground/ChatInput'
import { SessionSidebar } from 'components/playground/SessionSidebar'
import { TokenInput } from 'components/playground/TokenInput'
import { useChat } from 'hooks/useChat'

export function Playground() {
  const {
    messages,
    sessions,
    activeSession,
    activeSessionId,
    isLoading,
    isSessionLoading,
    isStreaming,
    error,
    models,
    selectedModel,
    thinking,
    apiToken,
    streamEnabled,
    pendingFiles,
    setSelectedModel,
    setThinking,
    saveApiToken,
    setStreamEnabled,
    loadModels,
    createSession,
    selectSession,
    renameSession,
    deleteSession,
    sendMessage,
    addFiles,
    removeFile,
    stopStreaming
  } = useChat()

  const [isHeaderVisible, setIsHeaderVisible] = useState(true)
  const [isDrawerOpen, setIsDrawerOpen] = useState(false)
  const isConnected = models.length > 0
  const isBusy = isLoading || isSessionLoading

  useEffect(() => {
    if (apiToken && models.length === 0 && !isLoading && !error) {
      loadModels()
    }
  }, [apiToken, models.length, isLoading, error, loadModels])

  const sidebar = (mobile = false) => (
    <SessionSidebar
      sessions={sessions}
      activeSessionId={activeSessionId}
      connected={isConnected}
      disabled={isBusy}
      onNew={() => void createSession()}
      onSelect={(sessionId) => void selectSession(sessionId)}
      onRename={renameSession}
      onDelete={(sessionId) => void deleteSession(sessionId)}
      onClose={mobile ? () => setIsDrawerOpen(false) : undefined}
    />
  )

  return (
    <div className="flex h-screen overflow-hidden font-sans text-gray-200">
      <div className="hidden h-full shrink-0 lg:block">{sidebar()}</div>

      {isDrawerOpen && (
        <div className="fixed inset-0 z-[80] flex lg:hidden">
          <button
            type="button"
            className="absolute inset-0 bg-black/75 backdrop-blur-sm"
            onClick={() => setIsDrawerOpen(false)}
            aria-label="Close conversations"
          />
          <div className="relative h-full shadow-2xl">{sidebar(true)}</div>
        </div>
      )}

      <section className="relative flex min-w-0 flex-1 flex-col overflow-hidden px-3 md:px-6">
        <header
          className={`shrink-0 overflow-hidden border-gray-800 transition-all duration-300 ease-in-out ${
            isHeaderVisible
              ? 'max-h-[500px] border-b-2 py-3 opacity-100'
              : 'max-h-0 border-b-0 py-0 opacity-0'
          }`}
        >
          <div className="mx-auto max-w-6xl">
            <TokenInput
              token={apiToken}
              onSave={saveApiToken}
              onConnect={loadModels}
              isConnected={isConnected}
              isLoading={isLoading && models.length === 0}
            />

            {error && !isConnected && (
              <div className="mt-4 border-2 border-danger bg-danger/20 px-4 py-2 font-mono text-sm text-danger">
                {error}
              </div>
            )}
          </div>
        </header>

        <div className="relative z-50 -mt-0.5 mb-1 flex shrink-0 justify-center">
          <button
            type="button"
            onClick={() => setIsHeaderVisible(!isHeaderVisible)}
            className="rounded-b-lg border-2 border-t-0 border-gray-600 bg-concrete px-8 py-0.5 text-gray-400 shadow-lg transition-colors hover:border-acid hover:text-acid"
            title={isHeaderVisible ? 'Collapse Header' : 'Expand Header'}
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={3}
              stroke="currentColor"
              className={`size-3 transition-transform duration-300 ${
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

        <div className="mx-auto flex w-full max-w-6xl shrink-0 items-center gap-3 border-b border-gray-800 p-2">
          <button
            type="button"
            onClick={() => setIsDrawerOpen(true)}
            className="grid size-8 place-items-center border border-gray-700 text-gray-400 hover:border-neon-blue hover:text-neon-blue lg:hidden"
            aria-label="Open conversations"
          >
            ☰
          </button>
          <h2 className="min-w-0 flex-1 truncate text-sm font-bold text-gray-200">
            {activeSession?.title ||
              (isConnected ? 'Loading conversation…' : 'Playground')}
          </h2>
          {activeSession?.bound_client_id && (
            <span
              className="max-w-[45vw] truncate border border-acid/40 bg-acid/5 px-2 py-1 font-mono text-[10px] uppercase text-acid/80"
              title={`This conversation is locked to ${activeSession.bound_client_id}`}
            >
              🔒 {activeSession.bound_client_id}
            </span>
          )}
        </div>

        {error && isConnected && (
          <div className="mx-auto mt-2 w-full max-w-6xl border border-danger/70 bg-danger/10 px-3 py-2 font-mono text-xs text-danger">
            {error}
          </div>
        )}

        <main className="mx-auto flex min-h-0 w-full max-w-6xl flex-1 flex-col">
          <ChatContainer
            messages={messages}
            isStreaming={isStreaming}
            isLoading={isLoading}
          />

          <div className="shrink-0">
            <ChatInput
              onSend={sendMessage}
              disabled={!isConnected || isBusy}
              placeholder={
                !isConnected
                  ? 'Connect with API token first...'
                  : isSessionLoading
                    ? 'Loading conversation...'
                    : 'Message this conversation...'
              }
              models={models}
              selectedModel={selectedModel}
              thinking={thinking}
              onSelectModel={setSelectedModel}
              onThinkingChange={setThinking}
              streamEnabled={streamEnabled}
              onStreamEnabledChange={setStreamEnabled}
              isGenerating={isLoading}
              onStop={stopStreaming}
              pendingFiles={pendingFiles}
              onAddFiles={addFiles}
              onRemoveFile={removeFile}
            />
          </div>
        </main>
      </section>
    </div>
  )
}
