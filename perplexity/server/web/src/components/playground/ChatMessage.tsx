import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ChatMessage as ChatMessageType, Source } from 'lib/api'

interface SourcesListProps {
  sources: Source[]
}

function SourcesList({ sources }: SourcesListProps) {
  const [isOpen, setIsOpen] = useState(false)

  if (!sources || sources.length === 0) return null

  const truncateUrl = (url: string, maxLength = 40) => {
    try {
      const urlObj = new URL(url)
      const display = urlObj.hostname + urlObj.pathname
      return display.length > maxLength ? display.slice(0, maxLength) + '...' : display
    } catch {
      return url.length > maxLength ? url.slice(0, maxLength) + '...' : url
    }
  }

  return (
    <div className="mt-3 pt-3 border-t border-gray-600">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="font-mono text-xs uppercase mb-2 text-gray-400 hover:text-white transition-colors flex items-center gap-2"
      >
        <span className="text-neon-pink font-bold">
          [{isOpen ? '-' : '+'}]
        </span>
        {sources.length} SOURCES
      </button>

      {isOpen && (
        <div className="flex flex-wrap gap-2 animate-in fade-in slide-in-from-top-1 duration-200">
          {sources.map((source, idx) => (
            <a
              key={idx}
              href={source.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 px-2 py-1 bg-void/50 border border-gray-600 hover:border-neon-blue text-sm text-gray-300 hover:text-neon-blue transition-colors"
            >
              <span className="font-mono text-xs text-gray-500">[{idx + 1}]</span>
              <span className="truncate max-w-[200px]">
                {source.title || truncateUrl(source.url)}
              </span>
            </a>
          ))}
        </div>
      )}
    </div>
  )
}

function CopyButton({ content }: { content: string }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (err) {
      console.error('Failed to copy:', err)
    }
  }

  return (
    <button
      onClick={handleCopy}
      className="absolute top-2 right-2 p-1.5 rounded-md bg-gray-800 border border-gray-700 text-gray-400 hover:text-white hover:border-gray-500 opacity-0 group-hover:opacity-100 transition-all duration-200 z-10"
      title="Copy to clipboard"
    >
      {copied ? (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4 text-green-400">
          <path fillRule="evenodd" d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z" clipRule="evenodd" />
        </svg>
      ) : (
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
          <path d="M7 3.5A1.5 1.5 0 018.5 2h3.879a1.5 1.5 0 011.06.44l3.122 3.12A1.5 1.5 0 0118 6.621V18a1.5 1.5 0 01-1.5 1.5h-9A1.5 1.5 0 016 18v-9H4v9a3.5 3.5 0 003.5 3.5h9a3.5 3.5 0 003.5-3.5V6.621a3.5 3.5 0 00-1.025-2.475l-3.122-3.12A3.5 3.5 0 0014.379 2H8.5A3.5 3.5 0 005 5.5v2h2v-2z" />
          <path fillRule="evenodd" d="M12.5 6a1 1 0 011 1v10.5a1 1 0 01-1 1h-9a1 1 0 01-1-1V7a1 1 0 011-1h9zM4 8.5V17h8V8.5H4z" clipRule="evenodd" />
        </svg>
      )}
    </button>
  )
}

interface ChatMessageProps {
  message: ChatMessageType
  isStreaming?: boolean
}

