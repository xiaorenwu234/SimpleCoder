"""
测试增强版代码编辑工具 (tools/safe_code_edit.py)
"""
import os
import pytest
from tools.safe_code_edit import SafeCodeEditTool


class TestSafeCodeEditTool:
    """SafeCodeEditTool 测试"""
    
    def test_tool_name(self):
        """测试工具名称"""
        tool = SafeCodeEditTool()
        assert tool.name == "safe_code_edit"
    
    def test_replace_operation(self, temp_dir):
        """测试替换操作"""
        tool = SafeCodeEditTool()
        
        test_file = os.path.join(temp_dir, "edit_test.py")
        with open(test_file, "w") as f:
            f.write("line1\nline2\nline3\nline4\nline5\n")
        
        result = tool._run(
            file_path=test_file,
            operation="replace",
            start_line=2,
            end_line=3,
            new_content="replaced_line",
            description="replace test"
        )
        
        assert "✅" in result
        
        with open(test_file, "r") as f:
            content = f.read()
        assert "replaced_line" in content
        assert "line1" in content
        assert "line4" in content
    
    def test_insert_operation(self, temp_dir):
        """测试插入操作"""
        tool = SafeCodeEditTool()
        
        test_file = os.path.join(temp_dir, "insert_test.py")
        with open(test_file, "w") as f:
            f.write("line1\nline2\nline3\n")
        
        result = tool._run(
            file_path=test_file,
            operation="insert",
            start_line=1,
            new_content="inserted_line",
            description="insert test"
        )
        
        assert "✅" in result
        
        with open(test_file, "r") as f:
            lines = f.readlines()
        assert "inserted_line" in lines[1]
    
    def test_delete_operation(self, temp_dir):
        """测试删除操作"""
        tool = SafeCodeEditTool()
        
        test_file = os.path.join(temp_dir, "delete_test.py")
        with open(test_file, "w") as f:
            f.write("line1\nline2\nline3\nline4\n")
        
        result = tool._run(
            file_path=test_file,
            operation="delete",
            start_line=2,
            end_line=3,
            description="delete test"
        )
        
        assert "✅" in result
        
        with open(test_file, "r") as f:
            content = f.read()
        assert "line2" not in content
        assert "line3" not in content
        assert "line1" in content
        assert "line4" in content
    
    def test_file_not_found(self, temp_dir):
        """测试编辑不存在的文件"""
        tool = SafeCodeEditTool()
        
        result = tool._run(
            file_path=os.path.join(temp_dir, "nonexistent.py"),
            operation="replace",
            start_line=1,
            end_line=1,
            new_content="test"
        )
        
        assert "Error" in result
    
    def test_invalid_line_range(self, temp_dir):
        """测试无效行号"""
        tool = SafeCodeEditTool()
        
        test_file = os.path.join(temp_dir, "range_test.py")
        with open(test_file, "w") as f:
            f.write("only one line\n")
        
        result = tool._run(
            file_path=test_file,
            operation="replace",
            start_line=10,
            end_line=20,
            new_content="test"
        )
        
        assert "Error" in result or "out of range" in result
    
    def test_replace_without_end_line(self, temp_dir):
        """测试替换操作缺少 end_line"""
        tool = SafeCodeEditTool()
        
        test_file = os.path.join(temp_dir, "no_end.py")
        with open(test_file, "w") as f:
            f.write("content\n")
        
        result = tool._run(
            file_path=test_file,
            operation="replace",
            start_line=1,
            new_content="test"
        )
        
        assert "Error" in result or "requires end_line" in result
    
    def test_unknown_operation(self, temp_dir):
        """测试未知操作"""
        tool = SafeCodeEditTool()
        
        test_file = os.path.join(temp_dir, "unknown_op.py")
        with open(test_file, "w") as f:
            f.write("content\n")
        
        result = tool._run(
            file_path=test_file,
            operation="invalid_op",
            start_line=1,
            new_content="test"
        )
        
        assert "Unknown operation" in result
    
    def test_backup_created(self, temp_dir):
        """测试备份文件创建"""
        tool = SafeCodeEditTool()
        
        test_file = os.path.join(temp_dir, "backup_test.py")
        with open(test_file, "w") as f:
            f.write("original content\n")
        
        result = tool._run(
            file_path=test_file,
            operation="replace",
            start_line=1,
            end_line=1,
            new_content="new content",
            description="backup test"
        )
        
        assert "Backup" in result
    
    def test_relative_path(self, temp_dir, monkeypatch):
        """测试相对路径"""
        tool = SafeCodeEditTool()
        
        monkeypatch.chdir(temp_dir)
        
        test_file = "relative_test.py"
        with open(test_file, "w") as f:
            f.write("content\nline2\n")
        
        result = tool._run(
            file_path=test_file,
            operation="replace",
            start_line=1,
            end_line=1,
            new_content="new content"
        )
        
        assert "✅" in result
