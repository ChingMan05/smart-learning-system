from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException ,UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from typing import List
from datetime import datetime, timedelta
from pytz import timezone
import json
from data_store import data_store, User
from pydantic import BaseModel,field_validator
import csv
from io import StringIO
from apscheduler.schedulers.background import BackgroundScheduler
import smtplib
from email.mime.text import MIMEText
from pydantic import BaseModel, EmailStr, field_validator
import re

# 定义请求模型
class UserLogin(BaseModel):
    email: str
    password: str

class UserRegister(BaseModel):
    username: str
    email: str
    password: str

app = FastAPI()

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 存储WebSocket连接
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.user_connections: dict = {}  # 存储用户邮箱和对应的websocket连接

    async def connect(self, websocket: WebSocket, user_email: str):
        await websocket.accept()
        # 如果用户已经有连接，先断开旧连接
        if user_email in self.user_connections:
            old_websocket = self.user_connections[user_email]
            await old_websocket.close()
            self.active_connections.remove(old_websocket)
        
        self.active_connections.append(websocket)
        self.user_connections[user_email] = websocket

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        # 清理用户连接记录
        for email, ws in list(self.user_connections.items()):
            if ws == websocket:
                del self.user_connections[email]
                break

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()


# 登录接口
@app.post("/api/login")
async def login(login_data: UserLogin):
    user = data_store.verify_user(login_data.email, login_data.password)
    if user:
        return {
            "user": {
                "username": user.username,
                "email": user.email
            }
        }
    raise HTTPException(status_code=401, detail="邮箱或密码错误")

# 注册接口
@app.post("/api/register")
async def register(user_data: UserRegister):
    success = data_store.add_user(
        email=user_data.email,
        username=user_data.username,
        password=user_data.password
    )
    if success:
        return {"message": "注册成功"}
    raise HTTPException(status_code=400, detail="邮箱已被注册")
# 用户更新信息模型
class UserUpdate(BaseModel):
    email: str  
    new_username: str = None
    new_email: str = None  
    new_password: str = None
    
    @field_validator('new_email')
    @classmethod
    def validate_email(cls, v):
        # 修复：只在有值时验证
        if v is not None and v.strip():
            if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', v.strip()):
                raise ValueError('邮箱格式不正确')
            return v.strip()
        return v
    
    @field_validator('new_username')
    @classmethod
    def validate_username(cls, v):
        # 修复：只在有值时验证，并且允许更灵活的格式
        if v is not None and v.strip():
            username = v.strip()
            if not username:
                raise ValueError('用户名不能为空')
            if len(username) > 20:
                raise ValueError('用户名不能超过20个字符')
            # 修改正则表达式，允许更多字符
            if not re.match(r'^[\u4e00-\u9fa5a-zA-Z0-9_\-\s]+$', username):
                raise ValueError('用户名包含非法字符')
            return username
        return v
    
    @field_validator('new_password')
    @classmethod
    def validate_password(cls, v):
        # 修复：只在有值时验证
        if v is not None and v.strip():
            if len(v.strip()) < 6:
                raise ValueError('密码长度至少6位')
            if len(v.strip()) > 50:
                raise ValueError('密码长度不能超过50位')
            return v.strip()
        return v

