"use client";
import { useState, useEffect, useRef } from "react";
import { useTheme } from "next-themes";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Marquee } from "@/components/magicui/marquee";
import Image from "next/image";
import { QuestionCard } from "@/components/custom/question-card";
import { ChatMessage } from "@/components/chat/chat-message";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import { AlertCircleIcon } from "lucide-react";

const questions = [
    { category: "Connector", question: "How to setup Snowflake connector?" },
    { category: "Connector", question: "How to delete a connection?" },
    { category: "API/SDK", question: "Give code to change asset description" },
    { category: "SSO", question: "Setup SSO with Azure AD" },
    { category: "Lineage", question: "Export lineage for audit" },
    {
      category: "Best practices",
      question: "Create custom role for data stewards",
    },
  ];

  const firstRow = questions.slice(0, questions.length / 2);
  const secondRow = questions.slice(questions.length / 2);

  // Helper function to convert generic status messages to user-friendly ones
  const getFriendlyStatusMessage = (node: string, message: string) => {
    const statusMap: { [key: string]: string } = {
      'classify': 'Understanding your question...',
      'agent': 'Preparing response...',
      'document_search': 'Searching knowledge base...',
      'finalize_response': 'Finalizing answer...'
    };
    
    // If we have a custom message for this node, use it
    if (statusMap[node]) {
      return statusMap[node];
    }
    
    // Otherwise, clean up the generic message
    return message.replace(/Processing\s+/i, '').replace(/Completed\s+/i, 'Finished ').replace(/\.\.\./g, '...');
  };

