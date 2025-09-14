"use client";

import Image from "next/image";
import { User } from 'lucide-react';
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface ChatMessageProps {
  role: "user" | "assistant";
  content: string;
  isLoading?: boolean;
  timestamp?: string;
  isDarkMode?: boolean;
}

export const ChatMessage = ({ role, content, isLoading, timestamp, isDarkMode }: ChatMessageProps) => {
  const avatar =
    role === 'assistant' ? (
      <Image
        src="/images/nora.webp"
        alt="Nora"
        width={28}
        height={28}
        className="rounded-full flex-shrink-0"
      />
    ) : (
      <div className="w-7 h-7 rounded-full bg-blue-500 flex items-center justify-center flex-shrink-0">
        <User className="h-4 w-4 text-white" />
      </div>
    );

  const messageBubble = (
    <div
      className={`max-w-[75%] rounded-2xl px-3 py-2 shadow-sm text-sm ${
        role === 'user'
          ? 'bg-blue-500 text-white ml-auto rounded-br-md'
          : isDarkMode 
            ? 'bg-neutral-700 text-neutral-100 border border-neutral-600 rounded-bl-md'
            : 'bg-gray-100 text-gray-800 border border-gray-200 rounded-bl-md'
      }`}
    >
      {isLoading ? (
        <div className="flex items-center space-x-1">
          <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce"></div>
          <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce delay-75"></div>
          <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce delay-150"></div>
        </div>
      ) : (
        <div className="prose prose-sm max-w-none">
          <ReactMarkdown 
            remarkPlugins={[remarkGfm]}
            components={{
              p: ({children}) => <p className="mb-2 last:mb-0">{children}</p>,
              code: ({children}) => <code className={`px-1 py-0.5 rounded text-xs ${
                role === 'user' 
                  ? 'bg-blue-600' 
                  : isDarkMode 
                    ? 'bg-neutral-600 text-neutral-200'
                    : 'bg-gray-200 text-gray-800'
              }`}>{children}</code>
            }}
          >{content}</ReactMarkdown>
        </div>
      )}
      {timestamp && role === 'user' && (
        <div className="text-xs mt-1 opacity-70 text-blue-100 text-right">
          {timestamp}
        </div>
      )}
    </div>
  );

  if (role === 'user') {
    return (
      <div className="flex justify-end mb-3 animate-slide-up">
        <div className="flex items-end space-x-1.5 max-w-[90%]">
          {messageBubble}
          {avatar}
        </div>
      </div>
    );
  } else {
    return (
      <div className="flex justify-start mb-3 animate-slide-up">
        <div className="flex items-end space-x-1.5 max-w-[90%]">
          {avatar}
          {messageBubble}
        </div>
      </div>
    );
  }
};