"""
记忆管理工具 - AgentScope 格式
"""
import os
from typing import Optional
from agentscope.tool import ToolResponse
from agentscope.message import TextBlock
from tools.agent_memory import AgentMemory


async def agent_memory(
    action: str,
    key: Optional[str] = None,
    value: Optional[str] = None,
    category: str = "general"
) -> ToolResponse:
    """Manage persistent memory across sessions.
    
    Actions:
    - save: Save a key-value pair to memory (persists across sessions)
    - recall: Recall a value by key
    - list: List all saved preferences
    - project_save: Save project-specific context
    - project_recall: Recall project-specific context
    
    Examples:
    - Save: action='save', key='coding_style', value='PEP8 with 120 char lines'
    - Recall: action='recall', key='coding_style'
    - List: action='list'
    
    Args:
        action: Action to perform
        key: Key for save/recall
        value: Value to save
        category: Category (default: 'general')
    
    Returns:
        ToolResponse with result
    """
    try:
        memory = AgentMemory()
        
        if action == "save":
            if not key or value is None:
                return ToolResponse(
                    content=[TextBlock(type="text", text="Error: 'save' requires both 'key' and 'value'")]
                )
            memory.set_preference(key, value)
            return ToolResponse(
                content=[TextBlock(type="text", text=f"✅ Saved: {key} = {value}")]
            )
        
        elif action == "recall":
            if not key:
                return ToolResponse(
                    content=[TextBlock(type="text", text="Error: 'recall' requires 'key'")]
                )
            result = memory.get_preference(key)
            if result is not None:
                return ToolResponse(
                    content=[TextBlock(type="text", text=f"📝 Recalled: {key} = {result}")]
                )
            return ToolResponse(
                content=[TextBlock(type="text", text=f"❌ No memory found for key: {key}")]
            )
        
        elif action == "list":
            prefs = memory.get_all_preferences()
            if not prefs:
                return ToolResponse(
                    content=[TextBlock(type="text", text="📋 No saved preferences")]
                )
            output = ["📋 Saved Preferences:\n"]
            for k, v in prefs.items():
                output.append(f"  • {k} = {v}")
            return ToolResponse(
                content=[TextBlock(type="text", text="\n".join(output))]
            )
        
        elif action == "project_save":
            if not key or value is None:
                return ToolResponse(
                    content=[TextBlock(type="text", text="Error: 'project_save' requires both 'key' and 'value'")]
                )
            memory.set_project_context(os.getcwd(), key, value)
            return ToolResponse(
                content=[TextBlock(type="text", text=f"✅ Saved project context: {key} = {value}")]
            )
        
        elif action == "project_recall":
            if not key:
                # Return full project context
                ctx = memory.get_full_project_context(os.getcwd())
                if not ctx:
                    return ToolResponse(
                        content=[TextBlock(type="text", text="📋 No project context saved for current directory")]
                    )
                output = ["📋 Project Context:\n"]
                for k, v in ctx.items():
                    output.append(f"  • {k} = {v}")
                return ToolResponse(
                    content=[TextBlock(type="text", text="\n".join(output))]
                )
            result = memory.get_project_context(os.getcwd(), key)
            if result is not None:
                return ToolResponse(
                    content=[TextBlock(type="text", text=f"📝 Project context: {key} = {result}")]
                )
            return ToolResponse(
                content=[TextBlock(type="text", text=f"❌ No project context found for key: {key}")]
            )
        
        else:
            return ToolResponse(
                content=[TextBlock(type="text", text=f"Unknown action: {action}. Use: save, recall, list, project_save, project_recall")]
            )
            
    except Exception as e:
        return ToolResponse(
            content=[TextBlock(type="text", text=f"Error: {str(e)}")]
        )