# 获取用户信息接口
@app.get("/api/user/profile")
async def get_user_profile(email: str):
    """获取用户个人信息"""
    try:
        user = data_store.get_user(email)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        
        # 返回用户信息（不包含密码）
        return {
            "user": {
                "username": user.username,
                "email": user.email
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/api/user/profile")
async def update_user_profile(user_update: UserUpdate):
    """更新用户个人信息"""
    try:
        # 验证原用户是否存在
        user = data_store.get_user(user_update.email)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        
        # 检查是否有任何实际更新
        has_updates = False
        updated_fields = {}
        
        # 更新用户名
        if user_update.new_username is not None and user_update.new_username.strip():
            new_username = user_update.new_username.strip()
            if new_username != user.username:
                user.username = new_username
                updated_fields['username'] = new_username
                has_updates = True
        
        # 更新邮箱
        if user_update.new_email is not None and user_update.new_email.strip():
            new_email = user_update.new_email.strip()
            if new_email != user_update.email:
                # 检查新邮箱是否已被使用
                if data_store.get_user(new_email):
                    raise HTTPException(status_code=400, detail="新邮箱已被其他用户使用")
                
                # 更新邮箱（需要特殊处理，因为邮箱是主键）
                old_email = user_update.email
                user.email = new_email
                # 在数据存储中更新邮箱键
                data_store.users[new_email] = data_store.users.pop(old_email)
                updated_fields['email'] = new_email
                has_updates = True
        
        # 更新密码
        if user_update.new_password is not None and user_update.new_password.strip():
            user.password = user_update.new_password.strip()  # 实际项目中应该加密
            updated_fields['password'] = '已更新'
            has_updates = True
        
        if not has_updates:
            raise HTTPException(status_code=400, detail="没有检测到任何更改")
        
        return {
            "message": "用户信息更新成功",
            "updated_fields": updated_fields,
            "user": {
                "username": user.username,
                "email": user.email
            }
        }
        
    except HTTPException:
        raise
    except ValueError as e:
        # Pydantic 验证错误
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
# 验证密码接口（用于敏感操作前的密码确认）
@app.post("/api/user/verify-password")
async def verify_password(email: str = Form(...), password: str = Form(...)):
    """验证用户密码"""
    try:
        user = data_store.verify_user(email, password)
        if user:
            return {"message": "密码验证成功"}
        else:
            raise HTTPException(status_code=401, detail="密码错误")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
# WebSocket连接处理
@app.websocket("/ws/chat/")
async def websocket_endpoint(websocket: WebSocket):
    try:
        # 获取连接信息
        params = websocket.query_params
        user_email = params.get("user_email", "anonymous")
        
        await manager.connect(websocket, user_email)
        
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)
            
            # 获取用户信息并存储消息
            username = message_data.get("username", "匿名用户")
            content = message_data.get("content", "")
            data_store.add_message(username, content)
            
            # 构造返回消息
            response = {
                "username": username,
                "content": content,
                "time": datetime.now().strftime("%H:%M"),
                "avatar": "https://via.placeholder.com/30",
                "isSelf": False
            }
            
            await manager.broadcast(json.dumps(response))
            
    except WebSocketDisconnect:
        manager.disconnect(websocket)

        
# 添加视频用户接口
@app.post("/api/video/register")
async def register_video_user(data: dict):
    data_store.add_video_user(data["username"], data["peer_id"])
    return {"message": "success"}

# 获取在线视频用户接口
@app.get("/api/video/users")
async def get_video_users():
    users = data_store.get_video_users()
    return {"users": [{"username": user.username, "peer_id": user.peer_id} for user in users]}

# 用户退出视频接口
@app.post("/api/video/unregister")
async def unregister_video_user(data: dict):
    data_store.remove_video_user(data["username"])
    return {"message": "success"}

# 课表数据模型
class TimetableEntry(BaseModel):
    course_name: str
    day_of_week: str
    start_time: str
    end_time: str
    location: str

@app.post("/api/timetable/upload")
async def upload_timetable(
    file: UploadFile = File(...),
    email: str = Form(...)
):
    try:
        # 验证文件类型
        if not file.filename.endswith(".csv"):
            raise HTTPException(status_code=400, detail="仅支持CSV文件")

        # 读取并解析CSV
        contents = await file.read()
        csv_data = StringIO(contents.decode('utf-8-sig'))  # 处理BOM
        reader = csv.DictReader(csv_data)
        
        # 验证必要列
        required_columns = ["Course Name", "Day", "Start Time", "End Time", "Location"]
        if not all(col in reader.fieldnames for col in required_columns):
            missing = [col for col in required_columns if col not in reader.fieldnames]
            raise HTTPException(
                status_code=400,
                detail=f"CSV文件缺少必要列: {', '.join(missing)}"
            )

        # 转换为标准格式
        entries = []
        for row in reader:
            entries.append({
                "course_name": row["Course Name"].strip(),
                "day_of_week": row["Day"].strip(),
                "start_time": row["Start Time"].strip(),
                "end_time": row["End Time"].strip(),
                "location": row["Location"].strip()
            })

        # 存储数据
        data_store.add_timetable(email, entries)
        return {"message": "课表上传成功", "entries_count": len(entries)}

    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="文件编码错误，请使用UTF-8编码")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/timetable")
async def get_timetable(email: str):
    try:
        timetable = data_store.get_timetable(email)
        if not timetable:
            raise HTTPException(status_code=404, detail="未找到课表数据")
        return {"timetable": timetable}
    except KeyError:
        raise HTTPException(status_code=404, detail="用户不存在")


