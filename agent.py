from typing import Annotated, Sequence
from dotenv import load_dotenv
import os
import asyncio
import time
import logging
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.syntax import Syntax

from langchain_openai import ChatOpenAI
from langchain_core.messages import (
    BaseMessage,
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.prebuilt import create_react_agent
from langgraph.graph.message import add_messages
from langgraph.types import StreamWriter
from pydantic import BaseModel
from tools.run_unit_tests_tool import run_unit_tests
from tools.advanced_file_read import AdvancedFileReadTool
from tools.file_write import FileWriteTool
from tools.list_directory import ListDirectoryTool
from tools.run_command import RunCommandTool
from tools.search_files import SearchFilesTool
from tools.code_edit import CodeEditTool
from tools.lint_code import LintCodeTool
from tools.format_code import FormatCodeTool
from tools.git_diff import GitDiffTool
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from tools.sandbox_executor import SandboxEnvironment, OperationLogger
from tools.operation_rollback import OperationRollback
from tools.code_indexer import CodeIndexer
from tools.agent_memory import AgentMemory
from tools.safe_run_command import SafeRunCommandTool
from tools.safe_code_edit import SafeCodeEditTool
from tools.code_search_tool import CodeSearchTool, IndexCodebaseTool
from tools.rollback_tool import RollbackTool
from tools.memory_tool import MemoryTool


class AgentState(BaseModel):
    """
    Persistent agent state tracked across the graph.
    - messages: complete chat history (system + user + assistant + tool messages)
    """

    messages: Annotated[Sequence[BaseMessage], add_messages]


class Agent:
    def __init__(self):
        self._initialized = False
        # Load environment
        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
        api_base = os.getenv("OPENAI_API_BASE") or os.getenv(
            "DASHSCOPE_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        model_name = os.getenv("MODEL_NAME", "qwen-plus")

        if not api_key:
            raise RuntimeError(
                "Missing OPENAI_API_KEY or DASHSCOPE_API_KEY in environment. Set it in .env or your shell."
            )

        # Model instantiation (OpenAI compatible API)
        self.model = ChatOpenAI(
            model=model_name,
            temperature=0.3,
            max_tokens=4096,
            api_key=api_key,
            base_url=api_base,
        )

        # Rich console for UI
        self.console = Console()
        
        # 初始化增强组件
        self.sandbox = SandboxEnvironment()
        self.operation_logger = OperationLogger()
        self.rollback_manager = OperationRollback()
        self.code_indexer = CodeIndexer()
        self.memory = AgentMemory()
        
        # 设置日志
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('agent.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger('Agent')

        # Agent will be created in initialize() with tools
        self.agent = None

    async def initialize(self):
        """Async initialization - load tools and create agent"""
        if self._initialized:
            return self

        print("🔄 Initializing agent...")

        # Local tools - replacing Desktop Commander MCP functionality
        local_tools = [
            run_unit_tests,
            AdvancedFileReadTool(),
            FileWriteTool(),
            ListDirectoryTool(),
            RunCommandTool(),
            SearchFilesTool(),
            CodeEditTool(),
            LintCodeTool(),
            FormatCodeTool(),
            GitDiffTool(),
            # 增强工具
            SafeRunCommandTool(),
            SafeCodeEditTool(),
            CodeSearchTool(),
            IndexCodebaseTool(),
            RollbackTool(),
            MemoryTool(),
        ]

        print(f"📦 Loaded {len(local_tools)} local tools:")
        for tool in local_tools:
            print(f"   🔧 {tool.name}")

        # Set up MCP client (optional - requires Docker)
        mcp_tools = []
        try:
            print("🔌 Attempting to load MCP tools (requires Docker)...")
            mcp_tools = await self.get_mcp_tools()
            print(f"✅ Loaded {len(mcp_tools)} MCP tools")
            for tool in mcp_tools:
                print(f"  🔧 {tool.name}")
        except Exception as e:
            import traceback

            print(f"⚠️  MCP tools loading failed: {e}")
            print(f"📋 Detailed error:\n{traceback.format_exc()}")
            print("💡 Continuing with local tools only. To use MCP tools:")
            print("   1. Ensure Docker is running: docker ps")
            print("   2. Check Docker images: docker images")
            print("   3. Try: pip install langchain-mcp-adapters==0.1.11")

        self.tools = local_tools + mcp_tools
        print(f"✅ Loaded {len(self.tools)} total tools (Local: {len(local_tools)} + MCP: {len(mcp_tools)})")
        self._initialized = True

        # Build system prompt
        system_prompt = """You are a specialised agent for maintaining and developing codebases.
## Development Guidelines:

1. **Test Failures:**
- When tests fail, fix the implementation first, not the tests.
- Tests represent expected behavior; implementation should conform to tests
- Only modify tests if they clearly don't match specifications

2. **Code Changes:**
- Make the smallest possible changes to fix issues
- Focus on fixing the specific problem rather than rewriting large portions
- Add unit tests for all new functionality before implementing it

3. **Best Practices:**
- Keep functions small with a single responsibility
- Implement proper error handling with appropriate exceptions
- Be mindful of configuration dependencies in tests

4. **Safety:**
- Use safe_run_command instead of run_command for safer execution
- Use safe_code_edit instead of code_edit for automatic backup
- Use rollback tool to undo changes if something goes wrong
- Use index_codebase + code_search to understand codebase before making changes
- Use agent_memory to save important context for future sessions

Ask for clarification when needed. Remember to examine test failure messages carefully to understand the root cause before making any changes."""

        # 加载记忆上下文
        memory_context = self._build_memory_context()
        if memory_context:
            system_prompt += f"\n\n## Session Context:\n{memory_context}"

        # Create agent using create_react_agent - 简洁的 Agent API
        self.agent = create_react_agent(
            model=self.model,
            tools=self.tools,
            state_modifier=system_prompt,
        )

        # Setup checkpointer for persistence
        db_path = os.path.join(os.getcwd(), "checkpoints.db")
        self._checkpointer_ctx = AsyncSqliteSaver.from_conn_string(db_path)
        self.checkpointer = await self._checkpointer_ctx.__aenter__()
        
        # Compile with checkpointer
        self.agent.checkpointer = self.checkpointer

        # Optional: print a greeting panel
        self.console.print(
            Panel.fit(
                Markdown("**LangGraph Coding Agent** — Claude Code Clone\n\n"
                         "✅ Enhanced Features:\n"
                         "- 🔒 Sandbox execution environment\n"
                         "- 📦 Automatic file backup & rollback\n"
                         "- 🔍 Code indexing & semantic search\n"
                         "- 🧠 Persistent memory across sessions\n"
                         "- ⚡ Parallel tool execution with retry\n"
                         "- 📊 Operation logging & statistics\n\n"
                         "Type /help for special commands"),
                title="[bold green]Ready[/bold green]",
                border_style="green",
            )
        )
        return self

    async def run(self):
        """
        Main loop: invoke the agent repeatedly, never exits automatically.
        """
        config = {"configurable": {"thread_id": "1"}}
        
        # 记录会话开始
        self.memory.add_conversation("main", "system", "会话开始")
        self.logger.info("Agent 会话开始")
        
        try:
            while True:
                # Get user input
                self.console.print("[bold cyan]User Input[/bold cyan]: ")
                user_input = self.console.input("> ")
                
                # 处理特殊命令
                if user_input.startswith("/"):
                    special_response = self._handle_special_command(user_input)
                    if special_response:
                        self.console.print(
                            Panel.fit(
                                Markdown(special_response),
                                title="[bold yellow]Command Result[/bold yellow]",
                                border_style="yellow",
                            )
                        )
                        continue
                
                # 记录对话
                self.memory.add_conversation("main", "user", user_input)
                
                # Invoke agent with streaming for progressive output
                self.console.print("\n[bold cyan]🤖 Processing...[/bold cyan]\n")
                
                # 跟踪是否正在输出AI响应
                assistant_output_active = False
                
                # 使用 astream_events 获取更详细的事件流
                async for event in self.agent.astream_events(
                    {"messages": [HumanMessage(content=user_input)]},
                    config=config,
                    version="v2"
                ):
                    event_type = event.get("event", "")
                    
                    # 处理 AI 文本流式输出
                    if event_type == "on_chat_model_stream":
                        chunk = event.get("data", {}).get("chunk", "")
                        if chunk:
                            if isinstance(chunk, AIMessage):
                                if chunk.content and isinstance(chunk.content, str):
                                    if chunk.content.strip():
                                        if not assistant_output_active:
                                            self.console.print("\n[magenta]━ Assistant Response ━[/magenta]")
                                            assistant_output_active = True
                                        print(chunk.content, end="", flush=True)
                    
                    # 处理工具调用开始
                    elif event_type == "on_tool_start":
                        if assistant_output_active:
                            print()
                            assistant_output_active = False
                        
                        tool_name = event.get("name", "unknown")
                        tool_input = event.get("data", {}).get("input", {})
                        
                        print()  # 换行
                        if tool_input:
                            import json
                            args_str = json.dumps(tool_input, indent=2, ensure_ascii=False)
                            self.console.print(
                                Panel.fit(
                                    Markdown(f'**🔧 Tool**: `{tool_name}`\n\n**Parameters**:\n```json\n{args_str}\n```'),
                                    title="[yellow]⚡ Tool Execution[/yellow]",
                                    border_style="yellow",
                                )
                            )
                        else:
                            self.console.print(
                                Panel.fit(
                                    Markdown(f'**🔧 Tool**: `{tool_name}`'),
                                    title="[yellow]⚡ Tool Execution[/yellow]",
                                    border_style="yellow",
                                )
                            )
                        print()  # 工具调用后换行
                    
                    # 处理工具执行完成
                    elif event_type == "on_tool_end":
                        print()  # 换行
                        tool_output = event.get("data", {}).get("output", "")
                        tool_name = event.get("name", "tool")
                        
                        if isinstance(tool_output, str):
                            content_preview = tool_output[:500] if len(tool_output) > 500 else tool_output
                            self.console.print(
                                Panel.fit(
                                    Syntax("\n" + content_preview + ("\n...[truncated]" if len(tool_output) > 500 else ""), "text"),
                                    title=f"[green]✅ Tool Result: {tool_name}[/green]",
                                    border_style="green",
                                )
                            )
                        print()  # 工具结果后换行
                
                # 确保最后有换行
                if assistant_output_active:
                    print()  # 结束AI文本输出
        
        finally:
            # 记录会话结束
            self.memory.add_conversation("main", "system", "会话结束")
            self.logger.info("Agent 会话结束")
    
    def _build_memory_context(self) -> str:
        """构建记忆上下文,注入到 system prompt"""
        context_parts = []
        
        try:
            # 加载用户偏好
            prefs = self.memory.get_all_preferences()
            if prefs:
                pref_lines = [f"  - {k}: {v}" for k, v in prefs.items()]
                context_parts.append("User Preferences:\n" + "\n".join(pref_lines))
            
            # 加载项目上下文
            project_ctx = self.memory.get_full_project_context(os.getcwd())
            if project_ctx:
                ctx_lines = [f"  - {k}: {v}" for k, v in project_ctx.items()]
                context_parts.append("Project Context:\n" + "\n".join(ctx_lines))
            
            # 加载工具统计
            tool_stats = self.memory.get_tool_stats()
            if tool_stats:
                reliable_tools = [
                    name for name, stats in tool_stats.items()
                    if stats['success_count'] > stats['failure_count']
                ]
                if reliable_tools:
                    context_parts.append(f"Reliable Tools: {', '.join(reliable_tools)}")
        except Exception as e:
            self.logger.warning(f"构建记忆上下文失败: {e}")
        
        return "\n\n".join(context_parts) if context_parts else ""

    async def close_checkpointer(self):
        """Close the async checkpointer context if opened."""
        if hasattr(self, "_checkpointer_ctx"):
            await self._checkpointer_ctx.__aexit__(None, None, None)

    async def get_mcp_tools(self):
        from langchain_mcp_adapters.client import MultiServerMCPClient
        import asyncio

        GITHUB_PERSONAL_ACCESS_TOKEN = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")

        # Define MCP configurations
        mcp_configs = {
            "duckduckgo_MCP": {
                "command": "docker",
                "args": ["run", "-i", "--rm", "mcp/duckduckgo"],
                "transport": "stdio",
            },
            # Desktop Commander replaced by local tools
            # Python Run MCP commented out (slow initialization)
        }

        # Add GitHub MCP if token is available
        if GITHUB_PERSONAL_ACCESS_TOKEN:
            mcp_configs["Github_MCP"] = {
                "command": "docker",
                "args": [
                    "run",
                    "-i",
                    "--rm",
                    "-e",
                    f"GITHUB_PERSONAL_ACCESS_TOKEN={GITHUB_PERSONAL_ACCESS_TOKEN}",
                    "-e",
                    "GITHUB_READ-ONLY=1",
                    "ghcr.io/github/github-mcp-server",
                ],
                "transport": "stdio",
            }

        mcp_tools = []

        # Load MCP tools one by one to avoid resource conflicts
        for name, config in mcp_configs.items():
            try:
                print(f"🔌 Loading {name}...")
                client = MultiServerMCPClient({name: config})
                tools = await client.get_tools()
                mcp_tools.extend(tools)
                print(f"✅ {name}: loaded {len(tools)} tools")
                for tool in tools:
                    print(f"   🔧 {tool.name}: {tool.description[:100]}...")
                # Small delay to avoid resource conflicts
                await asyncio.sleep(1.0)
            except Exception as e:
                import traceback

                print(f"⚠️  {name} failed: {e}")
                print(f"   Error details:\n{traceback.format_exc()}")

        for tb in mcp_tools:
            print(f"MCP 🔧 {tb.name}")
        return mcp_tools

    def _handle_special_command(self, command: str) -> str:
        """处理特殊命令"""
        cmd = command.strip().lower()
        
        if cmd == "/rollback":
            history = self.rollback_manager.get_operation_history(10)
            if not history:
                return "No operation history found."
            output = ["📋 Recent Operations (use /rollback <id> to undo):\n"]
            for op in history:
                status = "✅" if op['success'] else "❌"
                output.append(f"  {status} #{op['id']} [{op['operation_type']}] {op['description'] or op['file_path']}")
            return "\n".join(output)
        
        elif cmd.startswith("/rollback "):
            try:
                op_id = int(cmd.split()[1])
                result = self.rollback_manager.rollback_operation(op_id)
                if result['success']:
                    return f"✅ {result['message']}"
                else:
                    return f"❌ {result.get('error', 'Unknown error')}"
            except (ValueError, IndexError):
                return "Usage: /rollback <operation_id>"
        
        elif cmd == "/history":
            history = self.memory.get_conversation_history("main", 10)
            if not history:
                return "No conversation history."
            output = ["📋 Conversation History:\n"]
            for msg in history:
                output.append(f"  [{msg['role']}] {msg['content'][:100]}...")
            return "\n".join(output)
        
        elif cmd == "/stats":
            tool_stats = self.memory.get_tool_stats()
            if not tool_stats:
                return "No tool usage statistics yet."
            output = ["📊 Tool Usage Statistics:\n"]
            for name, stats in tool_stats.items():
                total = stats['success_count'] + stats['failure_count']
                success_rate = (stats['success_count'] / total * 100) if total > 0 else 0
                output.append(f"  {name}: {success_rate:.0f}% success ({total} uses, avg {stats['avg_execution_time']:.2f}s)")
            return "\n".join(output)
        
        elif cmd == "/index":
            try:
                count = self.code_indexer.index_directory(os.getcwd())
                stats = self.code_indexer.get_index_stats()
                return f"✅ Indexed {count} files\n   Symbols: {stats['symbols']}, Imports: {stats['imports']}"
            except Exception as e:
                return f"❌ Indexing failed: {e}"
        
        elif cmd == "/help":
            return ("🔧 Special Commands:\n"
                   "  /rollback        - View operation history\n"
                   "  /rollback <id>   - Undo a specific operation\n"
                   "  /history         - View conversation history\n"
                   "  /stats           - View tool usage statistics\n"
                   "  /index           - Re-index current codebase\n"
                   "  /help            - Show this help")
        
        return None
