# FastAPI+Streamlit 架构实现任务分解（无WebSocket）

## 概述

本任务分解旨在指导实现一个完全弃用WebSocket的FastAPI+Streamlit架构方案，用于监控TDMS音频文件、转换格式、处理音频并展示结果。采用HTTP轮询机制替代WebSocket实现实时数据更新，并使用SQLite数据库存储处理结果。

## 实现任务

- [x] 1. **后端API改造**
  - 移除WebSocket相关代码
  - 实现轮询所需的API端点
  - 实现SQLite数据库存储机制

- [x] 2. **数据库模块开发**
  - 创建数据库模型和表结构
  - 实现数据访问层(DAO)
  - 添加数据清理功能

- [x] 3. **文件监控与处理优化**
  - 优化文件监控逻辑
  - 改进TDMS转WAV流程
  - 实现处理完成后自动删除临时WAV文件
  - 完善音频处理回调机制

- [x] 4. **前端轮询机制实现**
  - 移除WebSocket连接代码
  - 实现定时HTTP请求获取数据
  - 更新界面显示逻辑

- [ ] 5. **测试与验证**
  - 测试API端点功能
  - 验证轮询机制有效性
  - 确认TDMS转换准确性
  - 验证数据库存储和查询功能

## 需要创建/修改的文件

- `app/main.py` - 修改主应用文件，移除WebSocket相关代码，添加轮询API端点
- `app/core/background_tasks.py` - 优化任务管理器，调整回调机制
- `streamlit_app.py` - 重新实现前端轮询逻辑，移除WebSocket连接
- `app/core/file_monitor.py` - 优化文件监控逻辑（如有需要）
- `app/core/tdms_converter.py` - 修改TDMS转换功能，添加处理后自动删除临时文件
- `app/core/audio_processor.py` - 保持现有音频处理功能（如无需修改）
- `app/database/database.py` - 新增数据库模块，实现SQLite数据库操作
- `app/database/models.py` - 新增数据库模型定义

## 成功标准

- [x] 后端成功移除WebSocket依赖
- [x] 前端通过HTTP轮询正确获取处理结果
- [x] TDMS文件能正确转换为WAV并处理，处理完成并存储到数据库后自动删除临时文件
- [x] 处理结果正确存储到SQLite数据库中（采用纵表结构）
- [x] 界面能实时显示最新的音频处理结果和历史数据
- [ ] 系统稳定运行，无明显性能问题
- [x] 保持与现有音频处理逻辑的兼容性
- [x] 数据库设计具有良好的扩展性，便于添加新的声学指标