from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
import uuid
import logging
import os
import eventlet

# 모듈 import
from auth import AuthManager
from room_manager import RoomManager
from user_manager import UserManager
from translator import TranslatorManager

# 로깅 설정
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default-secret-key-for-development')

# 모듈 초기화
auth_manager = AuthManager(app)
room_manager = RoomManager()
user_manager = UserManager()
translator_manager = TranslatorManager()

socketio = SocketIO(app, 
                  cors_allowed_origins="*", 
                  logger=False, 
                  engineio_logger=False,
                  async_mode='eventlet',
                  transports=['websocket', 'polling'])

@app.route('/')
def index():
    if not auth_manager.is_authenticated():
        return redirect('/login')
    return render_template('lobby.html', user=session['user'])

@app.route('/login')
def login():
    if auth_manager.is_authenticated():
        return redirect('/')
    return render_template('login.html')

@app.route('/lobby')
def lobby():
    if not auth_manager.is_authenticated():
        return redirect('/login')
    return render_template('lobby.html', user=session['user'])

@app.route('/chat/<room_id>')
def chat_room(room_id):
    if not auth_manager.is_authenticated():
        return redirect('/login')
    if not room_manager.room_exists(room_id):
        return redirect('/lobby')
    return render_template('chat.html', user=session['user'], room=room_manager.get_room_info(room_id))

@app.route('/auth/google')
def google_login():
    return auth_manager.google_login()

@app.route('/auth/google/callback')
def google_callback():
    return auth_manager.google_callback()

@app.route('/logout')
def logout():
    return auth_manager.logout()

@app.route('/api/rooms')
def get_rooms():
    """활성 채팅방 목록 반환"""
    return jsonify(room_manager.get_rooms_list())

# Socket 이벤트 핸들러들
@socketio.on('connect')
def on_connect():
    if not auth_manager.is_authenticated():
        return False
    
    user_info = user_manager.add_user(request.sid, session['user'])
    print(f'사용자 연결: {session["user"]["name"]} ({request.sid})')
    emit('connected', {'status': 'success', 'user': user_info})

@socketio.on('disconnect')
def on_disconnect():
    user = user_manager.remove_user(request.sid)
    if user and user['current_room']:
        # 현재 방에서 나가기 처리
        room_manager.leave_room(user['current_room'], request.sid)
        
        # 퇴장 알림 - 유령 방지를 위한 안전한 닉네임 확인
        if user.get('nickname'):
            room_users = room_manager.get_room_users(user['current_room'])
            for sid in room_users:
                if sid != request.sid and user_manager.is_user_exists(sid):
                    target_user = user_manager.get_user(sid)
                    if target_user and target_user.get('language'):
                        target_lang = target_user['language']
                        leave_msg = translator_manager.translate_text(
                            f"{user['nickname']} left the chat room.", 
                            'en', 
                            target_lang
                        )
                        emit('user_left', {
                            'message': leave_msg,
                            'nickname': user['nickname']
                        }, room=sid)

@socketio.on('set_language')
def on_set_language(data):
    """방 입장 시 언어 설정 - 새로운 이벤트"""
    if not user_manager.is_user_exists(request.sid):
        emit('language_error', {'message': 'User not found'})
        return
    
    language_code = translator_manager.get_language_code(data['language'])
    if user_manager.set_user_language(request.sid, language_code):
        # 세션에도 언어 정보 저장
        if 'user' in session:
            session['user']['language'] = language_code
            session.modified = True
        
        emit('language_set', {'success': True, 'language': language_code})
    else:
        emit('language_error', {'message': 'Failed to set language'})

@socketio.on('create_room')
def on_create_room(data):
    """새 채팅방 생성"""
    user = user_manager.get_user(request.sid)
    if not user:
        emit('create_room_error', {'message': 'Not authenticated'})
        return
    
    room_id = room_manager.create_room(
        data['title'],
        data.get('password', ''),
        data.get('max_users', 50),
        user['nickname']
    )
    
    emit('room_created', {
        'success': True,
        'room_id': room_id,
        'room_title': data['title']
    })

