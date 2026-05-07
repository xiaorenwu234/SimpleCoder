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
from langgraph.graph import StateGraph
from pydantic import BaseModel
from langgraph.graph.message import add_messages
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

        # Build workflow graph
        self.workflow = StateGraph(AgentState)

        # Register nodes
        self.workflow.add_node("user_input", self.user_input)
        self.workflow.add_node("model_response", self.model_response)
        self.workflow.add_node("tool_use", self.tool_use)

        # Edges: start at user_input
        self.workflow.set_entry_point("user_input")
        self.workflow.add_edge("user_input", "model_response")
        self.workflow.add_edge("tool_use", "model_response")

        # Conditional: model_response -> tool_use OR -> user_input
        self.workflow.add_conditional_edges(
            "model_response",
            self.check_tool_use,
            {
                "tool_use": "tool_use",
                "user_input": "user_input",
            },
        )

    async def initialize(self):
        """Async initialization - load tools and other async resources"""
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

        # Bind tools to model
        self.model_with_tools = self.model.bind_tools(self.tools)

        # Compile graph
        db_path = os.path.join(os.getcwd(), "checkpoints.db")
        self._checkpointer_ctx = AsyncSqliteSaver.from_conn_string(db_path)
        self.checkpointer = await self._checkpointer_ctx.__aenter__()
        self.agent = self.workflow.compile(checkpointer=self.checkpointer)

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
        Main loop: invoke the workflow repeatedly, never exits automatically.
        """
        config = {"configurable": {"thread_id": "1"}}
        
        # 记录会话开始
        self.memory.add_conversation("main", "system", "会话开始")
        self.logger.info("Agent 会话开始")
        
        try:
            return await self.agent.ainvoke({"messages": AIMessage(content="What can I do for you?")}, config=config)
        finally:
            # 记录会话结束
            self.memory.add_conversation("main", "system", "会话结束")
            self.logger.info("Agent 会话结束")
    
    def _build_memory_context(self) -> str:
        """构建记忆上下文，注入到 system prompt"""
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

        # Add Python Run MCP (commented out as it's slow to initialize)
        # Uncomment if you need Python execution capability
        # mcp_configs["Run_Python_MCP"] = {
        #     "command": "docker",
        #     "args": [
        #         "run",
        #         "-i",
        #         "--rm",
        #         "deno-docker:latest",
        #         "deno",
        #         "run",
        #         "-N",
        #         "-R=node_modules",
        #         "-W=node_modules",
        #         "--node-modules-dir=auto",
        #         "jsr:@pydantic/mcp-run-python",
        #         "stdio",
        #     ],
        #     "transport": "stdio",
        # }

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

    # Node: user_input
    def user_input(self, state: AgentState) -> AgentState:
        """
        Ask user for input and append HumanMessage to state.
        Supports special commands starting with '/'.
        """
        self.console.print("[bold cyan]User Input[/bold cyan]: ")
        user_input = self.console.input("> ")
        
        # 处理特殊命令
        if user_input.startswith("/"):
            special_response = self._handle_special_command(user_input)
            if special_response:
                return {"messages": [HumanMessage(content=special_response)]}
        
        # 记录对话
        self.memory.add_conversation("main", "user", user_input)
        
        return {"messages": [HumanMessage(content=user_input)]}
    
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

    # Node: model_response
    def model_response(self, state: AgentState) -> AgentState:
        """
        Call the LLM (with tools bound). Print assistant content and any tool_call previews.
        Decide routing via check_tool_use.
        """
        system_text = """You are a specialised agent for maintaining and developing codebases.
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
            system_text += f"\n\n## Session Context:\n{memory_context}"
        
        # Compose messages: include prior state
        messages = [
            SystemMessage(
                content=[
                    {
                        "type": "text",
                        "text": system_text,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
            ),
            HumanMessage(content=f"Working directory: {os.getcwd()}"),
        ] + state.messages

        # Invoke model
        response = self.model_with_tools.invoke(messages)
        if isinstance(response.content, list):
            for item in response.content:
                if item["type"] == "text":
                    text = item.get("text", "")
                    if text:
                        self.console.print(
                            Panel.fit(
                                Markdown(text),
                                title="[magenta]Assistant[/magenta]",
                                border_style="magenta",
                            )
                        )
                elif item["type"] == "tool_use":
                    self.console.print(
                        Panel.fit(
                            Markdown(f'{item["name"]} with args {item.get("args",None)}'),
                            title="Tool Use",
                        )
                    )
        else:
            self.console.print(
                Panel.fit(
                    Markdown(response.content),
                    title="[magenta]Assistant[/magenta]",
                )
            )

        return {"messages": [response]}

    # Conditional router
    def check_tool_use(self, state: AgentState) -> str:
        """
        If the last assistant message has tool_calls, route to 'tool_use', else route to 'user_input'.
        """
        if state.messages[-1].tool_calls:
            return "tool_use"
        return "user_input"

    # Node: tool_use
    async def tool_use(self, state: AgentState) -> AgentState:
        """
        Execute tool calls from the last assistant message and return ToolMessage(s),
        preserving tool_call_id so the model can reconcile results when we go back to model_response.
        支持并行执行和自动重试。
        """
        from langgraph.prebuilt import ToolNode

        response = []
        tools_by_name = {t.name: t for t in self.tools}

        # 定义需要确认的危险操作
        DANGEROUS_TOOLS = {"run_command", "code_edit", "file_write"}
        
        # 收集需要执行的工具调用
        tool_calls_to_execute = []
        for tc in state.messages[-1].tool_calls:
            tool_name = tc["name"]
            tool_args = tc["args"]
            
            # 安全检查：危险操作需要用户确认
            if tool_name in DANGEROUS_TOOLS:
                self.console.print(
                    Panel.fit(
                        Markdown(f"**⚠️ 危险操作确认**\n\n工具: `{tool_name}`\n\n参数:\n```json\n{tool_args}\n```\n\n是否继续执行？"),
                        title="安全警告",
                        border_style="yellow",
                    )
                )
                user_confirm = self.console.input("[bold yellow]输入 'y' 或 'yes' 继续，其他键取消: [/bold yellow]")
                if user_confirm.lower() not in ['y', 'yes']:
                    self.console.print("[red]❌ 操作已取消[/red]")
                    response.append(
                        ToolMessage(
                            content=f"操作被用户取消",
                            tool_call_id=tc["id"],
                        )
                    )
                    continue
            
            tool_calls_to_execute.append(tc)
        
        # 并行执行独立工具调用
        if len(tool_calls_to_execute) > 1:
            self.logger.info(f"并行执行 {len(tool_calls_to_execute)} 个工具调用")
            
            # 创建异步任务
            tasks = [
                self._execute_single_tool(tool_call, tools_by_name, state)
                for tool_call in tool_calls_to_execute
            ]
            
            # 等待所有任务完成
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 收集结果
            for result in results:
                if isinstance(result, Exception):
                    self.logger.error(f"工具执行异常: {result}")
                    response.append(
                        ToolMessage(
                            content=f"ERROR: {str(result)}",
                            tool_call_id="unknown",
                        )
                    )
                else:
                    response.append(result)
        else:
            # 单个工具调用，顺序执行
            for tc in tool_calls_to_execute:
                result = await self._execute_single_tool(tc, tools_by_name, state)
                response.append(result)
        
        return {"messages": response}
    
    async def _execute_single_tool(self, tc: dict, tools_by_name: dict, state: AgentState, max_retries: int = 2) -> ToolMessage:
        """执行单个工具调用，支持自动重试"""
        tool_name = tc["name"]
        tool_args = tc["args"]
        
        for attempt in range(max_retries + 1):
            try:
                start_time = time.time()
                self.logger.info(f"执行工具 {tool_name} (尝试 {attempt + 1}/{max_retries + 1})")
                
                from langgraph.prebuilt import ToolNode
                tool = tools_by_name.get(tool_name)
                tool_node = ToolNode([tool])
                
                tool_result = await tool_node.ainvoke(state)
                execution_time = time.time() - start_time
                
                # 记录成功
                self.operation_logger.log(tool_name, {"args": tool_args}, success=True)
                self.memory.record_tool_usage(tool_name, success=True, execution_time=execution_time)
                
                result_msg = tool_result["messages"][0]
                
                # 显示结果
                self.console.print(
                    Panel.fit(
                        Syntax("\n" + result_msg.content + "\n", "text"),
                        title=f"Tool Result ({tool_name})",
                    )
                )
                
                return result_msg
                
            except Exception as e:
                self.logger.error(f"工具 {tool_name} 执行失败 (尝试 {attempt + 1}): {e}")
                
                if attempt < max_retries:
                    # 等待后重试
                    wait_time = 2 ** attempt
                    self.console.print(f"[yellow]⚠️ 工具 {tool_name} 执行失败，{wait_time}秒后重试...[/yellow]")
                    await asyncio.sleep(wait_time)
                else:
                    # 所有重试失败
                    self.operation_logger.log(tool_name, {"args": tool_args, "error": str(e)}, success=False)
                    self.memory.record_tool_usage(tool_name, success=False, execution_time=0)
                    
                    return ToolMessage(
                        content=f"ERROR: 工具 '{tool_name}' 执行失败（已重试{max_retries}次）: {e}",
                        tool_call_id=tc["id"],
                    )

    def print_mermaid_workflow(self):
        """
        Utility: print Mermaid diagram to visualize the graph edges.
        """
        try:
            mermaid = self.agent.get_graph().draw_mermaid_png(
                output_file_path="langgraph_workflow.png",
                max_retries=5,
                retry_delay=2,
            )
        except Exception as e:
            print(f"Error generating mermaid PNG: {e}")
            mermaid = self.agent.get_graph().draw_mermaid()
            self.console.print(
                Panel.fit(
                    Syntax(mermaid, "mermaid", theme="monokai", line_numbers=False),
                    title="Workflow (Mermaid)",
                    border_style="cyan",
                )
            )
            print(self.agent.get_graph().draw_ascii())
