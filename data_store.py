from typing import Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass,field

@dataclass
class User:
    email: str
    username: str
    password: str
    timetable: List[dict] =  field(default_factory=list) 
    tasks: List[dict] = field(default_factory=list) 
@dataclass
class ChatMessage:
    username: str
    content: str
    timestamp: datetime

@dataclass
class VideoUser:
    username: str
    peer_id: str

class DataStore:
    def __init__(self):
        # 用户数据: email -> User
        self.users: Dict[str, User] = {
            "test1@example.com": User(email="test1@example.com", username="张三", password="123456"),
            "test2@example.com": User(email="test2@example.com", username="李四", password="123456"),
            "test3@example.com": User(email="test3@example.com", username="王五", password="123456")
        }
        
        # 聊天消息列表
        self.chat_messages: List[ChatMessage] = [
            ChatMessage(username="张三", content="大家好！", timestamp=datetime.now()),
            ChatMessage(username="李四", content="你好啊！", timestamp=datetime.now()),
            ChatMessage(username="王五", content="今天天气真不错", timestamp=datetime.now())
        ]
        
        # 视频会议用户: username -> VideoUser
        self.video_users: Dict[str, VideoUser] = {
            "张三": VideoUser(username="张三", peer_id="模拟数据"),
            "李四": VideoUser(username="李四", peer_id="模拟数据")
        }

    # 用户相关方法
    def add_user(self, email: str, username: str, password: str) -> bool:
        if email in self.users:
            return False
        self.users[email] = User(email=email, username=username, password=password)
        return True

    def get_user(self, email: str) -> Optional[User]:
        return self.users.get(email)

    def verify_user(self, email: str, password: str) -> Optional[User]:
        user = self.get_user(email)
        if user and user.password == password:
            return user
        return None

    # 聊天消息相关方法
    def add_message(self, username: str, content: str):
        message = ChatMessage(
            username=username,
            content=content,
            timestamp=datetime.now()
        )
        self.chat_messages.append(message)

    def get_messages(self) -> List[ChatMessage]:
        return self.chat_messages

    # 视频会议相关方法
    def add_video_user(self, username: str, peer_id: str):
        print(f"[Debug] 添加视频用户: username={username}, peer_id={peer_id}")
        self.video_users[username] = VideoUser(username=username, peer_id=peer_id)
        print(f"[Debug] 当前在线视频用户: {list(self.video_users.keys())}")

    def remove_video_user(self, username: str):
        print(f"[Debug] 尝试移除视频用户: username={username}")
        if username in self.video_users:
            del self.video_users[username]
            print(f"[Debug] 成功移除用户 {username}")
        else:
            print(f"[Debug] 用户 {username} 不在视频用户列表中")
        print(f"[Debug] 当前在线视频用户: {list(self.video_users.keys())}")

    def get_video_users(self) -> List[VideoUser]:
        users = list(self.video_users.values())
        print(f"[Debug] 获取视频用户列表: {[user.username for user in users]}")
        return users

    def add_timetable(self, email: str, entries: List[dict]):
        if email not in self.users:
            raise KeyError("用户不存在")
        # 清空旧课表后添加新条目
        self.users[email].timetable = [dict(entry) for entry in entries]
        new_entries = []
        for entry in entries:
            new_entry = dict(entry)
            new_entry['last_reminder'] = None  # 添加提醒标记字段
            new_entries.append(new_entry)
        self.users[email].timetable = new_entries
        
    def get_timetable(self, email: str) -> List[dict]:
        user = self.users.get(email)
        if not user:
            raise KeyError("用户不存在")
        return user.timetable.copy()  # 返回副本防止数据被意外修改
    
    
    # ====== 任务管理方法 ======

    def add_task(self, email: str, task: dict):
        if email not in self.users:
            raise KeyError("用户不存在")
        self.users[email].tasks.append(task)

    def get_tasks(self, email: str) -> List[dict]:
        if email not in self.users:
            raise KeyError("用户不存在")
        return self.users[email].tasks.copy()

    def delete_task(self, email: str, index: int):
        if email not in self.users:
            raise KeyError("用户不存在")
        if 0 <= index < len(self.users[email].tasks):
            del self.users[email].tasks[index]

    def edit_task(self, email: str, index: int, updated_task: dict):
        if email not in self.users:
            raise KeyError("用户不存在")
        if 0 <= index < len(self.users[email].tasks):
            self.users[email].tasks[index] = updated_task
# 创建全局数据存储实例
data_store = DataStore()