export default function Home() {
  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL;
  const { theme } = useTheme();
  const [messages, setMessages] = useState([] as any);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [chatStarted, setChatStarted] = useState(false);
  const [currentStatus, setCurrentStatus] = useState("");
  const [citations, setCitations] = useState([] as any);
  const [mode, setMode] = useState<'chat' | 'bulk'>('chat');
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [ticketData, setTicketData] = useState<any[]>([]);
  const [processedCount, setProcessedCount] = useState(0);
  const [totalCount, setTotalCount] = useState(0);
  const [bulkResults, setBulkResults] = useState<any[]>([]);
  const [internalAnalysis, setInternalAnalysis] = useState<any>(null);
  const [showInternalView, setShowInternalView] = useState(false);
  const [sessionId, setSessionId] = useState<string>("");
  const [rateLimitTimer, setRateLimitTimer] = useState<NodeJS.Timeout | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  
  const isDarkMode = theme === 'dark';

  // Generate a unique session ID
  const generateSessionId = () => {
    return crypto.randomUUID();
  };

  // Initialize session ID on component mount
  useEffect(() => {
    if (!sessionId) {
      setSessionId(generateSessionId());
    }
  }, [sessionId]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    // Validate file type
    if (!file.name.endsWith('.json')) {
      alert('Please upload a JSON file');
      return;
    }

    // Validate file size (2MB max)
    const maxSize = 2 * 1024 * 1024; // 2MB in bytes
    if (file.size > maxSize) {
      alert('File size must be less than 2MB');
      return;
    }

    try {
      const text = await file.text();
      const data = JSON.parse(text);
      
      // Validate JSON structure
      if (!Array.isArray(data)) {
        alert('JSON file must contain an array of tickets');
        return;
      }

      // Validate each ticket has required fields
      const invalidTickets = data.filter((ticket, index) => {
        if (!ticket.id || !ticket.body) {
          console.warn(`Ticket at index ${index} missing id or body:`, ticket);
          return true;
        }
        return false;
      });

      if (invalidTickets.length > 0) {
        alert(`${invalidTickets.length} tickets are missing required fields (id, body)`);
        return;
      }

      setUploadedFile(file);
      setTicketData(data);
      setTotalCount(data.length);
      setProcessedCount(0);
      setBulkResults([]);
      setCurrentStatus(`File uploaded: ${data.length} tickets. Starting processing...`);
      
      // Auto-start processing
      setTimeout(() => {
        startBulkProcessing(data);
      }, 500);
      
    } catch (error) {
      alert('Invalid JSON file format');
      console.error('JSON parse error:', error);
    }
  };

  const processBatch = async (batch: any[], batchIndex: number) => {
    try {
      // Create a FormData object with the JSON file
      const formData = new FormData();
      const jsonBlob = new Blob([JSON.stringify(batch)], { type: 'application/json' });
      formData.append('file', jsonBlob, `batch_${batchIndex}.json`);

      const response = await fetch(`${backendUrl}/bulk/`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      // Handle streaming response
      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      const results = [];

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          const chunk = decoder.decode(value, { stream: true });
          const lines = chunk.split('\n');

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const data = line.slice(6).trim();
              if (data) {
                try {
                  const parsed = JSON.parse(data);
                  results.push(parsed);
                } catch (parseError) {
                  console.warn('Failed to parse SSE data:', data);
                }
              }
            }
          }
        }
      }

      return { results, batch_index: batchIndex };
      
    } catch (error) {
      console.error(`Error processing batch ${batchIndex}:`, error);
      return { error: error.message, batch_index: batchIndex };
    }
  };

  const startBulkProcessing = async (data: any[]) => {
    setIsLoading(true);
    setCurrentStatus('Starting batch processing...');
    setBulkResults([]);
    setProcessedCount(0);

    const batchSize = 5;
    const batches = [];
    
    // Split tickets into batches of 5
    for (let i = 0; i < data.length; i += batchSize) {
      batches.push(data.slice(i, i + batchSize));
    }

    // Process batches sequentially
    for (let i = 0; i < batches.length; i++) {
      const batchStatus = `Processing batch ${i + 1} of ${batches.length} (${batches[i].length} tickets)...`;
      setCurrentStatus(batchStatus);
      console.log(batchStatus); // Also log to console for debugging
      
      const batchStartTime = Date.now();
      const batchResult = await processBatch(batches[i], i);
      const batchEndTime = Date.now();
      
      console.log(`Batch ${i + 1} completed in ${batchEndTime - batchStartTime}ms:`, batchResult);
      
      // Process the results from the batch
      if (batchResult.results) {
        setBulkResults(prev => [...prev, ...batchResult.results]);
        setProcessedCount(prev => prev + batchResult.results.length);
        setCurrentStatus(`Batch ${i + 1} completed successfully. ${batchResult.results.length} tickets processed.`);
      } else if (batchResult.error) {
        setCurrentStatus(`Batch ${i + 1} failed: ${batchResult.error}. Continuing with next batch...`);
        await new Promise(resolve => setTimeout(resolve, 1000)); // Show error longer
      } else {
        setCurrentStatus(`Batch ${i + 1} completed with no results.`);
        await new Promise(resolve => setTimeout(resolve, 500));
      }
      
      // Small delay between batches to avoid overwhelming the server
      if (i < batches.length - 1) {
        await new Promise(resolve => setTimeout(resolve, 200));
      }
    }

    setIsLoading(false);
    setCurrentStatus(`Processing complete: ${data.length} tickets processed`);
  };

  const handleBulkProcess = async () => {
    if (ticketData.length === 0) {
      alert('Please upload a JSON file first');
      return;
    }

    await startBulkProcessing(ticketData);
  };

  const handleSendMessage = async (message: string) => {
    if (!message.trim()) return;

    setChatStarted(true);
    const userMessage = { role: "user", content: message, timestamp: new Date().toLocaleTimeString() };
    setMessages(prev => [...prev, userMessage]);
    setInput("");
    setIsLoading(true);
    setCurrentStatus("Understanding your question...");
    setCitations([]);
    setInternalAnalysis(null);
    setShowInternalView(false);

    // Clear any existing rate limit timer
    if (rateLimitTimer) {
      clearTimeout(rateLimitTimer);
    }

    // Set up rate limit detection timer (15 seconds)
    const timer = setTimeout(() => {
      if (isLoading) {
        const rateLimitMessage = "As we are using free tier of Gemini API in backend, the request got rate limited, please try after 60 seconds 🙏";
        const assistantMessage = { role: "assistant", content: rateLimitMessage };
        setMessages(prev => [...prev, assistantMessage]);
        setIsLoading(false);
        setCurrentStatus("");
      }
    }, 15000);

    setRateLimitTimer(timer);

    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 300000); // 5 minute timeout

      const response = await fetch(`${backendUrl}/chat/`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ query: message, session_id: sessionId }),
        signal: controller.signal,
      });

      clearTimeout(timeoutId);
      
      // Clear rate limit timer since we got a response
      if (rateLimitTimer) {
        clearTimeout(rateLimitTimer);
        setRateLimitTimer(null);
      }

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      if (reader) {
        while (true) {
          const { done, value } = await reader.read();
          if (done) {
            // Stream ended - process any remaining buffer
            if (buffer.trim()) {
              const line = buffer.trim();
              if (line.startsWith('data: ')) {
                const data = line.slice(6).trim();
                if (data && data !== '[DONE]') {
                  try {
                    const parsed = JSON.parse(data);
                    console.log('Final parsed SSE:', parsed);
                    // Process the final message here
                    if (parsed.type === 'final_result' && parsed.data) {
                      console.log('Processing final buffer message:', parsed);
                      // Handle final result from buffer
                      const responseData = parsed.data;
                      
                      if (responseData.internal_analysis) {
                        setInternalAnalysis({
                          classification: responseData.internal_analysis.classification,
                          timestamp: new Date().toLocaleTimeString()
                        });
                      }
                      
                      let finalContent = "";
                      let responseSources = [];
                      
                      if (responseData.final_response?.rag_response?.answer) {
                        finalContent = responseData.final_response.rag_response.answer;
                        responseSources = responseData.final_response.rag_response.sources || [];
                      } else if (responseData.final_response?.routing_response?.message) {
                        finalContent = responseData.final_response.routing_response.message;
                      }
                      
                      if (finalContent) {
                        console.log('Adding final buffer message to chat:', finalContent);
                        const assistantMessage = { role: "assistant", content: finalContent };
                        setMessages(prev => [...prev, assistantMessage]);
                        
                        if (responseSources.length > 0) {
                          setCitations(responseSources);
                        }
                      }
                    }
                  } catch (parseError) {
                    console.log('JSON parse error in buffer:', parseError, 'for data:', data);
                  }
                }
              }
            }
            
            if (isLoading) {
              setCurrentStatus("Processing complete");
              setIsLoading(false);
              
              // Clear rate limit timer when processing completes
              if (rateLimitTimer) {
                clearTimeout(rateLimitTimer);
                setRateLimitTimer(null);
              }
            }
            break;
          }

          const chunk = decoder.decode(value, { stream: true });
          buffer += chunk;
          const lines = buffer.split('\n');
          
          // Keep the last line in buffer in case it's incomplete
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              const data = line.slice(6).trim();
              
              if (data === '[DONE]') {
                setIsLoading(false);
                setCurrentStatus("");
                
                // Clear rate limit timer when stream ends
                if (rateLimitTimer) {
                  clearTimeout(rateLimitTimer);
                  setRateLimitTimer(null);
                }
                continue;
              }

              // Debug: Log all data before parsing
              console.log('Raw SSE data:', data);

              // Skip empty data
              if (!data) {
                continue;
              }

              try {
                const parsed = JSON.parse(data);
                console.log('Parsed SSE:', parsed);
                
                // Debug: Check if this is the final_result message
                if (parsed.type === 'final_result') {
                  console.log('FOUND final_result message!', parsed);
                }
                
                // Handle the new backend response structure
                if (parsed.internal_analysis && parsed.final_response) {
                  // Complete ChatbotResponse received
                  setCurrentStatus("");
                  setIsLoading(false);
                  
                  // Clear rate limit timer when final response received
                  if (rateLimitTimer) {
                    clearTimeout(rateLimitTimer);
                    setRateLimitTimer(null);
                  }
                  
                  // Store internal analysis for internal view
                  setInternalAnalysis({
                    classification: parsed.internal_analysis.classification,
                    timestamp: new Date().toLocaleTimeString()
                  });
                  
                  // Handle final response
                  let finalContent = "";
                  let responseSources = [];
                  
                  if (parsed.final_response.response_type === "rag_answer" && parsed.final_response.rag_response) {
                    finalContent = parsed.final_response.rag_response.answer;
                    responseSources = parsed.final_response.rag_response.sources || [];
                  } else if (parsed.final_response.response_type === "routing_message" && parsed.final_response.routing_response) {
                    finalContent = parsed.final_response.routing_response.message;
                  }
                  
                  if (finalContent) {
                    const assistantMessage = { role: "assistant", content: finalContent };
                    setMessages(prev => [...prev, assistantMessage]);
                    
                    // Handle citations
                    if (responseSources.length > 0) {
                      setCitations(responseSources);
                    }
                  }
                } else if (parsed.type === 'node_complete') {
                  // Update status message with user-friendly text
                  if (parsed.message) {
                    const friendlyMessage = getFriendlyStatusMessage(parsed.node, parsed.message);
                    setCurrentStatus(friendlyMessage);
                  }
                  
                  // Handle classification data - store for internal view
                  if (parsed.node === 'classify' && parsed.data) {
                    setInternalAnalysis({
                      classification: parsed.data,
                      timestamp: new Date().toLocaleTimeString()
                    });
                  }
                } else if (parsed.type === 'final_response' || parsed.type === 'final_result') {
                  // Final response received
                  setCurrentStatus("");
                  setIsLoading(false);
                  
                  // Clear rate limit timer when final response received
                  if (rateLimitTimer) {
                    clearTimeout(rateLimitTimer);
                    setRateLimitTimer(null);
                  }
                  
                  let finalContent = "";
                  let responseSources = [];
                  
                  if (parsed.type === 'final_result' && parsed.data) {
                    // Handle the complete response from backend
                    const responseData = parsed.data;
                    console.log('Final result data:', responseData);
                    
                    // Store internal analysis for internal view
                    if (responseData.internal_analysis) {
                      setInternalAnalysis({
                        classification: responseData.internal_analysis.classification,
                        timestamp: new Date().toLocaleTimeString()
                      });
                    }
                    
                    // Extract final response content
                    if (responseData.final_response?.rag_response?.answer) {
                      finalContent = responseData.final_response.rag_response.answer;
                      responseSources = responseData.final_response.rag_response.sources || [];
                      console.log('Extracted final content:', finalContent);
                    } else if (responseData.final_response?.routing_response?.message) {
                      finalContent = responseData.final_response.routing_response.message;
                      console.log('Extracted routing content:', finalContent);
                    }
                  } else {
                    finalContent = parsed.data || parsed.content || parsed.response?.data;
                  }
                  
                  if (finalContent) {
                    console.log('Adding final message to chat:', finalContent);
                    const assistantMessage = { role: "assistant", content: finalContent };
                    setMessages(prev => [...prev, assistantMessage]);
                    
                    // Handle citations
                    if (responseSources.length > 0) {
                      setCitations(responseSources);
                    }
                  } else {
                    console.log('No final content found in final_result');
                  }
                  
                  // Handle citations if present in other formats
                  if (parsed.citations || parsed.response?.citations) {
                    setCitations(parsed.citations || parsed.response.citations);
                  }
                } else if (parsed.response && parsed.response.data) {
                  // Another format for final response
                  setCurrentStatus("");
                  setIsLoading(false);
                  
                  // Clear rate limit timer when final response received
                  if (rateLimitTimer) {
                    clearTimeout(rateLimitTimer);
                    setRateLimitTimer(null);
                  }
                  
                  const assistantMessage = { role: "assistant", content: parsed.response.data };
                  setMessages(prev => [...prev, assistantMessage]);
                  
                  if (parsed.response.citations) {
                    setCitations(parsed.response.citations);
                  }
                }
              } catch (parseError) {
                // Skip malformed JSON
                console.log('JSON parse error:', parseError, 'for data:', data);
                continue;
              }
            }
          }
        }
      }
    } catch (error) {
      console.error("Error sending message:", error);
      
      // Clear rate limit timer on error
      if (rateLimitTimer) {
        clearTimeout(rateLimitTimer);
        setRateLimitTimer(null);
      }
      
      let errorMessage = "Sorry, something went wrong.";
      
      if (error instanceof Error) {
        if (error.name === 'AbortError') {
          errorMessage = "Request timed out. Please try again.";
        } else if (error.message.includes('Failed to fetch')) {
          errorMessage = "Unable to connect to the server. Please check if the backend is running.";
        } else if (error.message.includes('HTTP')) {
          errorMessage = `Server error: ${error.message}`;
        }
      }
      
      const assistantMessage = { role: "assistant", content: errorMessage };
      setMessages(prev => [...prev, assistantMessage]);
    } finally {
      setIsLoading(false);
      setCurrentStatus("");
      
      // Clear rate limit timer in finally block as well
      if (rateLimitTimer) {
        clearTimeout(rateLimitTimer);
        setRateLimitTimer(null);
      }
    }
  };

  return (
    <main className={`min-h-screen flex flex-col ${
      isDarkMode ? 'bg-neutral-950' : 'bg-white'
    } ${chatStarted || mode === 'bulk' ? 'pt-20 px-6' : 'justify-center items-center p-6'}`}>
      <title>Nora - Your Atlan Assistant</title>
      <div className={`w-full transition-all duration-500 ease-out ${chatStarted || mode === 'bulk' ? 'max-w-4xl mx-auto' : 'max-w-3xl'}`}>
        <Card className={`relative z-10 w-full transition-all duration-500 transform ${
          isDarkMode ? 'bg-neutral-950 border-neutral-800' : 'bg-white border-gray-200'
        } ${chatStarted || mode === 'bulk' ? 'scale-100' : 'scale-100 hover:scale-105'}`}>
        <CardHeader className={`flex flex-col items-center text-center transition-all duration-500 ${chatStarted || mode === 'bulk' ? 'flex-row items-center pb-3' : 'pb-6'}`}>
          <div className="relative">
            <Image
              src="/images/nora.webp"
              alt="Nora"
              width={chatStarted || mode === 'bulk' ? 40 : 80}
              height={chatStarted || mode === 'bulk' ? 40 : 80}
              className={`rounded-full transition-all duration-500 ${chatStarted || mode === 'bulk' ? '' : 'animate-pulse'}`}
            />
            {(chatStarted || mode === 'bulk') && (
              <div className="absolute -bottom-1 -right-1 w-3 h-3 bg-green-500 rounded-full border-2 border-white"></div>
            )}
          </div>
          {(chatStarted || mode === 'bulk') && (
            <div className="ml-3 text-left">
              <h1 className={`text-base font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>Nora</h1>
              <p className={`text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
                {mode === 'bulk' ? 'Bulk Ticket Processor' : 'Your Atlan Assistant'}
              </p>
            </div>
          )}
          {!chatStarted && mode === 'chat' && (
            <div className="text-center">
              <h1 className={`text-2xl font-bold mt-4 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>Nora</h1>
              <p className={`${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}>Your Atlan Assistant</p>
            </div>
          )}
          
          {/* Mode Toggle */}
          <div className={`${chatStarted || mode === 'bulk' ? 'ml-auto' : 'mt-6'} flex bg-gray-100 rounded-lg p-1`}>
              <button
                onClick={() => {
                  setMode('chat');
                  setChatStarted(false);
                  setUploadedFile(null);
                  setTicketData([]);
                  setBulkResults([]);
                  setCurrentStatus("");
                }}
                className={`px-4 py-2 rounded-md text-sm font-medium transition-all ${
                  mode === 'chat' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-600 hover:text-gray-900'
                }`}
              >
                Chat Mode
              </button>
              <button
                onClick={() => {
                  setMode('bulk');
                  setChatStarted(false);
                  setMessages([]);
                  setCurrentStatus("");
                }}
                className={`px-4 py-2 rounded-md text-sm font-medium transition-all ${
                  mode === 'bulk' ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-600 hover:text-gray-900'
                }`}
              >
                Bulk Upload
              </button>
            </div>
        </CardHeader>
        <CardContent className={chatStarted || mode === 'bulk' ? 'pt-4' : ''}>
          {mode === 'bulk' ? (
            <div className="space-y-6">
              {/* File Upload Section */}
              <div className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center">
                <input
                  type="file"
                  accept=".json"
                  onChange={handleFileUpload}
                  className="hidden"
                  id="json-upload"
                />
                <label htmlFor="json-upload" className="cursor-pointer">
                  <div className="space-y-4">
                  <Alert variant="destructive">
                    <AlertCircleIcon />
                    <AlertTitle>Please at max 5-7 tickets in a file.</AlertTitle>
                    <AlertDescription>
                      <p>We are using free tier of Gemini API in backend, so please at max 5-7 tickets in a file.</p>
                    </AlertDescription>
                  </Alert>
                    <div className="mx-auto w-12 h-12 bg-blue-50 rounded-lg flex items-center justify-center">
                      <svg className="w-6 h-6 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                      </svg>
                    </div>
                    <div>
                      <h3 className="text-lg font-medium text-gray-900">Upload JSON File</h3>
                      <p className="text-sm text-gray-500 mt-1">
                        Select a JSON file containing ticket data (max 2MB)
                      </p>
                    </div>
                  </div>
                </label>
              </div>

              {/* File Info and Progress */}
              {uploadedFile && (
                <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
                  <div className="flex items-center justify-between mb-2">
                    <h4 className="font-medium text-blue-900">File Information</h4>
                    <span className="text-sm text-blue-700">
                      {(uploadedFile.size / 1024).toFixed(1)} KB
                    </span>
                  </div>
                  <p className="text-sm text-blue-800 mb-3">{uploadedFile.name}</p>
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-blue-900">
                      {totalCount} tickets ready
                    </span>
                    {processedCount > 0 && (
                      <span className="text-sm text-blue-700">
                        {processedCount} / {totalCount} processed
                      </span>
                    )}
                  </div>
                  {totalCount > 0 && (
                    <div className="mt-2 w-full bg-blue-200 rounded-full h-2">
                      <div 
                        className="bg-blue-600 h-2 rounded-full transition-all duration-300"
                        style={{ width: `${(processedCount / totalCount) * 100}%` }}
                      ></div>
                    </div>
                  )}
                </div>
              )}

              {/* Status and Process Button */}
              {currentStatus && (
                <div className={`border rounded-lg p-4 ${
                  isLoading 
                    ? isDarkMode ? 'bg-blue-900/20 border-blue-700' : 'bg-blue-50 border-blue-200'
                    : isDarkMode ? 'bg-neutral-900 border-neutral-800' : 'bg-gray-50 border-gray-200'
                }`}>
                  <div className="flex items-center space-x-2">
                    {isLoading && (
                      <>
                        <div className="w-2 h-2 bg-blue-500 rounded-full animate-bounce"></div>
                        <div className="w-2 h-2 bg-blue-500 rounded-full animate-bounce delay-75"></div>
                        <div className="w-2 h-2 bg-blue-500 rounded-full animate-bounce delay-150"></div>
                      </>
                    )}
                    <p className={`text-sm ${
                      isDarkMode ? 'text-gray-200' : 'text-gray-700'
                    }`}>{currentStatus}</p>
                  </div>
                </div>
              )}

              {ticketData.length > 0 && (
                <div className="flex space-x-3">
                  <Button 
                    onClick={handleBulkProcess}
                    disabled={isLoading}
                    className="flex-1"
                  >
                    {isLoading ? 'Processing...' : `Process ${ticketData.length} Tickets`}
                  </Button>
                  <Button 
                    variant="outline"
                    onClick={() => {
                      setUploadedFile(null);
                      setTicketData([]);
                      setBulkResults([]);
                      setCurrentStatus("");
                      setProcessedCount(0);
                      setTotalCount(0);
                    }}
                  >
                    Clear
                  </Button>
                </div>
              )}

              {/* Results Section */}
              {bulkResults.length > 0 && (
                <div className="border rounded-lg p-4">
                  <h4 className="font-medium text-gray-900 mb-3">Processing Results</h4>
                  <div className="space-y-2 max-h-64 overflow-y-auto">
                    {bulkResults.map((result, i) => (
                      <div key={i} className="text-sm p-2 bg-gray-50 rounded">
                        <div className="font-medium mb-1">Ticket ID: {result.id}</div>
                        {result.classification ? (
                          <div className="space-y-1 text-xs">
                            <div>
                              <span className="font-medium">Topics:</span> 
                              <span className="ml-2 text-green-600">
                                {result.classification.topic_tags?.join(', ') || 'N/A'}
                              </span>
                            </div>
                            <div>
                              <span className="font-medium">Sentiment:</span> 
                              <span className="ml-2 text-orange-600">
                                {result.classification.sentiment || 'N/A'}
                              </span>
                            </div>
                            <div>
                              <span className="font-medium">Priority:</span> 
                              <span className="ml-2 text-purple-600">
                                {result.classification.priority || 'N/A'}
                              </span>
                            </div>
                            {result.classification.reasoning && (
                              <div className="text-gray-600 mt-1">
                                <span className="font-medium">Reasoning:</span> {result.classification.reasoning}
                              </div>
                            )}
                          </div>
                        ) : (
                          <span className="text-red-600">Error processing ticket</span>
                        )}
                      </div>
                    ))}
                  </div>
                  <div className="mt-4 flex space-x-3">
                    <Button 
                      variant="outline" 
                      onClick={() => {
                        const dataStr = JSON.stringify(bulkResults, null, 2);
                        const dataBlob = new Blob([dataStr], {type: 'application/json'});
                        const url = URL.createObjectURL(dataBlob);
                        const link = document.createElement('a');
                        link.href = url;
                        link.download = `nora_bulk_results_${new Date().toISOString().split('T')[0]}.json`;
                        link.click();
                        URL.revokeObjectURL(url);
                      }}
                    >
                      Download Results
                    </Button>
                  </div>
                </div>
              )}
            </div>
          ) : chatStarted ? (
            <>
              {/* Toggle Button */}
              {internalAnalysis && (
                <div className="flex justify-end mb-2">
                  <Button 
                    variant="outline" 
                    size="sm"
                    onClick={() => setShowInternalView(!showInternalView)}
                    className="text-xs"
                  >
                    {showInternalView ? 'Show Final Response' : 'Show Internal Analysis'}
                  </Button>
                </div>
              )}

              {/* Internal Analysis View */}
              {showInternalView && internalAnalysis && (
                <div className={`p-3 rounded-lg border mb-2 ${
                  isDarkMode 
                    ? 'bg-neutral-950 border-neutral-800' 
                    : 'bg-gray-50 border-gray-200'
                }`}>
                  <h4 className="font-semibold text-sm mb-2 text-blue-600">Internal Analysis</h4>
                  <div className="space-y-2 text-xs">
                    {internalAnalysis.classification.topic_tags && (
                      <div>
                        <span className="font-medium">Topics:</span> 
                        <span className="ml-2 text-green-600">
                          {internalAnalysis.classification.topic_tags.join(', ')}
                        </span>
                      </div>
                    )}
                    {internalAnalysis.classification.sentiment && (
                      <div>
                        <span className="font-medium">Sentiment:</span> 
                        <span className="ml-2 text-orange-600">
                          {internalAnalysis.classification.sentiment}
                        </span>
                      </div>
                    )}
                    {internalAnalysis.classification.priority && (
                      <div>
                        <span className="font-medium">Priority:</span> 
                        <span className="ml-2 text-purple-600">
                          {internalAnalysis.classification.priority}
                        </span>
                      </div>
                    )}
                    <div className="text-gray-500 pt-1 border-t">
                      Analyzed at {internalAnalysis.timestamp}
                    </div>
                  </div>
                </div>
              )}

              <div className={`flex flex-col space-y-2 h-[24rem] overflow-y-auto p-3 rounded-lg border ${
                isDarkMode 
                  ? 'bg-neutral-950 border-neutral-800' 
                  : 'bg-white border-gray-200'
              }`} ref={messagesEndRef}>
              {messages.map((msg, i) => (
                <ChatMessage key={i} {...msg} isDarkMode={isDarkMode} />
              ))}
              {isLoading && (
                <div className="flex justify-start mb-3">
                  <div className="flex items-end space-x-2 max-w-[85%]">
                    <div className="w-7 h-7 rounded-full flex-shrink-0">
                      <Image src="/images/nora.webp" alt="Nora" width={28} height={28} className="rounded-full" />
                    </div>
                    <div className={`rounded-2xl px-3 py-2 border rounded-bl-md ${
                      isDarkMode 
                        ? 'bg-neutral-900 border-neutral-800' 
                        : 'bg-gray-100 border-gray-200'
                    }`}>
                      <div className="flex flex-col space-y-1">
                        <div className="flex items-center justify-center space-x-1">
                          <div className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce"></div>
                          <div className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce delay-75"></div>
                          <div className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce delay-150"></div>
                        </div>
                        {currentStatus && (
                          <span className={`text-xs text-center ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
                            {currentStatus}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              )}
              {citations.length > 0 && (
                <div className="mt-3 space-y-2">
                  <div className="flex items-center space-x-2 mb-2">
                    <svg className="w-4 h-4 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                    </svg>
                    <h4 className={`text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}>
                      Sources ({citations.length})
                    </h4>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {citations.map((citation: any, i: number) => (
                      <div key={i} className={`inline-flex items-center space-x-2 px-3 py-1.5 rounded-full text-xs transition-all hover:scale-105 ${
                        isDarkMode 
                          ? 'bg-blue-900/30 border border-blue-700/50 text-blue-300' 
                          : 'bg-blue-50 border border-blue-200 text-blue-700'
                      }`}>
                        <svg className="w-3 h-3 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                        </svg>
                        <span className="font-medium truncate max-w-32">
                          {citation.title || citation.name || `Doc ${i + 1}`}
                        </span>
                        {citation.url && (
                          <a 
                            href={citation.url} 
                            target="_blank" 
                            rel="noopener noreferrer" 
                            className="hover:scale-110 transition-transform"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                            </svg>
                          </a>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
            </>
          ) : (
            <div className="relative flex w-full flex-col items-center justify-center overflow-hidden">
              <Marquee pauseOnHover className="[--duration:30s]">
                {firstRow.map((question, i) => (
                  <QuestionCard key={i} {...question} onClick={() => handleSendMessage(question.question)} />
                ))}
              </Marquee>
              <Marquee reverse pauseOnHover className="[--duration:30s]">
                {secondRow.map((question, i) => (
                  <QuestionCard key={i} {...question} onClick={() => handleSendMessage(question.question)} />
                ))}
              </Marquee>
              <div className="pointer-events-none absolute inset-y-0 left-0 w-1/4 bg-gradient-to-r from-background"></div>
              <div className="pointer-events-none absolute inset-y-0 right-0 w-1/4 bg-gradient-to-l from-background"></div>
            </div>
          )}
          
          {/* Chat Input - Only show in chat mode */}
          {mode === 'chat' && (
            <div className="flex w-full items-center space-x-2 mt-4">
              <Input
                type="text"
                placeholder="Ask Nora anything..."
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && !isLoading && handleSendMessage(input)}
                disabled={isLoading}
              />
              <Button 
                type="submit" 
                onClick={() => handleSendMessage(input)}
                disabled={isLoading || !input.trim()}
              >
                {isLoading ? 'Processing...' : 'Send'}
              </Button>
              {chatStarted && <Button variant="outline" onClick={() => {setMessages([]); setChatStarted(false); setCurrentStatus(""); setIsLoading(false);}} disabled={isLoading}>Clear Chat</Button>}
            </div>
          )}
        </CardContent>
      </Card>
      </div>
    </main>
  );
}