# 邮件配置（需替换为实际值）
SMTP_CONFIG = {
    "host": "smtp.qq.com",
    "port": 465,
    "user": "859766083@qq.com",
    "password": "jkpqfkttzglsbbgd"
}

def check_reminders():
    """ 每分钟执行一次的提醒检查 """
    tz = timezone('Asia/Shanghai')  # 设定时区为上海时间
    now = datetime.now(tz)  # 当前时间带时区
    weekday_map = {"周一":0, "周二":1, "周三":2, "周四":3, "周五":4, "周六":5, "周日":6}
    
    for user in data_store.users.values():
        for entry in user.timetable:
            # 检查星期匹配
            if weekday_map.get(entry['day_of_week'].strip(), -1) != now.weekday():
                continue
            
            # 解析课程时间
            try:
                course_time = datetime.strptime(entry['start_time'], "%H:%M").time()
                course_dt = datetime.combine(now.date(), course_time).replace(tzinfo=tz)  # 将 course_dt 转换为带时区的时间
            except ValueError:
                continue
            
            # 计算时间差
            delta = (course_dt - now).total_seconds()
            if 0 < delta <= 600:  # 10分钟内
                if entry['last_reminder'] != now.date().isoformat():
                    send_reminder(user.email, entry)#测试时发给自己
                    entry['last_reminder'] = now.date().isoformat()

def send_reminder(to_email:str, course: dict):
    """ 发送邮件提醒 """
    msg = MIMEText(
        f"您将在10分钟后有课程：{course['course_name']}\n"
        f"时间：{course['start_time']} 地点：{course['location']}",
        'plain', 'utf-8'
    )
    msg['Subject'] = "课程提醒"
    msg['From'] ="859766083@qq.com" 
    msg['To'] = to_email
    
    try:
        with smtplib.SMTP_SSL(SMTP_CONFIG['host'], SMTP_CONFIG['port']) as server:
            
            server.login(SMTP_CONFIG['user'], SMTP_CONFIG['password'])
            server.send_message(msg)
        print(f"已发送提醒至 {to_email}")
    except Exception as e:
        print(f"邮件发送失败：{str(e)}")

# 初始化定时器
scheduler = BackgroundScheduler()
scheduler.add_job(check_reminders, 'interval', minutes=1)

@app.on_event("startup")
async def startup():
    print("定时任务启动")
    scheduler.start()


# 任务模型
class Task(BaseModel):
    title: str
    description: str
    due_date: str  # 可选: datetime 类型更严格
    @field_validator('due_date')
    @classmethod
    def validate_date(cls, v):
        try:
            datetime.strptime(v, '%Y-%m-%d')
            return v
        except ValueError:
            raise ValueError('截止日期必须为 YYYY-MM-DD 格式')
@app.post("/api/tasks/add")
async def add_task(
    email: str = Form(...),
    title: str = Form(...),
    description: str = Form(...),
    due_date: str = Form(...)
):
    print(f"收到请求: email={email}, title={title}, description={description}, due_date={due_date}")
    if not all([title.strip(), description.strip(), due_date.strip()]):
        raise HTTPException(status_code=400, detail="任务信息不能为空")
    
    try:
        datetime.strptime(due_date, '%Y-%m-%d')
    except ValueError:
        raise HTTPException(status_code=422, detail="截止日期必须为 YYYY-MM-DD 格式")

    task = Task(title=title, description=description, due_date=due_date)
    data_store.add_task(email, task.dict())
    return {"message": "任务添加成功"}

# 获取任务接口
@app.get("/api/tasks")
async def get_tasks(email: str):
    tasks = data_store.get_tasks(email)
    return {"tasks": tasks}

# 删除任务接口
@app.post("/api/tasks/delete")
async def delete_task(email: str = Form(...), task_index: int = Form(...)):
    try:
        data_store.delete_task(email, task_index)
        return {"message": "任务删除成功"}
    except KeyError:
        raise HTTPException(status_code=404, detail="用户不存在")
    except IndexError:
        raise HTTPException(status_code=404, detail="任务不存在")

