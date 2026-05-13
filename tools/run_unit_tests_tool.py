"""运行单元测试工具 - AgentScope 格式"""
import asyncio
from agentscope.tool import ToolResponse
from agentscope.message import TextBlock


async def run_unit_tests() -> ToolResponse:
    """Run unit tests using pytest.
    
    Returns:
        ToolResponse with test results
    """
    try:
        # 异步运行测试
        process = await asyncio.create_subprocess_exec(
            "uv", "run", "pytest", "-xvs", "tests/",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        stdout_str = stdout.decode('utf-8', errors='replace')
        stderr_str = stderr.decode('utf-8', errors='replace')
        
        result = stdout_str if stdout_str else stderr_str
        
        return ToolResponse(
            content=[TextBlock(type="text", text=result)]
        )
            
    except Exception as e:
        return ToolResponse(
            content=[TextBlock(type="text", text=f"Error running tests: {str(e)}")]
        )
