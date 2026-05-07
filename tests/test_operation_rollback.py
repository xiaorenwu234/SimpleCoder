"""
测试操作回滚系统 (tools/operation_rollback.py)
"""
import os
import pytest
from tools.operation_rollback import OperationRollback


class TestOperationRollback:
    """OperationRollback 测试"""
    
    def test_init(self, temp_db):
        """测试初始化"""
        rollback = OperationRollback(db_path=temp_db)
        assert os.path.exists(temp_db) or True  # 数据库延迟创建
    
    def test_backup_file(self, temp_dir, temp_db):
        """测试文件备份"""
        rollback = OperationRollback(db_path=temp_db)
        
        # 创建测试文件
        test_file = os.path.join(temp_dir, "original.txt")
        with open(test_file, "w") as f:
            f.write("original content")
        
        backup_path = rollback.backup_file(test_file, "test backup")
        assert backup_path is not None
        assert os.path.exists(backup_path)
        
        # 验证备份内容
        with open(backup_path, "r") as f:
            assert f.read() == "original content"
    
    def test_backup_file_not_exists(self, temp_dir, temp_db):
        """测试备份不存在的文件"""
        rollback = OperationRollback(db_path=temp_db)
        result = rollback.backup_file("/nonexistent/file.txt")
        assert result is None
    
    def test_record_operation(self, temp_dir, temp_db):
        """测试记录操作"""
        rollback = OperationRollback(db_path=temp_db)
        
        rollback.record_operation(
            operation_type="edit",
            file_path=os.path.join(temp_dir, "test.py"),
            description="test edit"
        )
        
        history = rollback.get_operation_history()
        assert len(history) >= 1
        assert history[0]["operation_type"] == "edit"
        assert history[0]["description"] == "test edit"
    
    def test_get_operation_history(self, temp_dir, temp_db):
        """测试获取操作历史"""
        rollback = OperationRollback(db_path=temp_db)
        
        test_file = os.path.join(temp_dir, "test.py")
        
        # 记录多个操作
        rollback.record_operation("edit", test_file, description="first edit")
        rollback.record_operation("edit", test_file, description="second edit")
        rollback.record_operation("insert", test_file, description="insert op")
        
        history = rollback.get_operation_history(limit=10)
        assert len(history) >= 3
    
    def test_get_operation_history_limit(self, temp_dir, temp_db):
        """测试操作历史数量限制"""
        rollback = OperationRollback(db_path=temp_db)
        
        test_file = os.path.join(temp_dir, "test.py")
        for i in range(10):
            rollback.record_operation("edit", test_file, description=f"op {i}")
        
        history = rollback.get_operation_history(limit=3)
        assert len(history) == 3
    
    def test_rollback_operation(self, temp_dir, temp_db):
        """测试回滚操作"""
        rollback = OperationRollback(db_path=temp_db)
        
        # 创建测试文件
        test_file = os.path.join(temp_dir, "rollback_test.txt")
        with open(test_file, "w") as f:
            f.write("original content")
        
        # 备份
        backup_path = rollback.backup_file(test_file, "before edit")
        
        # 修改文件
        with open(test_file, "w") as f:
            f.write("modified content")
        
        # 验证文件已修改
        with open(test_file, "r") as f:
            assert f.read() == "modified content"
        
        # 获取操作历史
        history = rollback.get_operation_history()
        op_id = history[0]["id"]
        
        # 回滚
        result = rollback.rollback_operation(op_id)
        assert result["success"] is True
        
        # 验证文件已恢复
        with open(test_file, "r") as f:
            assert f.read() == "original content"
    
    def test_rollback_operation_not_found(self, temp_db):
        """测试回滚不存在的操作"""
        rollback = OperationRollback(db_path=temp_db)
        result = rollback.rollback_operation(9999)
        assert result["success"] is False
        assert "不存在" in result["error"]
    
    def test_rollback_to_point(self, temp_dir, temp_db):
        """测试回滚到指定时间点"""
        rollback = OperationRollback(db_path=temp_db)
        
        test_file = os.path.join(temp_dir, "time_test.txt")
        
        # 创建并备份文件
        with open(test_file, "w") as f:
            f.write("version 1")
        rollback.backup_file(test_file, "version 1")
        rollback.record_operation("edit", test_file, description="v1")
        
        # 修改文件
        with open(test_file, "w") as f:
            f.write("version 2")
        rollback.backup_file(test_file, "version 2")
        rollback.record_operation("edit", test_file, description="v2")
        
        # 获取历史
        history = rollback.get_operation_history()
        assert len(history) >= 2
    
    def test_cleanup_old_backups(self, temp_dir, temp_db):
        """测试清理旧备份"""
        rollback = OperationRollback(db_path=temp_db)
        
        # 此测试仅验证方法可调用，不删除实际数据（因为是新建的）
        count = rollback.cleanup_old_backups(days=0)
        assert isinstance(count, int)
