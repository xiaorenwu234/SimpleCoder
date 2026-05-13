"""列目录工具 - AgentScope 格式"""
import os
from agentscope.tool import ToolResponse
from agentscope.message import TextBlock


def _format_size(size: int) -> str:
    """Format file size."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


async def list_directory(
    path: str = ".",
    recursive: bool = False
) -> ToolResponse:
    """List contents of a directory.
    
    Shows files and directories with sizes.
    
    Args:
        path: Directory path (default: current directory)
        recursive: List recursively (default: False)
    
    Returns:
        ToolResponse with directory listing
    """
    try:
        # Resolve relative paths
        if not os.path.isabs(path):
            path = os.path.join(os.getcwd(), path)
        
        if not os.path.exists(path):
            return ToolResponse(
                content=[TextBlock(type="text", text=f"Error: Directory not found: {path}")]
            )
        
        if not os.path.isdir(path):
            return ToolResponse(
                content=[TextBlock(type="text", text=f"Error: Not a directory: {path}")]
            )
        
        result = []
        
        if recursive:
            for root, dirs, files in os.walk(path):
                level = root.replace(path, "").count(os.sep)
                indent = "  " * level
                result.append(f"{indent}📁 {os.path.basename(root)}/") 
                
                subindent = "  " * (level + 1)
                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        size = os.path.getsize(file_path)
                        size_str = _format_size(size)
                        result.append(f"{subindent}📄 {file} ({size_str})")
                    except:
                        result.append(f"{subindent}📄 {file}")
        else:
            items = os.listdir(path)
            items.sort()
            
            for item in items:
                item_path = os.path.join(path, item)
                if os.path.isdir(item_path):
                    result.append(f"📁 {item}/")
                else:
                    try:
                        size = os.path.getsize(item_path)
                        size_str = _format_size(size)
                        result.append(f"📄 {item} ({size_str})")
                    except:
                        result.append(f"📄 {item}")
        
        return ToolResponse(
            content=[TextBlock(type="text", text=f"Directory: {path}\n" + "\n".join(result))]
        )
            
    except Exception as e:
        return ToolResponse(
            content=[TextBlock(type="text", text=f"Error listing directory: {str(e)}")]
        )
