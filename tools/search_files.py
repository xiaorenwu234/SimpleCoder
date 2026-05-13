"""文件搜索工具 - AgentScope 格式"""
import os
import fnmatch
from agentscope.tool import ToolResponse
from agentscope.message import TextBlock


def _format_size(size: int) -> str:
    """Format file size."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


async def search_files(
    pattern: str = "*.py",
    path: str = ".",
    recursive: bool = True
) -> ToolResponse:
    """Search for files matching a pattern.
    
    Uses glob patterns for matching.
    
    Examples:
    - "*.py" - All Python files
    - "*.txt" - All text files
    - "test_*" - Files starting with test_
    
    Args:
        path: Directory to search (default: current directory)
        pattern: Glob pattern (default: *.py)
        recursive: Search recursively (default: True)
    
    Returns:
        ToolResponse with search results
    """
    try:
        # Resolve relative paths
        if not os.path.isabs(path):
            path = os.path.join(os.getcwd(), path)
        
        if not os.path.exists(path):
            return ToolResponse(
                content=[TextBlock(type="text", text=f"Error: Directory not found: {path}")]
            )
        
        matched_files = []
        
        if recursive:
            for root, dirs, files in os.walk(path):
                for filename in files:
                    if fnmatch.fnmatch(filename, pattern):
                        file_path = os.path.join(root, filename)
                        try:
                            size = os.path.getsize(file_path)
                            matched_files.append((file_path, size))
                        except:
                            matched_files.append((file_path, 0))
        else:
            for filename in os.listdir(path):
                if fnmatch.fnmatch(filename, pattern):
                    file_path = os.path.join(path, filename)
                    try:
                        size = os.path.getsize(file_path)
                        matched_files.append((file_path, size))
                    except:
                        matched_files.append((file_path, 0))
        
        if not matched_files:
            return ToolResponse(
                content=[TextBlock(type="text", text=f"No files matching '{pattern}' in {path}")]
            )
        
        # Format output
        result = [f"Found {len(matched_files)} files matching '{pattern}':", ""]
        for file_path, size in matched_files:
            size_str = _format_size(size)
            result.append(f"📄 {file_path} ({size_str})")
        
        return ToolResponse(
            content=[TextBlock(type="text", text="\n".join(result))]
        )
            
    except Exception as e:
        return ToolResponse(
            content=[TextBlock(type="text", text=f"Error searching files: {str(e)}")]
        )
