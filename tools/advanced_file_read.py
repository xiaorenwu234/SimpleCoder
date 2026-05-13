"""高级文件读取工具 - AgentScope 格式"""
import asyncio
import os
from agentscope.tool import ToolResponse
from agentscope.message import TextBlock


async def read_file(
    file_path: str,
    offset: int = 0,
    length: int = 1000
) -> ToolResponse:
    """Read contents from files. Supports partial reading with offset and length.
    
    Examples:
    - offset: 0, length: 10 → First 10 lines
    - offset: 100, length: 5 → Lines 100-104
    - offset: -20 → Last 20 lines (tail)
    - offset: -5, length: 10 → Last 5 lines
    
    Args:
        file_path: Path to file (absolute or relative)
        offset: Start line (default: 0, negative for tail)
        length: Max lines to read (default: 1000)
    
    Returns:
        ToolResponse with file content
    """
    try:
        # Resolve relative paths
        if not os.path.isabs(file_path):
            file_path = os.path.join(os.getcwd(), file_path)
        
        if not os.path.exists(file_path):
            return ToolResponse(
                content=[TextBlock(type="text", text=f"Error: File not found: {file_path}")]
            )
        
        # Use asyncio.to_thread 避免阻塞事件循环
        def read_sync():
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                total_lines = len(lines)
            
            # Handle negative offset (tail)
            if offset < 0:
                start = max(0, total_lines + offset)
                selected_lines = lines[start:]
            else:
                start = min(offset, total_lines)
                end = min(start + length, total_lines)
                selected_lines = lines[start:end]
            
            content = "".join(selected_lines)
            status = f"[Read {len(selected_lines)} lines from line {start} (total: {total_lines} lines)]"
            
            return f"{status}\n\n{content}"
        
        result = await asyncio.to_thread(read_sync)
        
        return ToolResponse(
            content=[TextBlock(type="text", text=result)]
        )
            
    except Exception as e:
        return ToolResponse(
            content=[TextBlock(type="text", text=f"Error reading file: {str(e)}")]
        )
