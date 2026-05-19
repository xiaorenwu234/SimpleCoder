from typing import Any
from dotenv import load_dotenv
import os
import sys
import asyncio
import time
import json
import logging
import threading
import readline  # 启用GNU readline行编辑，修复macOS下退格键等编辑功能失效
from rich.console import Console, Group
from rich.panel import Panel
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text
from rich.rule import Rule
from rich.live import Live
from rich.spinner import Spinner
from rich.columns import Columns

# AgentScope 核心组件
from agentscope.agent import ReActAgent
from agentscope.formatter import DashScopeChatFormatter, OpenAIChatFormatter
from agentscope.memory import InMemoryMemory
from agentscope.message import TextBlock, Msg
from agentscope.model import DashScopeChatModel, OpenAIChatModel
from agentscope.tool import Toolkit, ToolResponse
from agentscope.token import CharTokenCounter

# 导入原有工具（AgentScope 格式）
from tools.run_unit_tests_tool import run_unit_tests
from tools.advanced_file_read import read_file
from tools.file_write import write_file
from tools.list_directory import list_directory
from tools.run_command import run_command
from tools.search_files import search_files
from tools.code_edit import code_edit
from tools.lint_code import lint_code
from tools.format_code import format_code
from tools.git_diff import git_diff
from tools.web_search import web_search
from tools.file_read_tool import file_read
from tools.memory_tool import agent_memory
from tools.rollback_tool import rollback
from tools.sandbox_executor import SandboxEnvironment, OperationLogger
from tools.operation_rollback import OperationRollback
from tools.code_indexer import CodeIndexer
from tools.agent_memory import AgentMemory
# TODO: 以下工具还需要迁移
# from tools.safe_run_command import SafeRunCommandTool
# from tools.safe_code_edit import SafeCodeEditTool
# from tools.code_search_tool import CodeSearchTool, IndexCodebaseTool
from tools.tracer import get_tracer, reset_tracer



