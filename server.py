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
from email.mime.multipart import MIMEMultipart
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
    "password": "egtlxbbogzqvbbia"
}
def create_reminder_email_content(course: dict, user_name: str = "同学"):
    """创建丰富的HTML邮件内容 - 返回HTML和纯文本内容"""
    
    # 获取当前时间和课程时间
    tz = timezone('Asia/Shanghai')
    now = datetime.now(tz)
    course_time = datetime.strptime(course['start_time'], "%H:%M").time()
    course_datetime = datetime.combine(now.date(), course_time)
    
    # 计算剩余时间
    time_diff = course_datetime - now.replace(tzinfo=None)
    minutes_left = int(time_diff.total_seconds() / 60)
    
    # 根据课程时间段判断上课性质
    hour = course_time.hour
    if 8 <= hour < 12:
        period = "上午"
        greeting = "早上好"
        icon = "🌅"
    elif 12 <= hour < 18:
        period = "下午"
        greeting = "下午好"
        icon = "☀️"
    else:
        period = "晚上"
        greeting = "晚上好"
        icon = "🌙"
    
    # 课程类型图标（可以根据课程名称智能判断）
    course_icon = get_course_icon(course['course_name'])
    
    # HTML邮件模板
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                line-height: 1.6;
                color: #333;
                max-width: 600px;
                margin: 0 auto;
                background-color: #f5f5f5;
            }}
            .container {{
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                padding: 0;
                border-radius: 10px;
                box-shadow: 0 10px 25px rgba(0,0,0,0.1);
                overflow: hidden;
            }}
            .header {{
                background: rgba(255,255,255,0.1);
                color: white;
                padding: 30px 20px;
                text-align: center;
                border-bottom: 1px solid rgba(255,255,255,0.2);
            }}
            .header h1 {{
                margin: 0;
                font-size: 28px;
                font-weight: 300;
            }}
            .content {{
                background: white;
                padding: 30px;
            }}
            .alert-box {{
                background: linear-gradient(135deg, #ff6b6b, #ee5a24);
                color: white;
                padding: 20px;
                border-radius: 8px;
                text-align: center;
                margin-bottom: 25px;
                font-size: 18px;
                font-weight: bold;
            }}
            .course-info {{
                background: #f8f9fa;
                border-left: 4px solid #667eea;
                padding: 20px;
                margin: 20px 0;
                border-radius: 0 8px 8px 0;
            }}
            .info-row {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 8px 0;
                border-bottom: 1px solid #eee;
            }}
            .info-row:last-child {{
                border-bottom: none;
            }}
            .info-label {{
                font-weight: 600;
                color: #666;
                min-width: 80px;
            }}
            .info-value {{
                color: #333;
                font-weight: 500;
            }}
            .countdown {{
                background: linear-gradient(135deg, #ffeaa7, #fdcb6e);
                color: #2d3436;
                padding: 15px;
                border-radius: 8px;
                text-align: center;
                margin: 20px 0;
                font-size: 16px;
                font-weight: bold;
            }}
            .tips {{
                background: #e8f4fd;
                border: 1px solid #bee5eb;
                border-radius: 8px;
                padding: 15px;
                margin: 20px 0;
            }}
            .tips h3 {{
                color: #0c5460;
                margin-top: 0;
                font-size: 16px;
            }}
            .tips ul {{
                margin: 10px 0;
                padding-left: 20px;
            }}
            .tips li {{
                margin: 5px 0;
                color: #155724;
            }}
            .footer {{
                background: #f8f9fa;
                padding: 20px;
                text-align: center;
                color: #666;
                font-size: 14px;
                border-top: 1px solid #eee;
            }}
            .emoji {{
                font-size: 24px;
                margin-right: 10px;
            }}
            .highlight {{
                color: #667eea;
                font-weight: bold;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>{icon} {greeting}，{user_name}！</h1>
                <p>您的课程提醒到啦</p>
            </div>
            
            <div class="content">
                <div class="alert-box">
                    ⏰ 距离上课还有 <span class="highlight">{minutes_left}</span> 分钟
                </div>
                
                <div class="course-info">
                    <div class="info-row">
                        <span class="info-label">{course_icon} 课程</span>
                        <span class="info-value">{course['course_name']}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">📅 时间</span>
                        <span class="info-value">{course['day_of_week']} {course['start_time']} - {course['end_time']}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">📍 地点</span>
                        <span class="info-value">{course['location']}</span>
                    </div>
                    <div class="info-row">
                        <span class="info-label">⏱️ 时段</span>
                        <span class="info-value">{period}课程</span>
                    </div>
                </div>
                
                <div class="countdown">
                    🏃‍♀️ 建议现在开始准备出发！
                </div>
                
                <div class="tips">
                    <h3>📝 温馨提示：</h3>
                    <ul>
                        <li>🎒 请检查是否携带了相关课本和学习用品</li>
                        <li>🚗 考虑当前交通状况，合理规划出行路线</li>
                        <li>☔ 留意天气变化，必要时携带雨具</li>
                        <li>🔋 确保手机电量充足，以备不时之需</li>
                        <li>💧 记得携带水杯，保持水分充足</li>
                    </ul>
                </div>
                
                <div style="background: #fff3cd; border: 1px solid #ffeaa7; border-radius: 8px; padding: 15px; margin: 20px 0;">
                    <strong>🎯 今日目标：</strong> 准时到达，积极参与，收获满满！
                </div>
            </div>
            
            <div class="footer">
                <p>📧 这是一封自动发送的课程提醒邮件</p>
                <p>🕐 发送时间：{now.strftime('%Y年%m月%d日 %H:%M')}</p>
                <p>💝 祝您学习愉快，天天进步！</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    # 纯文本内容（作为备用）
    text_content = f"""
{greeting}，{user_name}！

【课程提醒】
距离上课还有 {minutes_left} 分钟

课程信息：
- 课程：{course['course_name']}
- 时间：{course['day_of_week']} {course['start_time']} - {course['end_time']}
- 地点：{course['location']}
- 时段：{period}课程

温馨提示：
- 请检查是否携带了相关课本和学习用品
- 考虑当前交通状况，合理规划出行路线
- 留意天气变化，必要时携带雨具
- 确保手机电量充足，以备不时之需
- 记得携带水杯，保持水分充足

今日目标：准时到达，积极参与，收获满满！

发送时间：{now.strftime('%Y年%m月%d日 %H:%M')}
祝您学习愉快，天天进步！
    """
    
    return html_content, text_content

def send_enhanced_reminder(to_email: str, course: dict, user_name: str = "同学"):
    """发送增强版邮件提醒"""
    
    # 创建邮件内容
    html_content, text_content = create_reminder_email_content(course, user_name)
    
    # 创建多部分邮件
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"📚 课程提醒：{course['course_name']} ({course['start_time']})"
    msg['From'] = "859766083@qq.com"
    msg['To'] = to_email
    
    # 添加纯文本和HTML部分
    text_part = MIMEText(text_content, 'plain', 'utf-8')
    html_part = MIMEText(html_content, 'html', 'utf-8')
    
    msg.attach(text_part)
    msg.attach(html_part)
    
    try:
        with smtplib.SMTP_SSL(SMTP_CONFIG['host'], SMTP_CONFIG['port']) as server:
            server.login(SMTP_CONFIG['user'], SMTP_CONFIG['password'])
            server.send_message(msg)
        print(f"✅ 增强版提醒邮件已发送至 {to_email}")
        return True
    except Exception as e:
        print(f"❌ 邮件发送失败：{str(e)}")
        return False

def get_course_icon(course_name: str) -> str:
    """根据课程名称返回相应的图标"""
    course_name_lower = course_name.lower()
    
    # 课程类型映射
    course_icons = {
        '数学': '🔢', '高数': '🔢', 'math': '🔢',
        '英语': '🔤', 'english': '🔤',
        '物理': '⚛️', 'physics': '⚛️',
        '化学': '🧪', 'chemistry': '🧪',
        '生物': '🧬', 'biology': '🧬',
        '历史': '📜', 'history': '📜',
        '地理': '🌍', 'geography': '🌍',
        '政治': '🏛️', 'politics': '🏛️',
        '语文': '📚', '中文': '📚',
        '计算机': '💻', '编程': '💻', 'computer': '💻',
        '体育': '⚽', 'sports': '⚽', '运动': '⚽',
        '音乐': '🎵', 'music': '🎵',
        '美术': '🎨', 'art': '🎨',
        '经济': '💰', 'economics': '💰',
        '管理': '📊', 'management': '📊',
        '心理': '🧠', 'psychology': '🧠',
        '医学': '⚕️', 'medicine': '⚕️',
        '法律': '⚖️', 'law': '⚖️',
        '实验': '🔬', 'lab': '🔬',
    }
    
    # 尝试匹配课程名称
    for keyword, icon in course_icons.items():
        if keyword in course_name_lower:
            return icon
    
    # 默认图标
    return '📖'

def send_enhanced_reminder(to_email: str, course: dict, user_name: str = "同学"):
    """发送增强版邮件提醒"""
    
    # 创建邮件内容
    html_content, text_content = create_reminder_email_content(course, user_name)
    
    # 创建多部分邮件
    msg = MIMEMultipart('alternative')
    msg['Subject'] = f"📚 课程提醒：{course['course_name']} ({course['start_time']})"
    msg['From'] = "859766083@qq.com"
    msg['To'] = to_email
    
    # 添加纯文本和HTML部分
    text_part = MIMEText(text_content, 'plain', 'utf-8')
    html_part = MIMEText(html_content, 'html', 'utf-8')
    
    msg.attach(text_part)
    msg.attach(html_part)
    
    try:
        with smtplib.SMTP_SSL(SMTP_CONFIG['host'], SMTP_CONFIG['port']) as server:
            server.login(SMTP_CONFIG['user'], SMTP_CONFIG['password'])
            server.send_message(msg)
        print(f"✅ 增强版提醒邮件已发送至 {to_email}")
        return True
    except Exception as e:
        print(f"❌ 邮件发送失败：{str(e)}")
        return False
   

def check_reminders():
    """每分钟执行一次的提醒检查"""
    tz = timezone('Asia/Shanghai')
    now = datetime.now(tz)
    weekday_map = {"周一":0, "周二":1, "周三":2, "周四":3, "周五":4, "周六":5, "周日":6}
    
    for user in data_store.users.values():
        for entry in user.timetable:
            # 检查星期匹配
            if weekday_map.get(entry['day_of_week'].strip(), -1) != now.weekday():
                continue
            
            # 解析课程时间
            try:
                course_time = datetime.strptime(entry['start_time'], "%H:%M").time()
                course_dt = datetime.combine(now.date(), course_time).replace(tzinfo=tz)
            except ValueError:
                continue
            
            # 计算时间差
            delta = (course_dt - now).total_seconds()
            if 0 < delta <= 600:  # 10分钟内
                if entry.get('last_reminder') != now.date().isoformat():
                    # 使用增强版邮件提醒
                    send_enhanced_reminder(user.email, entry, user.username)
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
    data_store.add_task(email, task.model_dump())
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