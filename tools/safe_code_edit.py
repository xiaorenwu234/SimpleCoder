"""
增强版代码编辑工具 - 集成操作回滚和自动备份
"""
from langchain.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Optional
import os
from tools.operation_rollback import OperationRollback


class SafeCodeEditInput(BaseModel):
    file_path: str = Field(..., description="Path to the file to edit")
    operation: str = Field(
        ...,
        description="Edit operation: 'replace', 'insert', 'delete'"
    )
    start_line: int = Field(
        ...,
        description="Start line number (1-based)"
    )
    end_line: Optional[int] = Field(
        None,
        description="End line number (1-based, inclusive). For insert, this is where to insert after."
    )
    new_content: Optional[str] = Field(
        None,
        description="New content to insert or replace with"
    )
    description: Optional[str] = Field(
        None,
        description="Description of the edit (for rollback tracking)"
    )


class SafeCodeEditTool(BaseTool):
    name: str = "safe_code_edit"
    description: str = """Safely edit code in a file with automatic backup and rollback support.
    
    This is the enhanced version of code_edit with:
    - Automatic file backup before editing
    - Rollback tracking via operation ID
    - Edit description for history tracking
    
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
    """
    args_schema: type = SafeCodeEditInput

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._rollback = OperationRollback()

    def _run(self, file_path: str, operation: str, start_line: int,
             end_line: Optional[int] = None, new_content: Optional[str] = None,
             description: str = "") -> str:
        """Edit code in file with backup."""
        try:
            # Resolve relative paths
            if not os.path.isabs(file_path):
                file_path = os.path.join(os.getcwd(), file_path)
            
            if not os.path.exists(file_path):
                return f"Error: File not found: {file_path}"
            
            # 备份文件
            backup_path = self._rollback.backup_file(file_path, description or f"{operation} at line {start_line}")
            
            # Read file
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            total_lines = len(lines)
            
            # Validate line numbers
            if start_line < 1 or start_line > total_lines:
                return f"Error: start_line {start_line} out of range (1-{total_lines})"
            
            if operation == "replace":
                if end_line is None:
                    return "Error: 'replace' operation requires end_line"
                if new_content is None:
                    return "Error: 'replace' operation requires new_content"
                if end_line < start_line or end_line > total_lines:
                    return f"Error: end_line {end_line} out of range"
                
                # Replace lines
                new_lines = lines[:start_line-1]
                if not new_content.endswith("\n"):
                    new_content += "\n"
                new_lines.append(new_content)
                new_lines.extend(lines[end_line:])
                
                # Write back
                with open(file_path, "w", encoding="utf-8") as f:
                    f.writelines(new_lines)
                
                # Record operation
                self._rollback.record_operation(
                    operation_type='edit',
                    file_path=file_path,
                    backup_path=backup_path,
                    description=description or f"Replaced lines {start_line}-{end_line}"
                )
                
                return (f"✅ Replaced lines {start_line}-{end_line} in {file_path}\n"
                       f"   Total lines: {total_lines} → {len(new_lines)}\n"
                       f"   Backup: {backup_path}")
            
            elif operation == "insert":
                if new_content is None:
                    return "Error: 'insert' operation requires new_content"
                
                # Insert after start_line
                new_lines = lines[:start_line]
                if not new_content.endswith("\n"):
                    new_content += "\n"
                new_lines.append(new_content)
                new_lines.extend(lines[start_line:])
                
                # Write back
                with open(file_path, "w", encoding="utf-8") as f:
                    f.writelines(new_lines)
                
                # Record operation
                self._rollback.record_operation(
                    operation_type='insert',
                    file_path=file_path,
                    backup_path=backup_path,
                    description=description or f"Inserted after line {start_line}"
                )
                
                return (f"✅ Inserted content after line {start_line} in {file_path}\n"
                       f"   Total lines: {total_lines} → {len(new_lines)}\n"
                       f"   Backup: {backup_path}")
            
            elif operation == "delete":
                if end_line is None:
                    return "Error: 'delete' operation requires end_line"
                if end_line < start_line or end_line > total_lines:
                    return f"Error: end_line {end_line} out of range"
                
                # Delete lines
                new_lines = lines[:start_line-1] + lines[end_line:]
                
                # Write back
                with open(file_path, "w", encoding="utf-8") as f:
                    f.writelines(new_lines)
                
                # Record operation
                self._rollback.record_operation(
                    operation_type='delete',
                    file_path=file_path,
                    backup_path=backup_path,
                    description=description or f"Deleted lines {start_line}-{end_line}"
                )
                
                return (f"✅ Deleted lines {start_line}-{end_line} from {file_path}\n"
                       f"   Total lines: {total_lines} → {len(new_lines)}\n"
                       f"   Backup: {backup_path}")
            
            else:
                return f"Error: Unknown operation '{operation}'. Use 'replace', 'insert', or 'delete'."
        
        except Exception as e:
            return f"Error editing file: {str(e)}"
