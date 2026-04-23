/**
 * Chat component — only rendered when USE_LLM = True in routes.py.
 *
 * Shows a message history and a chat input bar at the bottom.
 * When the backend returns a search_term event, it calls onSearchTerm
 * to update the search bar and results above.
 */
import { useState, useRef, useEffect } from 'react'
interface Message {
  text: string
  isUser: boolean
}

interface ChatProps {
  onSearchTerm: (term: string) => void
  minimized?: boolean
}

const MAX_MESSAGE_LENGTH = 150

function Chat({ onSearchTerm, minimized = false }: ChatProps): JSX.Element {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState<string>('')
  const [loading, setLoading] = useState<boolean>(false)
  const [isOpen, setIsOpen] = useState<boolean>(!minimized)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (minimized) {
      setIsOpen(false)
    } else {
      setIsOpen(true)
    }
  }, [minimized])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const sendMessage = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault()
    const text = input.trim()
    if (!text || loading || text.length > MAX_MESSAGE_LENGTH) return

    setMessages(prev => [...prev, { text, isUser: true }])
    setInput('')
    setLoading(true)

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      })

      if (!response.ok) {
        const data = await response.json()
        setMessages(prev => [...prev, { text: 'Error: ' + (data.error || response.status), isUser: false }])
        setLoading(false)
        return
      }

      let assistantText = ''
      setMessages(prev => [...prev, { text: '', isUser: false }])
      setLoading(false)

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6))
              if (data.search_term !== undefined) {
                onSearchTerm(data.search_term)
              }
              if (data.error) {
                setMessages(prev => [...prev.slice(0, -1), { text: 'Error: ' + data.error, isUser: false }])
                return
              }
              if (data.content !== undefined) {
                assistantText += data.content
                setMessages(prev => [...prev.slice(0, -1), { text: assistantText, isUser: false }])
              }
            } catch { /* ignore malformed lines */ }
          }
        }
      }
    } catch {
      setMessages(prev => [...prev, { text: 'Something went wrong. Check the console.', isUser: false }])
      setLoading(false)
    }
  }

  if (!isOpen) {
    return (
      <button
        type="button"
        className="chat-fab"
        aria-label="Open AI chatbot"
        onClick={() => setIsOpen(true)}
      >
        <span className="chat-fab-icon" aria-hidden="true">💬</span>
      </button>
    )
  }

  return (
    <div className="chat-widget" role="complementary" aria-label="AI chat">
      <div
        className="chat-header"
        role="button"
        tabIndex={0}
        aria-label="Minimize chat"
        onClick={() => setIsOpen(false)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            setIsOpen(false)
          }
        }}
      >
        <div className="chat-header-title-wrap">
          <p className="chat-header-title">DermMatch AI Chatbot</p>
        </div>
        <button
          type="button"
          className="chat-close-button"
          aria-label="Close chat"
          onClick={() => setIsOpen(false)}
        >
          ×
        </button>
      </div>

      <div id="messages">
        {messages.map((msg, i) => (
          <div key={i} className={`message ${msg.isUser ? 'user' : 'assistant'}`}>
            <p>{msg.text}</p>
          </div>
        ))}
        {loading && (
          <div className="loading-indicator visible">
            <span className="loading-dot" />
            <span className="loading-dot" />
            <span className="loading-dot" />
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div className="chat-bar">
        <form className="input-row" onSubmit={sendMessage}>
          {/* <img src={SearchIcon} alt="" /> */}
          <textarea
            placeholder="Ask AI about a skincare product, ingredient, or skin concern..."
            value={input}
            onChange={e => setInput(e.target.value.slice(0, MAX_MESSAGE_LENGTH))}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                e.currentTarget.form?.requestSubmit()
              }
            }}
            disabled={loading}
            autoComplete="off"
            rows={2}
            maxLength={MAX_MESSAGE_LENGTH}
          />
          <button type="submit" disabled={loading}>Send</button>
        </form>
        <p className="chat-char-count">{input.length}/{MAX_MESSAGE_LENGTH}</p>
      </div>
    </div>
  )
}

export default Chat