export function ChatMessage({ message, isStreaming }: ChatMessageProps) {
  const isUser = message.role === 'user'
  const isError = message.role === 'assistant' && message.content.startsWith('Error:')
  const showSources = !isUser && !isError && message.sources && message.sources.length > 0

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-8 px-2`}>
      <div className={`relative max-w-[85%] group ${!isUser ? 'w-full' : ''}`}>
        {/* 装饰性背景阴影 (仅 User) */}
        {isUser && (
          <div className="absolute inset-0 transform translate-x-1.5 translate-y-1.5 -skew-x-6 border-2 bg-red-600 border-red-600" />
        )}

        {/* 气泡主体 */}
        <div
          className={`relative px-6 py-4 border-2 transition-transform duration-200 ${
            isUser
              ? 'transform -skew-x-6 hover:-translate-y-0.5 bg-black text-white border-white'
              : isError
                ? 'bg-red-900/10 text-red-500 border-red-900'
                : 'bg-[#1a1a1a] text-gray-200 border-gray-700'
          }`}
        >
          {/* Copy Button (Assistant Only) */}
          {!isUser && !isError && <CopyButton content={message.content} />}

          {/* 内容容器 (User 需要反向 skew, Assistant 不需要) */}
          <div className={isUser ? 'transform skew-x-6' : ''}>
            <div className="font-sans break-words text-sm font-medium tracking-wide">
              {isUser ? (
                <span className="whitespace-pre-wrap">{message.content}</span>
              ) : (
                <div className="markdown-content">
                  <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                      // Headers - Clean style for assistant
                      h1: ({ children }) => (
                        <h1 className="text-xl font-bold mt-4 mb-2 text-white border-b border-gray-700 pb-1">
                          {children}
                        </h1>
                      ),
                      h2: ({ children }) => (
                        <h2 className="text-lg font-bold mt-3 mb-2 text-white">
                          {children}
                        </h2>
                      ),
                      h3: ({ children }) => (
                        <h3 className="text-base font-bold mt-2 mb-1 text-neon-blue">
                          {children}
                        </h3>
                      ),
                      // Paragraphs
                      p: ({ children }) => <p className="mb-2 last:mb-0 leading-relaxed text-gray-300">{children}</p>,
                      // Lists
                      ul: ({ children }) => (
                        <ul className="list-disc pl-5 mb-2 space-y-1 text-gray-300">
                          {children}
                        </ul>
                      ),
                      ol: ({ children }) => (
                        <ol className="list-decimal pl-5 mb-2 text-gray-300">
                          {children}
                        </ol>
                      ),
                      li: ({ children }) => (
                        <li className="mb-1">
                          {children}
                        </li>
                      ),
                      // Code
                      code: ({ className, children }) => {
                        const isInline = !className
                        return isInline ? (
                          <code className="bg-gray-800 text-neon-blue px-1.5 py-0.5 rounded font-mono text-xs border border-gray-700">
                            {children}
                          </code>
                        ) : (
                          <div className="my-3 rounded-md overflow-hidden border border-gray-700">
                            <code className="block bg-[#0d0d0d] p-3 font-mono text-xs overflow-x-auto text-gray-300">
                              {children}
                            </code>
                          </div>
                        )
                      },
                      pre: ({ children }) => (
                        <pre className="my-2 overflow-x-auto">
                          {children}
                        </pre>
                      ),
                      // Links
                      a: ({ href, children }) => (
                        <a
                          href={href}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-neon-blue hover:text-white underline transition-colors"
                        >
                          {children}
                        </a>
                      ),
                      // Blockquotes
                      blockquote: ({ children }) => (
                        <blockquote className="border-l-4 border-gray-600 pl-4 my-2 italic text-gray-500">
                          {children}
                        </blockquote>
                      ),
                      // Tables
                      table: ({ children }) => (
                        <div className="overflow-x-auto my-2 border border-gray-700 rounded-sm">
                          <table className="border-collapse w-full text-sm">
                            {children}
                          </table>
                        </div>
                      ),
                      th: ({ children }) => (
                        <th className="bg-gray-800 border-b border-gray-700 px-3 py-2 text-left font-bold text-gray-200">
                          {children}
                        </th>
                      ),
                      td: ({ children }) => (
                        <td className="border-b border-gray-800 px-3 py-2 text-gray-400">{children}</td>
                      ),
                      // Horizontal rule
                      hr: () => <hr className="border-gray-700 my-4" />,
                      // Strong and emphasis
                      strong: ({ children }) => (
                        <strong className="font-bold text-white">{children}</strong>
                      ),
                      em: ({ children }) => <em className="italic text-gray-400">{children}</em>,
                    }}
                  >
                    {message.content}
                  </ReactMarkdown>
                </div>
              )}
              {isStreaming && (
                <span className="inline-block w-2 h-4 bg-neon-blue ml-1 animate-pulse" />
              )}
              {showSources && <SourcesList sources={message.sources!} />}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
