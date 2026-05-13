"""
回滚操作工具 - AgentScope 格式
"""
from typing import Optional
from agentscope.tool import ToolResponse
from agentscope.message import TextBlock
from tools.operation_rollback import OperationRollback


async def rollback(
    operation_id: Optional[int] = None,
    list_history: bool = False,
    limit: int = 20
) -> ToolResponse:
    """Rollback file operations or view operation history.
    
    This tool allows you to:
    - View operation history (list_history=True)
    - Rollback a specific operation by ID
    
    After editing files with safe_code_edit, you can use this tool to undo changes.
    
    Args:
        operation_id: The operation ID to rollback
        list_history: Set to True to list recent operations
        limit: Number of history entries to show (default: 20)
    
    Returns:
        ToolResponse with result
    """
    try:
        rollback_mgr = OperationRollback()
        
        if list_history:
            history = rollback_mgr.get_operation_history(limit)
            if not history:
                return ToolResponse(
                    content=[TextBlock(type="text", text="No operation history found.")]
                )
            
            output = [f"📋 Operation History (last {limit}):\n"]
            for op in history:
                status = "✅" if op['success'] else "❌"
                output.append(f"  {status} #{op['id']} [{op['operation_type']}] {op['file_path']}")
                output.append(f"     Time: {op['timestamp']}")
                if op.get('description'):
                    output.append(f"     Description: {op['description']}")
            
            return ToolResponse(
                content=[TextBlock(type="text", text="\n".join(output))]
            )
        
        if operation_id is None:
            return ToolResponse(
                content=[TextBlock(type="text", text="Please provide either operation_id to rollback or list_history=True to view history.")]
            )
        
        result = rollback_mgr.rollback_operation(operation_id)
        if result['success']:
            return ToolResponse(
                content=[TextBlock(type="text", text=f"✅ {result['message']}\n   File: {result.get('file_path', 'N/A')}")]
            )
        else:
            return ToolResponse(
                content=[TextBlock(type="text", text=f"❌ Rollback failed: {result.get('error', 'Unknown error')}")]
            )
            
    except Exception as e:
        return ToolResponse(
            content=[TextBlock(type="text", text=f"Error: {str(e)}")]
        )
