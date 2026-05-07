"""
测试沙箱执行环境 (tools/sandbox_executor.py)
"""
import os
import pytest
from tools.sandbox_executor import SandboxEnvironment, OperationLogger


class TestSandboxEnvironment:
    """SandboxEnvironment 测试"""
    
    def test_init_default(self):
        """测试默认初始化"""
        sandbox = SandboxEnvironment()
        assert sandbox.work_dir is not None
        assert os.path.exists(sandbox.work_dir)
        assert sandbox.timeout == 30
        sandbox.cleanup()
    
    def test_init_custom_dir(self, temp_dir):
        """测试自定义工作目录"""
        sandbox = SandboxEnvironment(work_dir=temp_dir, timeout=60)
        assert sandbox.work_dir == temp_dir
        assert sandbox.timeout == 60
        sandbox.cleanup()
    
    def test_is_command_safe_allowed(self):
        """测试白名单命令安全检查"""
        sandbox = SandboxEnvironment()
        
        safe_commands = [
            'python3 --version',
            'ls -la',
            'git status',
            'pytest tests/',
            'cat file.txt',
            'echo hello',
        ]
        for cmd in safe_commands:
            is_safe, msg = sandbox.is_command_safe(cmd)
            assert is_safe, f"Command '{cmd}' should be safe: {msg}"
        sandbox.cleanup()
    
    def test_is_command_safe_dangerous(self):
        """测试危险命令检测"""
        sandbox = SandboxEnvironment()
        
        dangerous_commands = [
            'rm -rf /',
            'sudo apt install something',
            'chmod 777 /etc/passwd',
            'mkfs /dev/sda1',
        ]
        for cmd in dangerous_commands:
            is_safe, msg = sandbox.is_command_safe(cmd)
            assert not is_safe, f"Command '{cmd}' should be dangerous"
        sandbox.cleanup()
    
    def test_is_command_safe_unknown(self):
        """测试未知命令"""
        sandbox = SandboxEnvironment()
        is_safe, msg = sandbox.is_command_safe("some_unknown_command")
        assert not is_safe
        assert "白名单" in msg
        sandbox.cleanup()
    
    def test_run_command_simple(self, temp_dir):
        """测试简单命令执行"""
        sandbox = SandboxEnvironment(work_dir=temp_dir)
        result = sandbox.run_command("echo hello")
        assert result["success"] is True
        assert "hello" in result["stdout"]
        sandbox.cleanup()
    
    def test_run_command_dangerous_blocked(self, temp_dir):
        """测试危险命令被阻止"""
        sandbox = SandboxEnvironment(work_dir=temp_dir)
        result = sandbox.run_command("rm -rf /")
        assert result["success"] is False
        assert "危险" in result["error"]
        sandbox.cleanup()
    
    def test_run_command_unknown_blocked(self, temp_dir):
        """测试未知命令被阻止"""
        sandbox = SandboxEnvironment(work_dir=temp_dir)
        result = sandbox.run_command("somecommand args")
        assert result["success"] is False
        assert "白名单" in result["error"]
        sandbox.cleanup()
    
    def test_run_command_timeout(self, temp_dir):
        """测试命令超时"""
        sandbox = SandboxEnvironment(work_dir=temp_dir, timeout=1)
        result = sandbox.run_command("python3 -c \"import time; time.sleep(10)\"")
        assert result["success"] is False
        assert "超时" in result["error"]
        sandbox.cleanup()
    
    def test_safe_file_read(self, temp_dir):
        """测试安全文件读取"""
        sandbox = SandboxEnvironment(work_dir=temp_dir)
        
        # 创建测试文件
        test_file = os.path.join(temp_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("hello world")
        
        result = sandbox.safe_file_read(test_file)
        assert result["success"] is True
        assert result["content"] == "hello world"
        assert result["size"] == 11
        sandbox.cleanup()
    
    def test_safe_file_read_not_found(self, temp_dir):
        """测试读取不存在的文件"""
        sandbox = SandboxEnvironment(work_dir=temp_dir)
        result = sandbox.safe_file_read("/nonexistent/file.txt")
        assert result["success"] is False
        assert "不存在" in result["error"]
        sandbox.cleanup()
    
    def test_safe_file_read_too_large(self, temp_dir):
        """测试读取超大文件"""
        sandbox = SandboxEnvironment(work_dir=temp_dir)
        
        # 创建较大文件
        test_file = os.path.join(temp_dir, "large.txt")
        with open(test_file, "w") as f:
            f.write("x" * 2048)
        
        result = sandbox.safe_file_read(test_file, max_size=1024)
        assert result["success"] is False
        assert "过大" in result["error"]
        sandbox.cleanup()
    
    def test_safe_file_write(self, temp_dir):
        """测试安全文件写入"""
        sandbox = SandboxEnvironment(work_dir=temp_dir)
        
        test_file = os.path.join(temp_dir, "output.txt")
        result = sandbox.safe_file_write(test_file, "test content")
        assert result["success"] is True
        assert os.path.exists(test_file)
        
        with open(test_file, "r") as f:
            assert f.read() == "test content"
        sandbox.cleanup()
    
    def test_safe_file_write_creates_dirs(self, temp_dir):
        """测试写入时自动创建目录"""
        sandbox = SandboxEnvironment(work_dir=temp_dir)
        
        test_file = os.path.join(temp_dir, "sub", "dir", "output.txt")
        result = sandbox.safe_file_write(test_file, "nested content")
        assert result["success"] is True
        assert os.path.exists(test_file)
        sandbox.cleanup()
    
    def test_context_manager(self, temp_dir):
        """测试上下文管理器"""
        with SandboxEnvironment(work_dir=temp_dir) as sandbox:
            assert sandbox is not None
            result = sandbox.run_command("echo test")
            assert result["success"] is True
    
    def test_cleanup(self):
        """测试清理功能"""
        sandbox = SandboxEnvironment()
        work_dir = sandbox.work_dir
        assert os.path.exists(work_dir)
        sandbox.cleanup()
        # 默认创建的临时目录应被清理
        assert not os.path.exists(work_dir)


class TestOperationLogger:
    """OperationLogger 测试"""
    
    def test_init(self, temp_dir):
        """测试初始化"""
        log_file = os.path.join(temp_dir, "test.log")
        logger = OperationLogger(log_file=log_file)
        assert logger.log_file == log_file
    
    def test_log_success(self, temp_dir):
        """测试成功日志记录"""
        log_file = os.path.join(temp_dir, "test.log")
        logger = OperationLogger(log_file=log_file)
        
        logger.log("test_op", {"key": "value"}, success=True)
        
        assert os.path.exists(log_file)
        with open(log_file, "r") as f:
            content = f.read()
        assert "test_op" in content
        assert '"success": true' in content
    
    def test_log_failure(self, temp_dir):
        """测试失败日志记录"""
        log_file = os.path.join(temp_dir, "test.log")
        logger = OperationLogger(log_file=log_file)
        
        logger.log("failed_op", {"error": "something"}, success=False)
        
        with open(log_file, "r") as f:
            content = f.read()
        assert "failed_op" in content
        assert '"success": false' in content
    
    def test_log_multiple_entries(self, temp_dir):
        """测试多条日志"""
        log_file = os.path.join(temp_dir, "test.log")
        logger = OperationLogger(log_file=log_file)
        
        logger.log("op1", {"a": 1})
        logger.log("op2", {"b": 2})
        logger.log("op3", {"c": 3})
        
        with open(log_file, "r") as f:
            lines = f.readlines()
        assert len(lines) == 3
