import { useEffect, useRef } from 'react'
import { ChatMessage as ChatMessageType } from 'lib/api'
import { ChatMessage } from './ChatMessage'

interface ChatContainerProps {
  messages: ChatMessageType[]
  isStreaming?: boolean
  isLoading?: boolean
}

export function ChatContainer({
  messages,
  isStreaming,
  isLoading
}: ChatContainerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const nearBottom = useRef(true)
  const previous = useRef({ first: messages[0]?.id, height: 0 })

  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const first = messages[0]?.id
    const prepended =
      first !== undefined &&
      previous.current.first !== undefined &&
      first < previous.current.first
    if (prepended)
      container.scrollTop += container.scrollHeight - previous.current.height
    else if (nearBottom.current)
      bottomRef.current?.scrollIntoView({ behavior: 'auto' })
    previous.current = { first, height: container.scrollHeight }
  }, [messages, isStreaming])

  if (messages.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center p-8 overflow-hidden">
        <div className="text-center">
          <div className="font-mono text-6xl text-gray-700 mb-4">&gt;_</div>
          <p className="font-mono text-gray-500 uppercase">
            Start a conversation by typing a message below
          </p>
        </div>
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      onScroll={() => {
        const container = containerRef.current
        if (container)
          nearBottom.current =
            container.scrollHeight -
              container.scrollTop -
              container.clientHeight <
            100
      }}
      className="flex-1 overflow-y-auto p-4 min-h-0 scrollbar-hidden"
    >
      {messages.map((msg, idx) => (
        <ChatMessage
          key={msg.id ?? `${msg.job_id || idx}-${msg.role}`}
          message={msg}
          isStreaming={
            isStreaming &&
            idx === messages.length - 1 &&
            msg.role === 'assistant'
          }
        />
      ))}
      {isLoading && !isStreaming && (
        <div className="flex justify-start mb-4">
          <div className="bg-concrete border-2 border-gray-600 px-4 py-3">
            <div className="flex gap-1">
              <span className="w-2 h-2 bg-neon-pink rounded-full animate-bounce" />
              <span
                className="w-2 h-2 bg-neon-blue rounded-full animate-bounce"
                style={{ animationDelay: '0.1s' }}
              />
              <span
                className="w-2 h-2 bg-acid rounded-full animate-bounce"
                style={{ animationDelay: '0.2s' }}
              />
            </div>
          </div>
        </div>
      )}
      {/* Invisible element for scrolling to bottom */}
      <div ref={bottomRef} />
    </div>
  )
}
