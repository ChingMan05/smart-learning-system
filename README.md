# 项目运行说明

## 环境要求
- Python 3.8+
- FastAPI
- uvicorn
- 现代浏览器（支持WebRTC）

## 安装依赖
```bash
pip install fastapi uvicorn
pip install pytz
```

## 运行项目
1. 启动后端服务器
```bash
python server.py
```

2. 打开前端页面
- 直接在浏览器中打开 index.html 文件
- 或使用 Visual Studio Code 的 Live Server 插件运行

## 使用说明
1. 使用测试账号登录（见下方测试账号列表）或注册新账号
2. 登录后可以使用在线聊天、视频会议等功能
3. 视频会议功能需要允许浏览器访问摄像头和麦克风


# API 文档

## 用户认证接口

### 1. 用户登录
- **URL**: `/api/login`
- **方法**: POST
- **请求体**:
```json
{
    "email": "test1@example.com",
    "password": "123456"
}
```
- **成功响应** (200):
```json
{
    "user": {
        "username": "张三",
        "email": "test1@example.com"
    }
}
```
- **失败响应** (401):
```json
{
    "detail": "邮箱或密码错误"
}
```

### 2. 用户注册
- **URL**: `/api/register`
- **方法**: POST
- **请求体**:
```json
{
    "username": "张三",
    "email": "zhangsan@example.com",
    "password": "123456"
}
```
- **成功响应** (200):
```json
{
    "message": "注册成功"
}
```
- **失败响应** (400):
```json
{
    "detail": "邮箱已被注册"
}
```

## WebSocket 聊天接口

### 1. 聊天连接
- **URL**: `ws://localhost:8082/ws/chat/?user_email=${currentUser.email}`
- **协议**: WebSocket

### 2. 发送消息格式
```json
{
    "username": "张三",
    "content": "消息内容"
}
```

### 3. 接收消息格式
```json
{
    "username": "张三",
    "content": "消息内容",
    "time": "14:30",
    "avatar": "https://via.placeholder.com/30",
    "isSelf": false
}
```

## 测试账号
系统预置了以下测试账号：
1. 邮箱: test1@example.com 密码: 123456 用户名: 张三
2. 邮箱: test2@example.com 密码: 123456 用户名: 李四
3. 邮箱: test3@example.com 密码: 123456 用户名: 王五

## 注意事项
1. 所有 HTTP 请求头的 Content-Type 应设置为 `application/json`
2. WebSocket 连接建立后会自动接收其他用户的消息
3. 用户需要先登录才能发送消息
4. 服务器运行在 localhost:8082 端口