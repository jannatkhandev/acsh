"""LangGraph agent for Atlan support query processing - REFACTORED."""
import json
import logging
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional, AsyncGenerator
from uuid import uuid4

from app.core.langgraph.prompts.manager import get_prompt_manager
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage, AIMessage
from langgraph.graph import StateGraph, MessagesState, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode, tools_condition
from typing_extensions import TypedDict, Annotated

from ..config import settings
from ...models import (
    TopicTag, Sentiment, Priority, Classification, 
    RAGResponse, RoutingMessage,
    InternalAnalysis, FinalResponse, ChatbotResponse
)
from .tools.document_search_tool import document_search_tool
from ...dependencies.classifier import get_classifier

logger = logging.getLogger(__name__)

class AgentState(TypedDict):
    """State for the LangGraph agent."""
    messages: Annotated[List, add_messages]
    user_query: str
    session_id: str
    classification: Optional[Classification]
    search_query: Optional[str]
    retrieved_docs: Optional[List[Dict[str, Any]]]
    routing_message: Optional[RoutingMessage]
    internal_analysis: Optional[InternalAnalysis]
    final_response: Optional[FinalResponse]

class NoraAgent:
    """Refactored Nora chatbot agent with clean LangGraph pipeline."""
    
    def __init__(self):
        self.tools = [document_search_tool]
        self.llm = ChatGoogleGenerativeAI(
            model=settings.default_model,
            google_api_key=settings.google_api_key,
            temperature=0.1
        )
        self.llm_with_tools = self.llm.bind_tools(self.tools)
        
        self.memory = MemorySaver()
        self.graph = self._build_graph()
        self.prompt_manager = get_prompt_manager()

        self.classifier = get_classifier()
        logger.info("Initialized NoraAgent")
    
    def _build_graph(self) -> StateGraph:
        """Build the agentic LangGraph workflow with a tool-calling loop."""
        workflow = StateGraph(AgentState)
        
        # 1. Add the nodes
        workflow.add_node("classify", self._classify_query)
        workflow.add_node("agent", self.call_agent_node)
        workflow.add_node("document_search", ToolNode(self.tools))
        workflow.add_node("create_routing_message", self._create_routing_message)
        workflow.add_node("finalize_response", self._finalize_response)

        # 2. Define the entry point
        workflow.set_entry_point("classify")
        
        # 3. Add routing from the classification step
        workflow.add_conditional_edges(
            "classify",
            self._should_use_agent_or_route,
            {
                # If RAG is needed, we now go to the central "agent" node
                "rag_pipeline": "agent",
                "human_support": "create_routing_message"
            }
        )
        
        # 4. Define the tool-calling loop
        workflow.add_conditional_edges(
            "agent",
            # This pre-built function checks the last message for tool calls
            tools_condition,
            {
                # If the agent called a tool, run the ToolNode
                "tools": "document_search",
                # If the agent did NOT call a tool, it has the final answer
                # so we can proceed to the next step in our RAG pipeline.
                END: "finalize_response"
            }
        )
        
        # 5. Define the rest of the flow
        workflow.add_edge("document_search", "agent") # <-- After the tool runs, go BACK to the agent
        workflow.add_edge("create_routing_message", "finalize_response")
        workflow.add_edge("finalize_response", END)
        
        return workflow.compile(checkpointer=self.memory, name="NoraAgent")

    async def _classify_query(self, state: AgentState) -> Dict[str, Any]:
        """Classify the user query using structured output."""
        messages = state["messages"]
        query = messages[-1].content
        classification = await self.classifier.classify(query)
        return {"classification": classification}

    async def call_agent_node(self, state: AgentState) -> Dict[str, Any]:

        # Fetch the prompt template from the manager
        agent_prompt_template = self.prompt_manager.get_prompt("nora_system_prompt")

        # Format the prompt to get the string content (since it has no variables)
        system_prompt_content = agent_prompt_template.format()
        
        # Construct the messages list with the dynamic prompt
        messages = [SystemMessage(content=system_prompt_content)] + state["messages"]
        
        response = await self.llm_with_tools.ainvoke(messages)
        return {"messages": [response]}

    def _should_use_agent_or_route(self, state: AgentState) -> str:
        """Route based on classification - clean conditional logic."""
        classification = state.get("classification")
        if not classification:
            return "human_support"

        # Human Support topics
        human_support_topics = {
            TopicTag.ISSUE_REPORT, TopicTag.FEATURE_REQUEST
        }
        
        query_topics = set(classification.topic_tags)
        
        if any(topic in human_support_topics for topic in query_topics):
            logger.info(f"Routing to human support: {query_topics}")
            return "human_support"
        else:
            logger.info(f"Routing to RAG pipeline: {query_topics}")
            return "rag_pipeline"

    async def _create_routing_message(self, state: AgentState) -> Dict[str, Any]:
        """Create routing message for human support."""
        classification = state.get("classification")
        if not classification or not classification.topic_tags:
            topic = TopicTag.OTHER
        else:
            topic = classification.topic_tags[0]
        
        # Team routing
        team_mapping = {
            TopicTag.CONNECTOR: "Connectors Team",
            TopicTag.LINEAGE: "Lineage Team", 
            TopicTag.GLOSSARY: "Data Governance Team",
            TopicTag.SENSITIVE_DATA: "Security & Compliance Team",
        }
        
        team = team_mapping.get(topic, "General Support Team")
        message = f"Your '{topic.value}' inquiry has been routed to our {team}. You'll receive a response within 24 hours."
        
        routing_msg = RoutingMessage(message=message, team=team)
        return {"routing_message": routing_msg}


    async def _finalize_response(self, state: AgentState) -> Dict[str, Any]:
        """Create the final response structure."""
        
        # Build internal analysis
        internal_analysis = InternalAnalysis(
            classification=state.get("classification")
        )
        # Determine response type and build final response
        if state.get("routing_message"):
            # Human support path
            final_response = FinalResponse(
                response_type="routing_message",
                routing_response=state["routing_message"]
            )
        else:
            # RAG path - extract answer and sources from the message history
            messages = state["messages"]
            answer = "No answer generated."
            retrieved_docs = []

            if messages:
                # The final answer is in the last AIMessage, also as _finalize_response has edge only from Agent node, so its safe to assume that last message is of type AIMessage
                last_message = messages[-1]
                answer = last_message.content

                # The ToolNode does not automatically update the top-level keys in AgentState.
                # Instead, its primary job is to take the output from the tool and append it to the messages list as a ToolMessage.
                # The dictionary {"retrieved_docs": ...} becomes the content of that ToolMessage.
                # Hence we iterate the List in reverse order get last ToolMessage to get retrieved docs.
                if len(messages) > 1:
                    for tool_message in reversed(messages):
                        if not isinstance(tool_message, ToolMessage):
                            continue
                        # Safely parse the tool message content
                        if hasattr(tool_message, 'content') and isinstance(tool_message.content, str):
                            try:
                                tool_output = json.loads(tool_message.content)
                                retrieved_docs = tool_output.get("retrieved_docs", [])
                            except json.JSONDecodeError:
                                logger.warning("Could not parse tool message content for sources.")

            rag_response = RAGResponse(
                answer=answer,
                sources=retrieved_docs,
                confidence=0.85 
            )
            
            final_response = FinalResponse(
                response_type="rag_answer", 
                rag_response=rag_response
            )
        
        return {
            "internal_analysis": internal_analysis,
            "final_response": final_response
        }

    def _create_error_response(self, error: str, session_id: str) -> ChatbotResponse:
        """Create error response."""
        return ChatbotResponse(
            internal_analysis=InternalAnalysis(
                classification=Classification(
                    topic_tags=[TopicTag.OTHER],
                    sentiment=Sentiment.NEUTRAL,
                    priority=Priority.P2,
                    reasoning=f"Error: {error}"
                )
            ),
            final_response=FinalResponse(
                response_type="routing_message",
                routing_response=RoutingMessage(
                    message="I encountered an error. Please contact support.",
                    team="Technical Support"
                )
            ),
            session_id=session_id,
            timestamp=datetime.utcnow().isoformat()
        )


    async def process_query_stream(self, query: str, session_id: Optional[str] = None) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream the query processing using the modern astream_events API in a single run."""
        if not session_id:
            session_id = str(uuid4())
        
        initial_state = {
            "messages": [HumanMessage(content=query)],
            "user_query": query,
            "session_id": session_id
        }
        
        config = {"configurable": {"thread_id": session_id}}
        
        final_state = None
        try:
            # Use astream_events, which runs the graph only ONCE.
            # We specify version "v2" for the latest event format.
            async for event in self.graph.astream_events(initial_state, config=config, version="v2"):
                kind = event["event"]
                name = event.get("name", "") # Get the name of the node

                # Define the nodes we want to report on
                trackable_nodes = ["classify", "cleanup", "agent", "document_search", "finalize_response"]

                if kind == "on_chain_start" and name in trackable_nodes:
                    yield {
                        "type": "node_start",
                        "node": name,
                        "message": f"Processing {name.replace('_', ' ')}..."
                    }
                elif kind == "on_chain_end" and name in trackable_nodes:
                    yield {
                        "type": "node_complete",
                        "node": name,
                        "message": f"Completed {name.replace('_', ' ')}"
                    }
                
                # The final result of the entire graph is in the 'on_chain_end' event
                # for the top-level runnable. We can capture it here.
                # The 'output' of a StateGraph run is the final state dictionary.
                if kind == "on_chain_end" and name == "NoraAgent": # Check for the name of your graph
                    final_state = event["data"].get("output")


            if final_state:
                response = ChatbotResponse(
                    internal_analysis=final_state["internal_analysis"],
                    final_response=final_state["final_response"],
                    session_id=session_id,
                    timestamp=datetime.utcnow().isoformat()
                )
                yield {"type": "final_result", "data": response.model_dump()}
                
        except Exception as e:
            logger.error(f"Streaming failed: {e}", exc_info=True)
            yield {"type": "error", "message": str(e)}