class Agent:
    def __init__(self):
        self._initialized = False
        # Load environment
        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
        api_base = os.getenv("OPENAI_API_BASE") or os.getenv(
            "DASHSCOPE_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        api_base="http://localhost:8001/v1"
        api_key="sk-xxx"
        model_name = os.getenv("MODEL_NAME", "/home/xueht26/Qwen3-8B")

        if not api_key:
            raise RuntimeError(
                "Missing OPENAI_API_KEY or DASHSCOPE_API_KEY in environment. Set it in .env or your shell."
            )

        # Rich  console for UI
        self.console = Console()
        
        # 初始化增强组件
        self.sandbox = SandboxEnvironment()
        self.operation_logger = OperationLogger()
        self.rollback_manager = OperationRollback()
        self.code_indexer = CodeIndexer()
        self.memory = AgentMemory()
        
        # 初始化 Trace 追踪器
        self.tracer = get_tracer()
        
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
        # 屏蔽 httpx / openai 等库的 INFO 日志，避免干扰控制台输出
        logging.getLogger('httpx').setLevel(logging.WARNING)
        logging.getLogger('httpcore').setLevel(logging.WARNING)
        logging.getLogger('openai').setLevel(logging.WARNING)

        # Agent 将在 initialize() 中创建
        self.agent = None
        self.toolkit = Toolkit()

    async def initialize(self):
        """Async initialization - load tools and create agent"""
        if self._initialized:
            return self

        async with self.tracer.async_span("agent.initialize", category="init"):
            print("🔄 Initializing agent...")

        # 注册工具到 Toolkit
        print("📦 Loading tools...")
        
        # 注册工具函数（已在文件顶部导入）
        self.toolkit.register_tool_function(run_command)
        self.toolkit.register_tool_function(read_file)
        self.toolkit.register_tool_function(list_directory)
        self.toolkit.register_tool_function(search_files)
        self.toolkit.register_tool_function(write_file)
        self.toolkit.register_tool_function(code_edit)
        self.toolkit.register_tool_function(run_unit_tests)
        self.toolkit.register_tool_function(lint_code)
        self.toolkit.register_tool_function(format_code)
        self.toolkit.register_tool_function(git_diff)
        self.toolkit.register_tool_function(web_search)
        self.toolkit.register_tool_function(file_read)
        self.toolkit.register_tool_function(agent_memory)
        self.toolkit.register_tool_function(rollback)
        
        print(f"✅ Loaded {len(self.toolkit.tools)} tools into toolkit")
        for tool_name in self.toolkit.tools.keys():
            print(f"   🔧 {tool_name}")

        # 构建 system prompt
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
- Use web_search to find real-time information, documentation, or external knowledge

5. **Memory & Context:**
- You have access to a persistent memory system across sessions
- The "## Session Context" section below contains memories from previous sessions
- This includes user preferences, project context, and recent conversations
- When a user asks about previous interactions, CHECK the Session Context section first
- You DO have memory of prior conversations — reference it naturally when relevant
- Proactively use agent_memory tool to save important findings for future sessions

Ask for clarification when needed. Remember to examine test failure messages carefully to understand the root cause before making any changes."""

        # 加载记忆上下文
        memory_context = self._build_memory_context()
        if memory_context:
            system_prompt += f"\n\n## Session Context:\n{memory_context}"

        # 判断使用的 API 类型
        api_base = os.getenv("OPENAI_API_BASE") or os.getenv("DASHSCOPE_API_BASE", "")
        is_dashscope = "dashscope" in api_base.lower() if api_base else True
        
        self.model = OpenAIChatModel(
                model_name="/home/xueht26/Qwen3-8B",
                api_key="sk-xxx",
                client_kwargs={
                    "base_url": "http://localhost:8001/v1",
                },
                generate_kwargs={
                    "parallel_tool_calls": True,
                },
            )
        formatter = OpenAIChatFormatter()
            

        # 创建 ReActAgent，启用并行工具调用
        self.agent = ReActAgent(
            name="SimpleCoder",
            sys_prompt=system_prompt,
            model=self.model,
            formatter=formatter,
            memory=InMemoryMemory(),
            toolkit=self.toolkit,
            parallel_tool_calls=True,  # 启用并行工具调用！
        )
        
        # 完全接管 agent 的 print 方法，实现自定义流式输出
        # 禁用默认控制台输出，避免重复
        self.agent.set_console_output_enabled(False)
        self._stream_state = {}  # 流式文本/thinking输出状态追踪
        
        # 闭包引用（_stream_state 捕获 dict 对象，self 捕获实例引用）
        _stream_state = self._stream_state
        
        async def _custom_print(msg, last=True, speech=None):
            """
            自定义 print。支持两种 thinking 来源：
              1. 标准 ThinkingBlock（reasoning_content 字段 → AgentScope 解析）
              2. <think>...</think> 标签嵌入 text（Qwen3/vLLM 风格）
            thinking 内容显示为可折叠面板，text 内容流式输出。
            """
            msg_id = msg.id
            
            # 初始化消息状态
            if msg_id not in _stream_state:
                _stream_state[msg_id] = {
                    'thinking': '',           # 思考内容
                    'thinking_start_us': None,
                    'output_start_us': None,
                    'thinking_panel_shown': False,
                    'output_offset': None,    # None=未确定, int=raw text 中 output 的起始位置
                    'text_len': 0,            # 已输出的 output 字符数
                }
            state = _stream_state[msg_id]
            
            current_thinking = ''  # 来自标准 ThinkingBlock
            current_text = ''      # 来自 TextBlock（可能含 <think> 标签）
            
            for block in msg.get_content_blocks():
                block_type = block.get("type", "")
                if block_type == "thinking":
                    current_thinking = block.get("thinking", "")
                elif block_type == "text":
                    current_text = block.get("text", "")
                # tool_use / tool_result 由 middleware 面板处理，跳过
            
            # === Case 1: 标准 ThinkingBlock（来自 reasoning_content 字段）===
            if current_thinking:
                if state['thinking_start_us'] is None:
                    state['thinking_start_us'] = self.tracer._now_us()
                state['thinking'] = current_thinking
            
            # === Case 2: <think> 标签嵌入在 text 中（Qwen3/vLLM 风格）===
            output_text = current_text  # 默认全部为 output
            
            if current_text and not current_thinking:
                if state['output_offset'] is None:
                    # 尚未确定 output 起始位置
                    think_start = current_text.find('<think>')
                    think_end = current_text.find('</think>')
                    
                    if think_start < 0:
                        # 无 think 标签，全部是 output
                        state['output_offset'] = 0
                        output_text = current_text
                    elif think_end > think_start:
                        # 找到完整的 <think>...</think>
                        raw_thinking = current_text[think_start + 7:think_end].strip()
                        state['thinking'] = raw_thinking
                        if state['thinking_start_us'] is None and raw_thinking:
                            state['thinking_start_us'] = self.tracer._now_us()
                        if state['output_start_us'] is None:
                            state['output_start_us'] = self.tracer._now_us()
                        # output 从 </think> 之后开始，跳过前导换行
                        after_close = current_text[think_end + 8:]  # 8 = len('</think>')
                        stripped = len(after_close) - len(after_close.lstrip('\n'))
                        state['output_offset'] = think_end + 8 + stripped
                        output_text = current_text[state['output_offset']:]
                    else:
                        # 有 <think> 但还没有 </think>（思考进行中）
                        raw_partial = current_text[think_start + 7:].strip()
                        if raw_partial:
                            state['thinking'] = raw_partial
                        if state['thinking_start_us'] is None and raw_partial:
                            state['thinking_start_us'] = self.tracer._now_us()
                        output_text = ''  # 思考未结束，暂不输出
                else:
                    # 已知 output 起始位置，直接切片
                    output_text = current_text[state['output_offset']:]
            
            # === 记录 output 开始时间戳 ===
            if output_text and state['output_start_us'] is None:
                state['output_start_us'] = self.tracer._now_us()
            
            # === 展示 thinking 面板（thinking 完成时，即将开始 output）===
            should_show_thinking = (
                state['thinking']
                and not state['thinking_panel_shown']
                and (output_text or last)
            )
            if should_show_thinking:
                state['thinking_panel_shown'] = True
                thinking_text = state['thinking']
                thinking_chars = len(thinking_text)
                thinking_end_us = state['output_start_us'] or self.tracer._now_us()
                thinking_time_s = (
                    (thinking_end_us - state['thinking_start_us']) / 1_000_000
                    if state['thinking_start_us'] else 0
                )
                MAX_SHOW = 600
                if thinking_chars > MAX_SHOW:
                    display = (
                        f"[dim]{thinking_text[:MAX_SHOW]}[/dim]\n"
                        f"[dim]... ({thinking_chars - MAX_SHOW:,} more chars)[/dim]"
                    )
                else:
                    display = f"[dim]{thinking_text}[/dim]"
                
                sys.stdout.flush()  # 先刷 stdout，再用 Rich Console 打印
                self.console.print(
                    Panel(
                        display,
                        title=(
                            f"[dim]💭 Thinking"
                            f"  ⏱ {thinking_time_s:.1f}s"
                            f"  📝 {thinking_chars:,} chars[/dim]"
                        ),
                        border_style="dim",
                        padding=(0, 1),
                    )
                )
            
            # === 流式输出 output 文本（仅新增部分）===
            if output_text:
                prev_len = state['text_len']
                if len(output_text) > prev_len:
                    sys.stdout.write(output_text[prev_len:])
                    sys.stdout.flush()
                    state['text_len'] = len(output_text)
            
            # === 最后一条消息：清理状态，记录时间戳，补换行 ===
            if last:
                if msg_id in _stream_state:
                    s = _stream_state.pop(msg_id)
                    # 将 thinking/output 时间戳写入 turn_timeline 供 trace 使用
                    if s.get('thinking_start_us'):
                        self._turn_timeline['thinking_start_us'] = s['thinking_start_us']
                        self._turn_timeline['thinking_end_us'] = (
                            s.get('output_start_us') or self.tracer._now_us()
                        )
                    if s['text_len'] > 0 or s['thinking']:
                        sys.stdout.write("\n")
                        sys.stdout.flush()
        
        # 替换 agent 的 print 方法
        self.agent.print = _custom_print
        
        # 设置工具调用钩子，显示工具调用和返回
        self._setup_tool_hooks()

        self._initialized = True

        # Optional: print a greeting panel
        self.console.print(
            Panel.fit(
                Markdown("**AgentScope Coding Agent** — Claude Code Clone\n\n"
                         "✅ Enhanced Features:\n"
                         "- 🔒 Sandbox execution environment\n"
                         "- 📦 Automatic file backup & rollback\n"
                         "- 🔍 Code indexing & semantic search\n"
                         "- 🧠 Persistent memory across sessions\n"
                         "- ⚡ **True parallel tool execution** (AgentScope native)\n"
                         "- 📊 Operation logging & statistics\n\n"
                         "Type /help for special commands"),
                title="[bold green]Ready[/bold green]",
                border_style="green",
            )
        )
        return self

    def _setup_tool_hooks(self):
        """设置工具调用钩子，使用 Toolkit middleware 实现工具调用框显示"""
        console = self.console
        logger = self.logger
        tracer = self.tracer

        # 追踪turn内的时间线，用于推断LLM推理阶段（使用实例变量）
        self._turn_timeline = {
            'turn_start': None,
            'last_event_end': None,
            'llm_spans': [],   # 记录LLM推理阶段
            'tool_spans': [],  # 记录工具调用阶段
            'thinking_start_us': None,  # LLM思考阶段开始时间戳
            'thinking_end_us': None,    # LLM思考阶段结束（=输出阶段开始）时间戳
        }

        async def tool_display_middleware(kwargs, next_handler):
            """工具调用显示中间件：在工具调用前后显示 Rich 面板，并采集完整硬件指标"""
            tool_call = kwargs["tool_call"]
            tool_name = tool_call.get("name", "unknown")
            tool_input = tool_call.get("input", {})

            # ---- 工具调用框 ----
            # 格式化参数显示
            args_lines = []
            for key, value in tool_input.items():
                val_str = str(value)
                if len(val_str) > 200:
                    val_str = val_str[:200] + "..."
                args_lines.append(f"  [cyan]{key}[/cyan] = {val_str}")
            args_text = "\n".join(args_lines) if args_lines else "  [dim](no arguments)[/dim]"

            console.print("")
            console.print(
                Panel.fit(
                    args_text,
                    title=f"[bold yellow]🔧 {tool_name}[/bold yellow]",
                    border_style="yellow",
                    padding=(0, 1),
                )
            )

            # ---- 执行工具并采集硬件指标 ----
            result_text = ""
            start_time = time.time()
            # 记录并发数 + 采集前快照
            concurrent_count = tracer.track_tool_start(tool_name)
            hw_before = tracer._hw_snapshot()
            span_ts = tracer._now_us()  # 记录span开始时间
            had_error = False
            
            # 检查是否需要记录LLM推理阶段（工具调用前的间隙）
            if self._turn_timeline['last_event_end'] is not None:
                gap_start = self._turn_timeline['last_event_end']
                gap_end_us = span_ts
                gap_duration_us = gap_end_us - gap_start
                
                if gap_duration_us > 50_000:  # 50ms
                    t_start = self._turn_timeline.get('thinking_start_us')
                    t_end   = self._turn_timeline.get('thinking_end_us')
                    
                    if t_start and t_end and t_start >= gap_start:
                        # 有 thinking 阶段：拆分为 pre_thinking + thinking + output
                        pre_gap = t_start - gap_start
                        if pre_gap > 50_000:
                            tracer._add_event(
                                "llm.pre_thinking", "X", gap_start,
                                tid=3, cat="llm", dur=pre_gap,
                                args={"inferred": True, "gap_before_tool": tool_name, "phase": "pre_thinking"}
                            )
                        think_dur = t_end - t_start
                        if think_dur > 0:
                            tracer._add_event(
                                "llm.thinking", "X", t_start,
                                tid=3, cat="llm", dur=think_dur,
                                args={"inferred": True, "gap_before_tool": tool_name, "phase": "thinking"}
                            )
                        output_dur = gap_end_us - t_end
                        if output_dur > 50_000:
                            tracer._add_event(
                                "llm.output", "X", t_end,
                                tid=3, cat="llm", dur=output_dur,
                                args={"inferred": True, "gap_before_tool": tool_name, "phase": "output"}
                            )
                        # 记录后重置，避免影响后续轮次
                        self._turn_timeline['thinking_start_us'] = None
                        self._turn_timeline['thinking_end_us'] = None
                    else:
                        # 无 thinking 信息，整个计为 reasoning
                        tracer._add_event(
                            "llm.reasoning", "X", gap_start,
                            tid=3, cat="llm", dur=gap_duration_us,
                            args={"inferred": True, "gap_before_tool": tool_name}
                        )
                    self._turn_timeline['llm_spans'].append({
                        'start': gap_start,
                        'duration_us': gap_duration_us
                    })
            
            try:
                async for response in await next_handler(**kwargs):
                    # 收集结果文本
                    if response.content:
                        for block in response.content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                result_text += block.get("text", "")
                            elif hasattr(block, "text"):
                                result_text += block.text
                    yield response
            except Exception as e:
                result_text = f"Error: {e}"
                had_error = True
                raise
            finally:
                elapsed = time.time() - start_time
                # 采集后快照 + 计算差量
                hw_after = tracer._hw_snapshot()
                hw_delta = tracer._hw_delta(hw_before, hw_after)
                tracer.track_tool_end(tool_name)
                
                # 记录工具调用事件到trace文件（X事件，含完整硬件指标）
                dur_us = int(elapsed * 1_000_000)
                # 使用虚拟tid=2表示工具调用线程，与主线程区分
                tracer._add_event(
                    tool_name, "X", span_ts, 
                    tid=2,  # 工具调用使用独立的tid
                    cat="tool", 
                    dur=dur_us,
                    args={**tool_input, 'hw': hw_delta}
                )
                
                # 更新时间线
                self._turn_timeline['last_event_end'] = span_ts + dur_us
                self._turn_timeline['tool_spans'].append({
                    'name': tool_name,
                    'start': span_ts,
                    'duration_us': dur_us
                })
                
                # 累积到统计器（附带并发数和错误状态）
                try:
                    tracer.accumulate_tool_hw(
                        tool_name,
                        hw_delta,
                        concurrent_count=concurrent_count,
                        had_error=had_error,
                    )
                except Exception:
                    pass

                # ---- 工具结果框 ----
                # 截断过长结果
                display_text = result_text
                max_len = 800
                if len(display_text) > max_len:
                    display_text = display_text[:max_len] + f"\n\n[dim]... (truncated, {len(result_text)} chars total, elapsed {elapsed:.2f}s)[/dim]"
                else:
                    display_text += f"\n\n[dim]({len(result_text)} chars, elapsed {elapsed:.2f}s)[/dim]"

                # 硬件摘要行（优先使用线程级CPU，并发安全）
                hw_parts = []
                # 优先显示线程级CPU（并发安全），不可用时降级为进程级
                if hw_delta.get('thread_cpu_ms', -1) >= 0:
                    cpu_display = hw_delta['thread_cpu_ms']
                    cpu_label = 'thread'
                else:
                    cpu_display = hw_delta['cpu_total_ms']
                    cpu_label = 'process'
                hw_parts.append(f"CPU[{cpu_label}] {cpu_display:.1f}ms ({hw_delta['cpu_pct_end']:.0f}%)")
                if hw_delta['mem_delta_kb'] != 0:
                    hw_parts.append(f"RSS {hw_delta['mem_delta_kb']:+d}KB [dim](process-level)[/dim]")
                if hw_delta['io_read_ops'] or hw_delta['io_write_ops']:
                    hw_parts.append(f"blk {hw_delta['io_read_ops']}r/{hw_delta['io_write_ops']}w")
                # 文件 I/O 字节数
                io_r_kb = hw_delta.get('io_read_bytes', 0) / 1024
                io_w_kb = hw_delta.get('io_write_bytes', 0) / 1024
                if io_r_kb > 0 or io_w_kb > 0:
                    hw_parts.append(f"file {io_r_kb:.1f}KB↓/{io_w_kb:.1f}KB↑")
                # 访问的文件
                fa = hw_delta.get('files_accessed', [])
                if fa:
                    names = [os.path.basename(f) for f in fa[:3]]
                    suffix = f" (+{len(fa)-3}more)" if len(fa) > 3 else ""
                    hw_parts.append(f"files[{', '.join(names)}{suffix}]")
                # 网络 I/O
                net_sent = hw_delta.get('net_sent_bytes', 0)
                net_recv = hw_delta.get('net_recv_bytes', 0)
                if net_sent > 0 or net_recv > 0:
                    hw_parts.append(f"net {net_recv/1024:.1f}KB↓/{net_sent/1024:.1f}KB↑")
                if hw_delta['ctx_total'] > 0:
                    hw_parts.append(f"ctx {hw_delta['ctx_total']}")
                if hw_delta['page_faults_maj'] > 0:
                    hw_parts.append(f"pgflt {hw_delta['page_faults_maj']}maj")
                if concurrent_count > 1:
                    hw_parts.append(f"[bold magenta]concurrent={concurrent_count}[/bold magenta]")
                if hw_parts:
                    display_text += f"\n[dim]hw: {' | '.join(hw_parts)}[/dim]"

                # 判断结果状态
                is_error = had_error or "error" in result_text.lower()[:100] or "failed" in result_text.lower()[:100]
                border_style = "red" if is_error else "green"
                icon = "❌" if is_error else "✅"

                console.print(
                    Panel.fit(
                        display_text,
                        title=f"[bold {border_style}]{icon} {tool_name} result[/bold {border_style}]",
                        border_style=border_style,
                        padding=(0, 1),
                    )
                )

                # 记录工具统计
                try:
                    self.memory.record_tool_usage(
                        tool_name=tool_name,
                        success=not is_error,
                        execution_time=elapsed,
                    )
                except Exception:
                    pass

        # 注册中间件到 Toolkit
        self.toolkit.register_middleware(tool_display_middleware)
        self.logger.info("Tool display middleware registered")

    async def run(self):
        """
        Main loop: invoke the agent repeatedly, never exits automatically.
        """
        # 生成唯─会话 ID，区分不同运行实例
        from datetime import datetime
        self.session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # 记录会话开始
        self.tracer.event("session.start", category="lifecycle")
        self.memory.add_conversation(self.session_id, "system", "会话开始")
        self.logger.info(f"Agent 会话开始 (session_id={self.session_id})")
        
        turn_count = 0
        
        try:
            while True:
                # Get user input
                self.console.print("\n[bold cyan]━━ User Input ━━[/bold cyan]")
                user_input = input("> ")
                
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
                
                turn_count += 1
                turn_name = f"turn.{turn_count}"
                
                # 记录对话
                self.memory.add_conversation(self.session_id, "user", user_input)
                
                # Invoke agent
                self.console.print("")
                self.console.print(Rule("[bold magenta]🤖 Assistant[/bold magenta]", style="magenta"))
                
                # 重置 turn 时间线
                self._turn_timeline['turn_start'] = self.tracer._now_us()
                self._turn_timeline['last_event_end'] = self._turn_timeline['turn_start']
                self._turn_timeline['llm_spans'] = []
                self._turn_timeline['tool_spans'] = []
                self._turn_timeline['thinking_start_us'] = None  # 每轮重置
                self._turn_timeline['thinking_end_us'] = None    # 每轮重置
                
                async with self.tracer.async_span(turn_name, category="turn", input=user_input[:80]):
                    # 刷新记忆上下文到 system prompt（确保运行期间新增的记忆也能用上）
                    self._refresh_memory_context()
                    
                    # 创建用户消息
                    user_msg = Msg(
                        name="user",
                        content=user_input,
                        role="user"
                    )
                    
                    # 调用 AgentScope agent
                    response = await self.agent(user_msg)
                    
                    # turn结束：将最终 LLM 推理阶段拆分为 thinking + output 两段
                    turn_end_us = self.tracer._now_us()
                    if self._turn_timeline['last_event_end'] is not None:
                        final_gap = turn_end_us - self._turn_timeline['last_event_end']
                        if final_gap > 50_000:  # 50ms
                            llm_start = self._turn_timeline['last_event_end']
                            thinking_start = self._turn_timeline.get('thinking_start_us')
                            thinking_end   = self._turn_timeline.get('thinking_end_us')

                            if thinking_start and thinking_end and thinking_start >= llm_start:
                                # 有 thinking 阶段：分三段记录
                                pre_gap = thinking_start - llm_start
                                if pre_gap > 50_000:
                                    self.tracer._add_event(
                                        "llm.pre_thinking", "X", llm_start,
                                        tid=3, cat="llm", dur=pre_gap,
                                        args={"inferred": True, "phase": "pre_thinking"}
                                    )
                                think_dur = thinking_end - thinking_start
                                if think_dur > 0:
                                    self.tracer._add_event(
                                        "llm.thinking", "X", thinking_start,
                                        tid=3, cat="llm", dur=think_dur,
                                        args={"inferred": True, "phase": "thinking"}
                                    )
                                output_dur = turn_end_us - thinking_end
                                if output_dur > 50_000:
                                    self.tracer._add_event(
                                        "llm.output", "X", thinking_end,
                                        tid=3, cat="llm", dur=output_dur,
                                        args={"inferred": True, "phase": "output"}
                                    )
                            else:
                                # 无 thinking 阶段：整个计为 reasoning
                                self.tracer._add_event(
                                    "llm.reasoning", "X", llm_start,
                                    tid=3, cat="llm", dur=final_gap,
                                    args={"inferred": True, "phase": "final_response"}
                                )
                    
                    # 保存助手回复到记忆系统
                    if response and response.content:
                        resp_text = self._extract_response_text(response)
                        if resp_text:
                            self.memory.add_conversation(self.session_id, "assistant", resp_text[:500])
                    
                    self.console.print("")
                    self.console.print(Rule(style="dim"))
        
        finally:
            # 记录会话结束
            self.tracer.event("session.end", category="lifecycle")
            self.memory.add_conversation(self.session_id, "system", "会话结束")
            self.logger.info("Agent 会话结束")
            
            # 保存 trace 文件
            try:
                trace_path = self.tracer.save()
                stats = self.tracer.stats()
                self.console.print(
                    Panel.fit(
                        Markdown(
                            f"📊 **Trace saved**: `{trace_path}`\n\n"
                            f"- Total events: {stats['total_events']}\n"
                            f"- Total duration: {stats['total_duration_ms']:.0f}ms\n"
                            f"- Open with: **chrome://tracing** or **https://ui.perfetto.dev**"
                        ),
                        title="[dim]Trace[/dim]",
                        border_style="dim",
                    )
                )
            except Exception as e:
                self.logger.warning(f"保存 trace 失败: {e}")
    
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
            
            # 加载上次会话的最近对话（跨会话记忆）
            # 查找上一次会话的 session_id
            prev_session_id = self._get_previous_session_id()
            if prev_session_id:
                last_history = self.memory.get_conversation_history(prev_session_id, limit=10)
                prev_history = [
                    msg for msg in last_history
                    if msg.get('role', '') in ('user', 'assistant') and msg.get('content', '')
                    and '会话开始' not in msg.get('content', '') and '会话结束' not in msg.get('content', '')
                ][:6]  # 最多保留 6 条
                if prev_history:
                    hist_lines = []
                    for msg in prev_history:
                        role = msg['role']
                        content = msg['content'][:150]  # 截断过长内容
                        hist_lines.append(f"  [{role}] {content}")
                    context_parts.append("Recent Conversations (previous session):\n" + "\n".join(hist_lines))
            
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

    def _get_previous_session_id(self) -> str | None:
        """查找上一次会话的 session_id"""
        try:
            import sqlite3
            with sqlite3.connect(self.memory.db_path) as conn:
                cur = conn.cursor()
                # 查找最近一个已结束的会话的 session_id
                cur.execute('''
                    SELECT DISTINCT session_id FROM conversation_history
                    WHERE session_id != ? AND role = 'system' AND content = '会话结束'
                    ORDER BY rowid DESC LIMIT 1
                ''', (getattr(self, 'session_id', 'current'),))
                row = cur.fetchone()
                if row:
                    return row[0]
                # 回退：查找任何非当前会话的 session_id
                cur.execute('''
                    SELECT DISTINCT session_id FROM conversation_history
                    WHERE session_id != ? AND session_id != 'main'
                    ORDER BY rowid DESC LIMIT 1
                ''', (getattr(self, 'session_id', 'current'),))
                row = cur.fetchone()
                if row:
                    return row[0]
                # 最终回退：尝试用旧的 'main' session_id
                cur.execute('''
                    SELECT COUNT(*) FROM conversation_history
                    WHERE session_id = 'main' AND role IN ('user', 'assistant')
                ''')
                if cur.fetchone()[0] > 0:
                    return 'main'
        except Exception as e:
            self.logger.warning(f"查找上一次会话 ID 失败: {e}")
        return None

    def _refresh_memory_context(self):
        """每轮对话前刷新记忆上下文到 agent 的 system prompt"""
        try:
            memory_context = self._build_memory_context()
            if memory_context and hasattr(self.agent, '_sys_prompt'):
                # 去掉旧的记忆上下文，追加新的
                base_prompt = self.agent._sys_prompt
                # 移除之前追加的 Session Context
                marker = "\n\n## Session Context:"
                if marker in base_prompt:
                    base_prompt = base_prompt[:base_prompt.index(marker)]
                # 追加最新记忆
                self.agent._sys_prompt = base_prompt + f"\n\n## Session Context:\n{memory_context}"
        except Exception as e:
            self.logger.warning(f"刷新记忆上下文失败: {e}")

    def _extract_response_text(self, response) -> str:
        """从 AgentScope 响应中提取纯文本内容"""
        text_parts = []
        
        if isinstance(response.content, str):
            text_parts.append(response.content)
        elif isinstance(response.content, list):
            for block in response.content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    if text.strip():
                        text_parts.append(text)
                elif hasattr(block, "text"):
                    text = block.text
                    if text and text.strip():
                        text_parts.append(text)
        
        return "\n".join(text_parts)

    async def close(self):
        """清理资源"""
        pass  # AgentScope 不需要特殊的清理

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
        
        elif cmd == "/perf":
            report = self.tracer.get_tool_hw_report()
            conc  = self.tracer.get_concurrent_stats()
            if not report:
                return "No tool hardware metrics yet. Execute some tools first."

            lines = ["\U0001f4ca Tool Hardware Report (this session)\n"]
            lines.append(f"  Peak concurrent tools: {conc['peak_concurrent']}")
            lines.append("")

            # 按墙上时锏合计降序排列
            sorted_tools = sorted(report.items(), key=lambda x: x[1]['total_wall_ms'], reverse=True)

            for tool_name, hw in sorted_tools:
                err_tag  = f" [red]\u26a0 {hw['errors']}err/{hw['error_rate_pct']:.0f}%[/red]" if hw['errors'] else ""
                conc_tag = f" [magenta]peak_conc={hw['peak_concurrent']}[/magenta]" if hw['peak_concurrent'] > 1 else ""
                sample_tag = f" [yellow]\u26a0 small sample({hw['calls']})[/yellow]" if hw.get('small_sample', False) else ""
                lines.append(f"  [bold cyan]\U0001f527 {tool_name}[/bold cyan]  calls={hw['calls']}{err_tag}{conc_tag}{sample_tag}")
                lines.append(
                    f"     Wall  avg={hw['avg_wall_ms']:.0f}ms  "
                    f"min={hw['min_wall_ms']:.0f}  max={hw['max_wall_ms']:.0f}  "
                    f"p50={hw['p50_wall_ms']:.0f}  p95={hw['p95_wall_ms']:.0f}  p99={hw['p99_wall_ms']:.0f}"
                )
                lines.append(
                    f"     CPU   avg={hw['avg_cpu_ms']:.1f}ms  "
                    f"min={hw['min_cpu_ms']:.1f}  max={hw['max_cpu_ms']:.1f}  "
                    f"p50={hw['p50_cpu_ms']:.1f}  p95={hw['p95_cpu_ms']:.1f}  "
                    f"cpu%={hw['cpu_pct']:.0f}%  total={hw['total_cpu_ms']:.1f}ms  "
                )
                # CPU来源标注：进程级时用黄色警告
                if hw['cpu_source'] == 'process':
                    lines[-1] += f" [yellow]\u26a0 src={hw['cpu_source']} (concurrent-safe)[/yellow]"
                else:
                    lines[-1] += f" [dim](src={hw['cpu_source']})[/dim]"
                mem_line = (
                    f"     Mem   \u0394rss={hw['total_mem_delta_kb']:+d}KB  "
                    f"avg\u0394={hw['avg_mem_delta_kb']:+.1f}KB  "
                    f"peak_rss={hw['peak_mem_rss_kb']}KB"
                )
                if hw['total_vms_delta_kb'] != 0:
                    mem_line += f"  \u0394vms={hw['total_vms_delta_kb']:+d}KB"
                if hw['total_swap_delta_kb'] != 0:
                    mem_line += f"  \u0394swap={hw['total_swap_delta_kb']:+d}KB"
                lines.append(mem_line)
                io_parts = []
                if hw['total_io_read'] or hw['total_io_write']:
                    io_parts.append(f"blk {hw['total_io_read']}r/{hw['total_io_write']}w (avg {hw['avg_io_read']:.0f}r/{hw['avg_io_write']:.0f}w)")
                if hw['total_page_faults_min'] or hw['total_page_faults_maj']:
                    io_parts.append(f"pgflt {hw['total_page_faults_min']}min/{hw['total_page_faults_maj']}maj")
                # 网络 I/O
                if hw.get('total_net_sent_kb', 0) or hw.get('total_net_recv_kb', 0):
                    io_parts.append(f"net {hw['total_net_recv_kb']:.0f}KB↓/{hw['total_net_sent_kb']:.0f}KB↑")
                # 文件 I/O 字节数
                if hw.get('total_io_read_kb', 0) or hw.get('total_io_write_kb', 0):
                    io_parts.append(f"file {hw['total_io_read_kb']:.1f}KB↓/{hw['total_io_write_kb']:.1f}KB↑ (avg {hw['avg_io_read_kb']:.1f}/{hw['avg_io_write_kb']:.1f})")
                if io_parts:
                    lines.append(f"     IO    {' | '.join(io_parts)}")
                # 访问的文件列表
                accessed = hw.get('files_accessed', [])
                if accessed:
                    file_names = [os.path.basename(f) for f in accessed[:5]]
                    if len(accessed) > 5:
                        file_names.append(f"+{len(accessed)-5} more")
                    lines.append(f"     Files {', '.join(file_names)}")
                if hw['total_ctx_switches'] > 0:
                    lines.append(f"     Ctx   total={hw['total_ctx_switches']}  avg={hw['avg_ctx_switches']:.1f}")
                lines.append("")

            total_calls = sum(hw['calls']              for hw in report.values())
            total_cpu   = sum(hw['total_cpu_ms']       for hw in report.values())
            total_wall  = sum(hw['total_wall_ms']      for hw in report.values())
            total_io_r  = sum(hw['total_io_read']      for hw in report.values())
            total_io_w  = sum(hw['total_io_write']     for hw in report.values())
            total_mem   = sum(hw['total_mem_delta_kb'] for hw in report.values())
            total_errs  = sum(hw['errors']             for hw in report.values())
            cpu_pct_overall = round(total_cpu / total_wall * 100, 1) if total_wall > 0 else 0
            lines.append(
                f"  [bold]\U0001f4c8 Session Total[/bold]  calls={total_calls}  errors={total_errs}  "
                f"wall={total_wall:.0f}ms  cpu={total_cpu:.1f}ms ({cpu_pct_overall:.0f}%)  "
                f"IO={total_io_r}r/{total_io_w}w  \u0394mem={total_mem:+d}KB"
            )
            return "\n".join(lines)
        
        elif cmd == "/help":
            return ("🔧 Special Commands:\n"
                   "  /rollback        - View operation history\n"
                   "  /rollback <id>   - Undo a specific operation\n"
                   "  /history         - View conversation history\n"
                   "  /stats           - View tool usage statistics\n"
                   "  /perf            - View tool hardware costs (CPU/MEM/IO)\n"
                   "  /index           - Re-index current codebase\n"
                   "  /help            - Show this help")
        
        return None
