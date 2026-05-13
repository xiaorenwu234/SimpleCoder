"""代码编辑工具 - AgentScope 格式"""
import os
from typing import Optional
from agentscope.tool import ToolResponse
from agentscope.message import TextBlock


async def code_edit(
    file_path: str,
    operation: str,
    start_line: int,
    end_line: Optional[int] = None,
    new_content: Optional[str] = None
) -> ToolResponse:
    """Precisely edit code in a file.
    
    Operations:
    - replace: Replace lines start_line to end_line with new_content
    - insert: Insert new_content after start_line (end_line ignored)
    - delete: Delete lines start_line to end_line
    
    Examples:
    1. Replace lines 10-15 with new code:
       operation='replace', start_line=10, end_line=15, new_content='...'
    
    2. Insert code after line 5:
       operation='insert', start_line=5, new_content='...'
    
    3. Delete lines 20-25:
       operation='delete', start_line=20, end_line=25
    
    Line numbers are 1-based (first line is 1).
    
    Args:
        file_path: Path to the file to edit
        operation: Edit operation: 'replace', 'insert', 'delete'
        start_line: Start line number (1-based)
        end_line: End line number (1-based, inclusive). For insert, this is where to insert after.
        new_content: New content to insert or replace with
    
    Returns:
        ToolResponse with result
    """
    try:
        # Resolve relative paths
        if not os.path.isabs(file_path):
            file_path = os.path.join(os.getcwd(), file_path)
        
        if not os.path.exists(file_path):
            return ToolResponse(
                content=[TextBlock(type="text", text=f"Error: File not found: {file_path}")]
            )
        
        # Read file
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        total_lines = len(lines)
        
        # Validate line numbers
        if start_line < 1 or start_line > total_lines:
            return ToolResponse(
                content=[TextBlock(type="text", text=f"Error: start_line {start_line} out of range (1-{total_lines})")]
            )
        
        if operation == "replace":
            if end_line is None:
                return ToolResponse(
                    content=[TextBlock(type="text", text="Error: 'replace' operation requires end_line")]
                )
            if new_content is None:
                return ToolResponse(
                    content=[TextBlock(type="text", text="Error: 'replace' operation requires new_content")]
                )
            if end_line < start_line or end_line > total_lines:
                return ToolResponse(
                    content=[TextBlock(type="text", text=f"Error: end_line {end_line} out of range")]
                )
            
            # Replace lines
            new_lines = lines[:start_line-1]
            # Ensure new_content ends with newline
            if not new_content.endswith("\n"):
                new_content += "\n"
            new_lines.append(new_content)
            new_lines.extend(lines[end_line:])
            
            # Write back
            with open(file_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            
            return ToolResponse(
                content=[TextBlock(type="text", 
                    text=f"✅ Replaced lines {start_line}-{end_line} in {file_path}\n   Total lines: {total_lines} → {len(new_lines)}")]
            )
        
        elif operation == "insert":
            if new_content is None:
                return ToolResponse(
                    content=[TextBlock(type="text", text="Error: 'insert' operation requires new_content")]
                )
            
            # Insert after start_line
            new_lines = lines[:start_line]
            if not new_content.endswith("\n"):
                new_content += "\n"
            new_lines.append(new_content)
            new_lines.extend(lines[start_line:])
            
            # Write back
            with open(file_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            
            return ToolResponse(
                content=[TextBlock(type="text",
                    text=f"✅ Inserted content after line {start_line} in {file_path}\n   Total lines: {total_lines} → {len(new_lines)}")]
            )
        
        elif operation == "delete":
            if end_line is None:
                return ToolResponse(
                    content=[TextBlock(type="text", text="Error: 'delete' operation requires end_line")]
                )
            if end_line < start_line or end_line > total_lines:
                return ToolResponse(
                    content=[TextBlock(type="text", text=f"Error: end_line {end_line} out of range")]
                )
            
            # Delete lines
            new_lines = lines[:start_line-1] + lines[end_line:]
            
            # Write back
            with open(file_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            
            return ToolResponse(
                content=[TextBlock(type="text",
                    text=f"✅ Deleted lines {start_line}-{end_line} from {file_path}\n   Total lines: {total_lines} → {len(new_lines)}")]
            )
        
        else:
            return ToolResponse(
                content=[TextBlock(type="text", text=f"Error: Unknown operation '{operation}'. Use 'replace', 'insert', or 'delete'.")]
            )
    
    except Exception as e:
        return ToolResponse(
            content=[TextBlock(type="text", text=f"Error editing file: {str(e)}")]
        )
