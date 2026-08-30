# ComfyUI 与 Ref2VA 启动和诊断规范

## 一、启动顺序

1. 先检查`http://127.0.0.1:8188/system_stats`。若成功返回，复用现有ComfyUI实例，不要重复启动。
2. 若ComfyUI未运行，使用其虚拟环境中的Python显式启动`G:\ComfyUI\main.py`，不要把该虚拟环境激活后传给后续工具。
3. 循环检查ComfyUI健康接口，确认成功后才启动Ref2VA故事板。
4. Ref2VA使用已安装`fastapi`和`uvicorn`的独立Python解释器显式运行`start.py`。
5. 最后检查`http://127.0.0.1:8765/`，确认故事板服务在线并能连接ComfyUI。

当前推荐解释器：

- ComfyUI：`G:\ComfyUI\.venv\Scripts\python.exe`
- Ref2VA故事板：`E:\Anaconda\python.exe`

## 二、启动脚本原则

- 使用解释器绝对路径，不依赖父窗口中的`PATH`或已激活环境。
- 启动前做健康检查，在线则跳过，避免数据库锁和端口冲突。
- ComfyUI健康检查失败时不要继续启动故事板。
- 等待设定超时后明确报错并退出，不无限等待。
- 启动脚本接收的额外参数只传给ComfyUI，不误传给故事板。

## 三、常见故障

### `ModuleNotFoundError: No module named 'uvicorn'`

原因通常是故事板继承了ComfyUI虚拟环境。先分别执行：

```powershell
& 'G:\ComfyUI\.venv\Scripts\python.exe' -c "import sys; print(sys.executable)"
& 'E:\Anaconda\python.exe' -c "import sys,uvicorn,fastapi; print(sys.executable, uvicorn.__version__)"
```

若第二条成功，让故事板启动脚本显式使用`E:\Anaconda\python.exe`。不要仅在错误环境里反复安装包。

### `Could not acquire lock on database`

先检查8188健康接口和正在运行的ComfyUI进程。若已经在线，关闭新开的失败重复实例并复用原实例；不要通过删除数据库文件解决正常的进程锁。

### 端口被占用但健康检查失败

检查监听8188或8765的进程与命令行，确认是否为预期服务。不要直接终止不明进程；只有确认是本项目遗留实例且用户请求重启时才停止它。

### ComfyUI在线但故事板显示未连接

分别访问8188和8765；检查故事板配置的ComfyUI地址、代理、防火墙和启动日志。不要因网页未刷新就再次启动ComfyUI。

## 四、修改后的验证

在声称修复前至少验证：

- 两个解释器路径真实存在；
- ComfyUI解释器可导入其运行依赖；
- 故事板解释器可导入`uvicorn`和`fastapi`；
- 重复运行启动脚本会识别已在线的ComfyUI并跳过；
- 8188健康接口成功；
- 8765网页成功；
- 启动日志中没有新的数据库锁或模块缺失错误。

验证应使用只读健康检查和导入测试。除非用户明确授权，不提交生成任务、不清空队列、不删除数据库或结果文件。
