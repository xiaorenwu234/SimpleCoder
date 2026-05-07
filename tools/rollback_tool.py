"""
回滚操作工具 - LangChain Tool 封装
"""
from langchain.tools import BaseTool
from pydantic import BaseModel, Field
from typing import Optional
from tools.operation_rollback import OperationRollback


class RollbackInput(BaseModel):
    operation_id: Optional[int] = Field(None, description="Operation ID to rollback (use rollback_history to find IDs)")
    list_history: bool = Field(False, description="List recent operation history instead of rolling back")
    limit: int = Field(20, description="Number of history entries to show")


class RollbackTool(BaseTool):
    name: str = "rollback"
    description: str = """Rollback file operations or view operation history.
    
    This tool allows you to:
    - View operation history (list_history=True)
    - Rollback a specific operation by ID
    
    After editing files with safe_code_edit, you can use this tool to undo changes.
    
    Args:
        operation_id: The operation ID to rollback
        list_history: Set to True to list recent operations
        limit: Number of history entries to show (default: 20)
    """
    args_schema: type = RollbackInput

    def __init__(self, db_path: str = None, **kwargs):
        super().__init__(**kwargs)
        self._db_path = db_path
        self._rollback = None
    
    def _get_rollback(self):
        """懒加载 OperationRollback 实例"""
        if self._rollback is None:
            self._rollback = OperationRollback(db_path=self._db_path)
        return self._rollback

    def _run(self, operation_id: int = None, list_history: bool = False, limit: int = 20) -> str:
        """Rollback or list operations."""
        try:
            rollback = self._get_rollback()
            
            if list_history:
                history = rollback.get_operation_history(limit)
                if not history:
                    return "No operation history found."
                
                output = [f"📋 Operation History (last {limit}):\n"]
                for op in history:
                    status = "✅" if op['success'] else "❌"
                    output.append(f"  {status} #{op['id']} [{op['operation_type']}] {op['file_path']}")
                    output.append(f"     Time: {op['timestamp']}")
                    if op.get('description'):
                        output.append(f"     Description: {op['description']}")
                
                return "\n".join(output)
            
            if operation_id is None:
                return "Please provide either operation_id to rollback or list_history=True to view history."
            
            result = rollback.rollback_operation(operation_id)
            if result['success']:
                return f"✅ {result['message']}\n   File: {result.get('file_path', 'N/A')}"
            else:
                return f"❌ Rollback failed: {result.get('error', 'Unknown error')}"
            
        except Exception as e:
            return f"Error: {str(e)}"
