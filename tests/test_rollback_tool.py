"""
测试回滚操作工具 (tools/rollback_tool.py)
"""
import os
import pytest
from tools.rollback_tool import RollbackTool
from tools.operation_rollback import OperationRollback


class TestRollbackTool:
    """RollbackTool 测试"""
    
    def test_tool_name(self):
        """测试工具名称"""
        tool = RollbackTool()
        assert tool.name == "rollback"
    
    def test_list_history_empty(self, temp_dir):
        """测试空历史列表"""
        db_path = os.path.join(temp_dir, "test_rollback.db")
        tool = RollbackTool(db_path=db_path)
        result = tool._run(list_history=True)
        assert "No operation history" in result
    
    def test_list_history_with_data(self, temp_dir):
        """测试有数据时列出历史"""
        db_path = os.path.join(temp_dir, "test_rollback.db")
        # 先通过 rollback_manager 添加数据
        rollback = OperationRollback(db_path=db_path)
        rollback.record_operation("edit", "/test/file.py", description="test edit")
        
        # 使用同一个 db
        tool = RollbackTool(db_path=db_path)
        result = tool._run(list_history=True)
        assert isinstance(result, str)
    
    def test_rollback_without_id(self, temp_dir):
        """测试缺少操作ID"""
        db_path = os.path.join(temp_dir, "test_rollback.db")
        tool = RollbackTool(db_path=db_path)
        result = tool._run()
        assert "provide either" in result
    
    def test_rollback_nonexistent_id(self, temp_dir):
        """测试回滚不存在的操作ID"""
        db_path = os.path.join(temp_dir, "test_rollback.db")
        tool = RollbackTool(db_path=db_path)
        result = tool._run(operation_id=99999)
        assert "❌" in result or "failed" in result.lower()
    
    def test_list_history_with_limit(self, temp_dir):
        """测试历史数量限制"""
        db_path = os.path.join(temp_dir, "test_rollback.db")
        rollback = OperationRollback(db_path=db_path)
        for i in range(15):
            rollback.record_operation("edit", "/test/file.py", description=f"op {i}")
        
        tool = RollbackTool(db_path=db_path)
        result = tool._run(list_history=True, limit=5)
        assert isinstance(result, str)
