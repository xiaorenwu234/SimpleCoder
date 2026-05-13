"""简单文件读取工具 - AgentScope 格式"""
import asyncio
import os
from agentscope.tool import ToolResponse
from agentscope.message import TextBlock


async def file_read(file_path: str) -> ToolResponse:
    """Reads a file designated by the supplied absolute path and returns the content as string.
    
    If the path is not absolute, the tool will attempt to resolve it against the current working directory.
    Handle errors gracefully and return a helpful message when the file cannot be found or opened.
    
    Args:
        file_path: Absolute path to the file to read
    
    Returns:
        ToolResponse with file content
    """
    try:
        # Resolve relative paths
        if not os.path.isabs(file_path):
            file_path = os.path.join(os.getcwd(), file_path)
        
        # Use asyncio.to_thread 避免阻塞
        def read_sync():
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        
        content = await asyncio.to_thread(read_sync)
        
        return ToolResponse(
            content=[TextBlock(type="text", text=content)]
        )
    except FileNotFoundError:
        return ToolResponse(
            content=[TextBlock(type="text", text=f"Error: File not found: {file_path}")]
        )
    except Exception as e:
        return ToolResponse(
            content=[TextBlock(type="text", text=f"Error reading file: {str(e)}")]
        )