@socketio.on('join_room_request')
def on_join_room_request(data):
    """채팅방 입장 요청 - 언어 확인 추가"""
    user = user_manager.get_user(request.sid)
    if not user:
        emit('join_room_error', {'message': 'Not authenticated'})
        return
    
    # 언어가 설정되지 않은 경우 언어 선택 요구
    if not user.get('language'):
        emit('language_required', {'room_id': data['room_id']})
        return
    
    room_id = data['room_id']
    password = data.get('password', '')
    
    # 이전 방에서 나가기
    if user['current_room']:
        room_manager.leave_room(user['current_room'], request.sid)
        user_manager.set_user_room(request.sid, None)
    
    # 새 방 입장 시도
    success, message = room_manager.join_room(room_id, request.sid, password)
    
    if not success:
        emit('join_room_error', {'message': message})
        return
    
    # 입장 성공 처리
    join_room(room_id)
    user_manager.set_user_room(request.sid, room_id)
    
    # 입장 알림 - 중복 방지를 위한 단일 emit
    room_users = room_manager.get_room_users(room_id)
    join_msg_sent = False  # 중복 방지 플래그
    
    for sid in room_users:
        if sid != request.sid and user_manager.is_user_exists(sid):
            target_user = user_manager.get_user(sid)
            if target_user and target_user.get('language') and not join_msg_sent:
                target_lang = target_user['language']
                join_msg = translator_manager.translate_text(
                    f"{user['nickname']} joined the chat room.", 
                    'en', 
                    target_lang
                )
                emit('user_joined', {
                    'message': join_msg,
                    'nickname': user['nickname'],
                    'user': {
                        'nickname': user['nickname'],
                        'language': user['language'],
                        'picture': user['google_info'].get('picture', '')
                    }
                }, room=room_id)
                join_msg_sent = True  # 한 번만 전송되도록 설정
                break
    
    # 현재 방 사용자 목록 전송 - 정리된 목록
    current_room_users = user_manager.get_room_user_list(room_users)
    
    emit('room_joined', {
        'success': True,
        'room_info': room_manager.get_room_info(room_id),
        'users': current_room_users
    })

@socketio.on('leave_room')
def on_leave_room():
    """채팅방 나가기"""
    user = user_manager.get_user(request.sid)
    if not user or not user['current_room']:
        return
    
    room_id = user['current_room']
    room_manager.leave_room(room_id, request.sid)
    leave_room(room_id)
    user_manager.set_user_room(request.sid, None)
    
    emit('room_left', {'success': True})

@socketio.on('send_message')
def on_send_message(data):
    """메시지 전송 - 개선된 번역 로직"""
    sender = user_manager.get_user(request.sid)
    if not sender or not sender['current_room'] or not sender.get('language'):
        return
    
    room_id = sender['current_room']
    original_message = data['message']
    sender_nickname = sender['nickname']
    sender_lang = sender['language']
    
    print(f"메시지 전송: {sender_nickname} ({sender_lang}) -> {original_message}")
    
    # 같은 방의 모든 사용자에게 개별 번역하여 전송
    room_users = room_manager.get_room_users(room_id)
    
    for sid in room_users:
        if user_manager.is_user_exists(sid):
            target_user = user_manager.get_user(sid)
            if target_user and target_user.get('language'):
                target_lang = target_user['language']
                
                if sid == request.sid:
                    # 발신자에게는 원본 메시지
                    translated_message = original_message
                else:
                    # 수신자에게는 번역된 메시지 - 소스 언어 명시
                    translated_message = translator_manager.translate_text(
                        original_message, 
                        sender_lang, 
                        target_lang
                    )
                
                emit('receive_message', {
                    'nickname': sender_nickname,
                    'message': translated_message,
                    'original_language': translator_manager.get_language_name(sender_lang),
                    'is_own_message': (sid == request.sid)
                }, room=sid)

# 에러 핸들러
@app.errorhandler(500)
def internal_error(error):
    print(f"내부 서버 오류: {error}")
    return redirect('/login?error=server_error')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"서버 시작: 포트 {port}")
    print(f"Google OAuth 설정됨: {auth_manager.google is not None}")
    socketio.run(app, debug=False, host='0.0.0.0', port=port)