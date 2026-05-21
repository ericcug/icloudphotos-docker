# Plugin Interface Contract

**Version**: 1.0.0
**Spec**: FR-014, FR-016a

## BaseProcessor Abstract Class

```python
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any


class BaseProcessor(ABC):
    """后置处理插件抽象基类。
    
    所有后置处理插件 MUST 继承此类并实现全部抽象方法。
    插件在流水线中被顺序调用，每个步骤对文件进行原地处理或生成新版本。
    """

    version: str = "1.0.0"
    """插件版本标识，用于兼容性检查。"""

    @abstractmethod
    def init(self, config: Dict[str, Any]) -> None:
        """初始化处理器。
        
        在流水线启动时调用一次。可用于加载模型、验证配置、建立连接等。
        
        Args:
            config: 用户在配置文件中为该处理器指定的参数。
        
        Raises:
            ValueError: 配置参数无效时抛出。
        """
        ...

    @abstractmethod
    def process(self, file_path: Path, metadata: Dict[str, Any]) -> Path:
        """处理单个媒体文件。
        
        每次文件下载完成后被调用。处理器可原地修改文件或生成新文件。
        返回的路径将传递给下一个处理器。
        
        Args:
            file_path: 待处理文件的绝对路径。
            metadata: 文件元数据，包含：
                - record_name: iCloud 唯一标识
                - filename: 原始文件名
                - media_type: "photo" | "video" | "live_photo"
                - size_bytes: 文件大小
                - created_at: 创建时间 (ISO 8601)
                - modified_at: 修改时间 (ISO 8601)
        
        Returns:
            处理后的文件路径（可能与输入相同）。
        
        Raises:
            ProcessorError: 处理失败时抛出，流水线将根据重试策略处理。
        """
        ...

    @abstractmethod
    def cleanup(self) -> None:
        """清理资源。
        
        在流水线停止时调用一次。用于释放连接、清理临时文件等。
        此方法 SHOULD NOT 抛出异常（异常会被捕获并记录日志）。
        """
        ...


class ProcessorError(Exception):
    """插件处理异常。"""
    pass
```

## 插件发现机制

1. 内置插件：`src/icloud_docker/pipeline/builtin/` 下的模块自动注册
2. 用户插件：配置中指定 Python 模块路径 (如 `my_plugins.watermark`)，系统动态 `importlib` 加载
3. 插件注册表：`BaseProcessor.__subclasses__()` 遍历发现所有已加载子类

## 示例内置插件：HEIC 转 JPG

```python
class HeicToJpgProcessor(BaseProcessor):
    version = "1.0.0"
    
    def init(self, config):
        self.quality = config.get("quality", 85)
        self.remove_original = config.get("remove_original", False)
    
    def process(self, file_path, metadata):
        if file_path.suffix.lower() != ".heic":
            return file_path  # 非 HEIC 文件，直接透传
        jpg_path = file_path.with_suffix(".jpg")
        # 调用 pillow/pyheif 转换...
        return jpg_path
    
    def cleanup(self):
        pass
```
