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
    def get_user(self, email: str):
        """根据邮箱获取用户信息"""
        return self.users.get(email)
    
    def update_user(self, email: str, **kwargs):
        """更新用户信息"""
        user = self.users.get(email)
        if user:
            for key, value in kwargs.items():
                if hasattr(user, key) and value is not None:
                    setattr(user, key, value)
            return True
        return False
    
    def email_exists(self, email: str):
        """检查邮箱是否已存在"""
        return email in self.users
    
    def change_user_email(self, old_email: str, new_email: str):
        """更改用户邮箱（更新字典键）"""
        if old_email in self.users and new_email not in self.users:
            user = self.users.pop(old_email)
            user.email = new_email
            self.users[new_email] = user
            return True
        return False
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

    #课表相关方法
    
    def update_course(self, email: str, course_id: int, updated_course: dict) -> bool:
        """更新指定用户的课程信息"""
        try:
            if email not in self.users:
                return False
                
            user = self.users[email]
            
            # 检查课程ID是否有效
            if course_id < 0 or course_id >= len(user.timetable):
                return False
                
            # 更新课程信息
            user.timetable[course_id].update(updated_course)
            
            return True
            
        except Exception as e:
            print(f"更新课程失败: {str(e)}")
            return False

    def delete_course(self, email: str, course_id: int) -> bool:
        """删除指定用户的课程"""
        try:
            if email not in self.users:
                return False
                
            user = self.users[email]
            
            # 检查课程ID是否有效
            if course_id < 0 or course_id >= len(user.timetable):
                return False
                
            # 删除课程
            del user.timetable[course_id]
            
            return True
            
        except Exception as e:
            print(f"删除课程失败: {str(e)}")
            return False

    def get_course(self, email: str, course_id: int) -> dict:
        """获取指定用户的单个课程信息"""
        try:
            if email not in self.users:
                return None
                
            user = self.users[email]
            
            # 检查课程ID是否有效
            if course_id < 0 or course_id >= len(user.timetable):
                return None
                
            return user.timetable[course_id]
            
        except Exception as e:
            print(f"获取课程失败: {str(e)}")
            return None

    # 修改现有的 get_timetable 方法，为每个课程添加索引ID
    def get_timetable(self, email: str) -> List[dict]:
        """获取指定用户的课表，包含索引ID"""
        if email in self.users:
            timetable_with_id = []
            for index, course in enumerate(self.users[email].timetable):
                course_with_id = course.copy()
                course_with_id['id'] = index  # 添加索引作为ID
                timetable_with_id.append(course_with_id)
            return timetable_with_id
        return []
    
    def add_single_course(self, email: str, course: dict):
        """添加单个课程到用户课表"""
        if email not in self.users:
            raise KeyError("用户不存在")
        
        # 添加提醒标记字段
        course['last_reminder'] = None
        self.users[email].timetable.append(course)
        
# 创建全局数据存储实例
data_store = DataStore()