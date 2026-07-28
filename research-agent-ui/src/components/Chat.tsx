import { useState, useRef, useEffect } from 'react';
import { submitResearch } from '../api';
import { MessageBubble } from './MessageBubble';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
}

interface ChatProps {
  username: string;
  onLogout: () => void;
}

export function Chat({ username, onLogout }: ChatProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | undefined>();
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const task = input.trim();
    if (!task || loading) return;

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: 'user',
      content: task,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setLoading(true);

    try {
      const response = await submitResearch(task, sessionId);
      setSessionId(response.sessionId);

      const assistantMsg: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: response.report,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err: unknown) {
      const errorMsg: Message = {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: `Error: ${err instanceof Error ? err.message : 'Something went wrong'}`,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setLoading(false);
    }
  };

  const handleNewSession = () => {
    setMessages([]);
    setSessionId(undefined);
  };

  return (
    <div className="chat-container">
      <header className="chat-header">
        <div className="header-left">
          <h1>Research Agent</h1>
          {sessionId && <span className="session-badge">Session active</span>}
        </div>
        <div className="header-right">
          <button className="btn-secondary" onClick={handleNewSession}>
            New Session
          </button>
          <span className="username">{username}</span>
          <button className="btn-secondary" onClick={onLogout}>
            Logout
          </button>
        </div>
      </header>

      <main className="messages-area">
        {messages.length === 0 && (
          <div className="empty-state">
            <h2>What would you like to research?</h2>
            <p>Ask a question and the agent will search the web, analyze findings, and produce a structured report.</p>
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
        {loading && (
          <div className="thinking">
            <div className="thinking-dots">
              <span></span><span></span><span></span>
            </div>
            <p>Researching... this may take up to 2 minutes</p>
            <button className="btn-cancel" onClick={() => window.location.reload()}>
              Cancel
            </button>
          </div>
        )}
        <div ref={messagesEndRef} />
      </main>

      <form className="input-area" onSubmit={handleSubmit}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a research question..."
          disabled={loading}
          aria-label="Research question"
        />
        <button type="submit" disabled={loading || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}