# 编辑任务接口
@app.post("/api/tasks/edit")
async def edit_task(email: str = Form(...), task_index: int = Form(...), title: str = Form(...), description: str = Form(...), due_date: str = Form(...)):
    print(f"收到编辑任务请求: email={email}, task_index={task_index}, title={title}, description={description}, due_date={due_date}")
    try:
        if not all([title.strip(), description.strip(), due_date.strip()]):
            raise HTTPException(status_code=400, detail="任务信息不能为空")
        
        try:
            datetime.strptime(due_date, '%Y-%m-%d')
        except ValueError:
            raise HTTPException(status_code=422, detail="截止日期必须为 YYYY-MM-DD 格式")

        updated_task = {
            "title": title,
            "description": description,
            "due_date": due_date
        }
        data_store.edit_task(email, task_index, updated_task)
        print(f"任务编辑成功: email={email}, task_index={task_index}")
        return {"message": "任务编辑成功"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except KeyError:
        raise HTTPException(status_code=404, detail="用户不存在")
    except IndexError:
        raise HTTPException(status_code=404, detail="任务索引无效")
    
# 课程更新请求模型
class CourseUpdate(BaseModel):
    email: str
    course_name: str
    day_of_week: str
    start_time: str
    end_time: str
    location: str

# 更新课程接口
@app.put("/api/timetable/{course_id}")
async def update_course(course_id: int, course_data: CourseUpdate):
    try:
        # 验证时间格式
        try:
            start = datetime.strptime(course_data.start_time, "%H:%M").time()
            end = datetime.strptime(course_data.end_time, "%H:%M").time()
            if start >= end:
                raise HTTPException(status_code=400, detail="结束时间必须晚于开始时间")
        except ValueError:
            raise HTTPException(status_code=400, detail="时间格式错误，请使用 HH:MM 格式")
        
        # 验证星期格式
        valid_days = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        if course_data.day_of_week not in valid_days:
            raise HTTPException(status_code=400, detail="星期格式错误")
            
        # 构造更新的课程数据
        updated_course = {
            "course_name": course_data.course_name.strip(),
            "day_of_week": course_data.day_of_week.strip(),
            "start_time": course_data.start_time.strip(),
            "end_time": course_data.end_time.strip(),
            "location": course_data.location.strip()
        }
        
        # 调用数据存储层更新课程
        success = data_store.update_course(course_data.email, course_id, updated_course)
        if success:
            return {"message": "课程更新成功"}
        else:
            raise HTTPException(status_code=404, detail="课程不存在或更新失败")
            
    except KeyError:
        raise HTTPException(status_code=404, detail="用户不存在")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 删除课程接口
@app.delete("/api/timetable/{course_id}")
async def delete_course(
    course_id: int,
    email: str
):
    try:
        # 调用数据存储层删除课程
        success = data_store.delete_course(email, course_id)
        if success:
            return {"message": "课程删除成功"}
        else:
            raise HTTPException(status_code=404, detail="课程不存在或删除失败")
            
    except KeyError:
        raise HTTPException(status_code=404, detail="用户不存在")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 获取单个课程接口（可选，用于验证）
@app.get("/api/timetable/{course_id}")
async def get_course(course_id: int, email: str):
    try:
        course = data_store.get_course(email, course_id)
        if course:
            return {"course": course}
        else:
            raise HTTPException(status_code=404, detail="课程不存在")
    except KeyError:
        raise HTTPException(status_code=404, detail="用户不存在")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

 # 新增：单个课程添加模型
class CourseAdd(BaseModel):
    email: str
    course_name: str
    day_of_week: str
    start_time: str
    end_time: str
    location: str

# 新增：添加单个课程接口
@app.post("/api/timetable/add")
async def add_single_course(course_data: CourseAdd):
    try:
        # 验证时间格式
        try:
            start = datetime.strptime(course_data.start_time, "%H:%M").time()
            end = datetime.strptime(course_data.end_time, "%H:%M").time()
            if start >= end:
                raise HTTPException(status_code=400, detail="结束时间必须晚于开始时间")
        except ValueError:
            raise HTTPException(status_code=400, detail="时间格式错误，请使用 HH:MM 格式")
        
        # 验证星期格式
        valid_days = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        if course_data.day_of_week not in valid_days:
            raise HTTPException(status_code=400, detail="星期格式错误")
        
        # 验证用户是否存在
        user = data_store.get_user(course_data.email)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        
        # 构造课程数据
        new_course = {
            "course_name": course_data.course_name.strip(),
            "day_of_week": course_data.day_of_week.strip(),
            "start_time": course_data.start_time.strip(),
            "end_time": course_data.end_time.strip(),
            "location": course_data.location.strip(),
            "last_reminder": None
        }
        
        # 添加到用户的课表中
        user.timetable.append(new_course)
        
        return {"message": "课程添加成功"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))   
    
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="localhost", port=8082)