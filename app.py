from flask import Flask, render_template, request, session, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from googletrans import Translator
from authlib.integrations.flask_client import OAuth
import uuid
import logging
import os
import hashlib
import json
import eventlet  # 이미 requirements.txt에 있음

# 빈 방 삭제 예약 타이머 관리
pending_room_cleanup = {}  # room_id -> eventlet timer

def cancel_room_cleanup(room_id):
    """해당 방의 삭제 예약이 있으면 취소"""
    timer = pending_room_cleanup.pop(room_id, None)
    if timer:
        try:
            timer.cancel()
        except Exception:
            pass

def cleanup_room_if_still_empty(room_id):
    """유예 시간 후에도 방이 여전히 비었으면 실제 삭제"""
    try:
        if room_id in room_users and len(room_users[room_id]) == 0:
            title = chat_rooms.get(room_id, {}).get('title', '')
            chat_rooms.pop(room_id, None)
            room_users.pop(room_id, None)
            print(f"방 삭제됨(유예 만료): {room_id} - {title}")
        else:
            print(f"방 삭제 취소(재입장 감지): {room_id}")
    finally:
        pending_room_cleanup.pop(room_id, None)

def schedule_room_cleanup(room_id, delay=6):
    """빈 방을 delay초 뒤 삭제 예약"""
    cancel_room_cleanup(room_id)  # 중복 예약 방지
    t = eventlet.spawn_after(delay, cleanup_room_if_still_empty, room_id)
    pending_room_cleanup[room_id] = t
    print(f"빈 방 감지 → {room_id} {chat_rooms.get(room_id, {}).get('title','')} : {delay}초 후 삭제 예약")

# 로깅 설정
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default-secret-key-for-development')

# Google OAuth 설정
app.config['GOOGLE_CLIENT_ID'] = os.environ.get('GOOGLE_CLIENT_ID')
app.config['GOOGLE_CLIENT_SECRET'] = os.environ.get('GOOGLE_CLIENT_SECRET')

# 디버깅을 위한 환경 변수 출력
print(f"GOOGLE_CLIENT_ID: {'설정됨' if app.config['GOOGLE_CLIENT_ID'] else '설정되지 않음'}")
print(f"GOOGLE_CLIENT_SECRET: {'설정됨' if app.config['GOOGLE_CLIENT_SECRET'] else '설정되지 않음'}")

# OAuth 설정 검증
if not app.config['GOOGLE_CLIENT_ID'] or not app.config['GOOGLE_CLIENT_SECRET']:
    print("경고: Google OAuth 환경 변수가 설정되지 않았습니다!")
    print("GOOGLE_CLIENT_ID와 GOOGLE_CLIENT_SECRET을 Railway에서 설정하세요.")
    google = None
else:
    try:
        oauth = OAuth(app)
        google = oauth.register(
            name='google',
            client_id=app.config['GOOGLE_CLIENT_ID'],
            client_secret=app.config['GOOGLE_CLIENT_SECRET'],
            access_token_url='https://oauth2.googleapis.com/token',
            authorize_url='https://accounts.google.com/o/oauth2/auth',
            api_base_url='https://www.googleapis.com/oauth2/v2/',
            client_kwargs={
                # openid는 빼고 email, profile만
                'scope': 'email profile'
            }
        )
        print("Google OAuth 설정 완료")
    except Exception as e:
        print(f"Google OAuth 설정 오류: {e}")
        google = None

socketio = SocketIO(app, 
                  cors_allowed_origins="*", 
                  logger=False, 
                  engineio_logger=False,
                  async_mode='eventlet',
                  transports=['websocket', 'polling'])

# 번역기 초기화
translator = Translator()

# 전역 데이터 저장
users = {}  # session_id: user_info
chat_rooms = {}  # room_id: room_info
room_users = {}  # room_id: {user_session_ids}

# 언어 코드 매핑
LANGUAGES = {
    'korean': 'ko',
    'english': 'en', 
    'japanese': 'ja'
}

LANGUAGE_NAMES = {
    'ko': '한국어',
    'en': 'English',
    'ja': '日本語'
}

def translate_text(text, target_lang):
    """텍스트를 목표 언어로 번역"""
    try:
        if target_lang == 'auto' or target_lang == 'en':
            return text
        
        print(f"번역 시도: '{text}' -> {target_lang}")
        result = translator.translate(text, dest=target_lang)
        translated = result.text
        print(f"번역 결과: '{translated}'")
        return translated
    except Exception as e:
        print(f"번역 오류: {e}")
        return text

def hash_password(password):
    """비밀번호 해시화"""
    if not password:
        return None
    return hashlib.sha256(password.encode()).hexdigest()

@app.route('/')
def index():
    if 'user' not in session:
        return redirect('/login')
    return render_template('lobby.html', user=session['user'])

@app.route('/login')
def login():
    if 'user' in session:
        return redirect('/')
    return render_template('login.html', google_client_id=app.config['GOOGLE_CLIENT_ID'] or 'not-configured')

@app.route('/lobby')
def lobby():
    if 'user' not in session:
        return redirect('/login')
    return render_template('lobby.html', user=session['user'])

@app.route('/chat/<room_id>')
def chat_room(room_id):
    if 'user' not in session:
        return redirect('/login')
    if room_id not in chat_rooms:
        return redirect('/lobby')
    return render_template('chat.html', user=session['user'], room=chat_rooms[room_id])

@app.route('/auth/google')
def google_login():
    if not google:
        print("Google OAuth가 설정되지 않았습니다!")
        return redirect('/login?error=oauth_not_configured')
    
    try:
        # state에 언어 포함
        language = request.args.get('language', 'english')
        redirect_uri = url_for('google_callback', _external=True)
        print(f"Google OAuth 리다이렉트 URI: {redirect_uri}")
        print(f"전달된 언어: {language}")
        
        return google.authorize_redirect(redirect_uri, state=language)
        
    except Exception as e:
        print(f"Google OAuth 리다이렉트 오류: {e}")
        import traceback
        print(traceback.format_exc())
        return redirect('/login?error=oauth_redirect_failed')

@app.route('/auth/google/callback')
def google_callback():
    if not google:
        print("Google OAuth가 설정되지 않았습니다!")
        return redirect('/login?error=oauth_not_configured')
    
    try:
        print("Google OAuth 콜백 시작")
        print(f"Request args: {request.args}")
        
        # state 파라미터에서 언어 가져오기
        language = request.args.get('state', 'english')
        print(f"State에서 가져온 언어: {language}")
        
        if 'code' not in request.args:
            print("Authorization code가 없습니다!")
            error = request.args.get('error', 'unknown_error')
            print(f"OAuth error: {error}")
            return redirect(f'/login?error=no_authorization_code&oauth_error={error}')
        
        token = google.authorize_access_token()
        print(f"토큰 받음: {token is not None}")
        
        if token:
            access_token = token.get('access_token')
            if access_token:
                try:
                    import requests
                    userinfo_response = requests.get(
                        'https://www.googleapis.com/oauth2/v2/userinfo',
                        headers={'Authorization': f'Bearer {access_token}'}
                    )
                    
                    if userinfo_response.status_code == 200:
                        user_info = userinfo_response.json()
                        print(f"Google API에서 가져온 사용자 정보: {user_info}")
                        
                        # 언어 코드 변환
                        language_code = LANGUAGES.get(language, 'en')
                        session['user'] = {
                            'id': user_info['id'],
                            'email': user_info['email'],
                            'name': user_info['name'],
                            'picture': user_info.get('picture', ''),
                            'language': language_code
                        }
                        print(f"세션 저장 완료: {session['user']['name']}, 언어: {language_code}")
                        return redirect('/')
                    else:
                        print(f"Google API 오류: {userinfo_response.status_code}")
                        return redirect('/login?error=google_api_error')
                        
                except Exception as api_error:
                    print(f"Google API 호출 오류: {api_error}")
                    return redirect('/login?error=api_call_failed')
            else:
                print("access_token이 없습니다")
                return redirect('/login?error=no_access_token')
        else:
            print("토큰이 없습니다")
            return redirect('/login?error=no_token')
            
    except Exception as e:
        print(f"Google OAuth 콜백 오류: {e}")
        import traceback
        print(traceback.format_exc())
        return redirect('/login?error=callback_failed')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/api/rooms')
def get_rooms():
    """활성 채팅방 목록 반환"""
    rooms_list = []
    for room_id, room_info in chat_rooms.items():
        user_count = len(room_users.get(room_id, set()))
        rooms_list.append({
            'id': room_id,
            'title': room_info['title'],
            'has_password': bool(room_info['password']),
            'user_count': user_count,
            'max_users': room_info.get('max_users', 50),
            'created_by': room_info['created_by']
        })
    return jsonify(rooms_list)

@socketio.on('connect')
def on_connect():
    if 'user' not in session:
        return False  # 로그인하지 않은 사용자 연결 거부
    
    # 세션에서 언어 정보 가져오기
    user_language = session['user'].get('language', 'en')
    
    user_id = str(uuid.uuid4())
    users[request.sid] = {
        'user_id': user_id,
        'google_info': session['user'],
        'nickname': session['user']['name'],
        'language': user_language,  # 세션에서 가져온 언어 사용
        'current_room': None
    }
    print(f'사용자 연결됨: {session["user"]["name"]} ({request.sid}) - 언어: {users[request.sid]["language"]}')
    emit('connected', {'status': 'success', 'user': users[request.sid]})

@socketio.on('disconnect')
def on_disconnect():
    if request.sid in users:
        user = users[request.sid]
        
        # 현재 방에서 나가기
        if user['current_room']:
            leave_chat_room(user['current_room'])
        
        del users[request.sid]
        print(f'사용자 연결 해제됨: {user["nickname"]} ({request.sid})')

@socketio.on('set_language')
def on_set_language(data):
    """사용자 언어 설정"""
    if request.sid in users:
        language_code = LANGUAGES.get(data['language'], 'en')
        users[request.sid]['language'] = language_code
        
        # 세션에도 저장
        if 'user' in session:
            session['user']['language'] = language_code
            session.modified = True
        
        print(f"사용자 언어 설정: {request.sid} -> {data['language']} -> {language_code}")
        emit('language_set', {'success': True, 'language': language_code})

@socketio.on('create_room')
def on_create_room(data):
    """새 채팅방 생성"""
    if request.sid not in users:
        emit('create_room_error', {'message': 'Not authenticated'})
        return
    
    user = users[request.sid]
    room_id = str(uuid.uuid4())
    
    # 비밀번호 해시화
    hashed_password = hash_password(data.get('password', ''))
    
    chat_rooms[room_id] = {
        'id': room_id,
        'title': data['title'],
        'password': hashed_password,
        'created_by': user['nickname'],
        'created_at': str(uuid.uuid4()),
        'max_users': int(data.get('max_users', 50))
    }
    
    room_users[room_id] = set()
    
    print(f"방 생성 완료: {room_id} - {data['title']}")
    print(f"현재 방 목록: {list(chat_rooms.keys())}")
    
    # 방 생성자 자동 입장
    join_room(room_id)
    user['current_room'] = room_id
    room_users[room_id].add(request.sid)
    
    emit('room_created', {
        'success': True,
        'room_id': room_id,
        'room_title': data['title']
    })
    
    # 방 생성 완료 후 사용자가 직접 입장할 수 있도록 함
    print(f"방 생성자 자동 입장 완료: {user['nickname']} -> {room_id}")

@socketio.on('join_room_request')
def on_join_room_request(data):
    """채팅방 입장 요청"""
    if request.sid not in users:
        emit('join_room_error', {'message': 'Not authenticated'})
        return
    
    room_id = data['room_id']
    password = data.get('password', '')
    
    print(f"방 입장 시도: {room_id}")
    print(f"현재 방 목록: {list(chat_rooms.keys())}")
    print(f"방 정보: {chat_rooms.get(room_id, 'NOT_FOUND')}")
    
    if room_id not in chat_rooms:
        emit('join_room_error', {'message': 'Room does not exist'})
        return
    
    room_info = chat_rooms[room_id]
    user = users[request.sid]
    
    # 비밀번호 확인
    if room_info['password']:
        hashed_input = hash_password(password)
        print(f"비밀번호 확인: 입력={password}, 해시={hashed_input}, 저장된={room_info['password']}")
        if hashed_input != room_info['password']:
            emit('join_room_error', {'message': 'Incorrect password'})
            return
    
    # 최대 사용자 수 확인
    if len(room_users.get(room_id, set())) >= room_info['max_users']:
        emit('join_room_error', {'message': 'Room is full'})
        return
    
    # 이전 방에서 나가기
    if user['current_room']:
        leave_chat_room(user['current_room'])
    
    # 새 방 입장
    join_room(room_id)
    user['current_room'] = room_id
    room_users[room_id].add(request.sid)

    # ✅ 누군가 들어왔으니 삭제 예약 취소
    cancel_room_cleanup(room_id)
    
    # 다른 사용자들에게 입장 알림
    for sid in room_users[room_id]:
        if sid != request.sid and sid in users:
            target_lang = users[sid]['language']
            join_msg = translate_text(f"{user['nickname']} joined the chat room.", target_lang)
            emit('user_joined', {
                'message': join_msg,
                'nickname': user['nickname'],
                'user': {
                    'nickname': user['nickname'],
                    'language': user['language'],
                    'picture': user['google_info'].get('picture', '')
                }
            }, room=sid)
    
    # 현재 방 사용자 목록 전송
    current_room_users = []
    for sid in room_users[room_id]:
        if sid in users:
            room_user = users[sid]
            current_room_users.append({
                'nickname': room_user['nickname'],
                'language': room_user['language'],
                'picture': room_user['google_info'].get('picture', '')
            })
    
    emit('room_joined', {
        'success': True,
        'room_info': room_info,
        'users': current_room_users
    })

def leave_chat_room(room_id):
    """채팅방 나가기"""
    if request.sid not in users:
        return
        
    user = users[request.sid]
    
    if room_id in room_users and request.sid in room_users[room_id]:
        # 다른 사용자들에게 퇴장 알림
        for sid in room_users[room_id]:
            if sid != request.sid and sid in users:
                target_lang = users[sid]['language']
                leave_msg = translate_text(f"{user['nickname']} left the chat room.", target_lang)
                emit('user_left', {
                    'message': leave_msg,
                    'nickname': user['nickname']
                }, room=sid)
        
        room_users[room_id].remove(request.sid)
        leave_room(room_id)
        
        # 방이 비어있으면 삭제
        if len(room_users[room_id]) == 0:
            schedule_room_cleanup(room_id, delay=6)  # 5~8초 권장

@socketio.on('leave_room')
def on_leave_room():
    """채팅방 나가기"""
    if request.sid not in users:
        return
        
    user = users[request.sid]
    if user['current_room']:
        leave_chat_room(user['current_room'])
        user['current_room'] = None
    
    emit('room_left', {'success': True})

@socketio.on('send_message')
def on_send_message(data):
    if request.sid not in users:
        return
    
    sender = users[request.sid]
    if not sender['current_room']:
        return
    
    room_id = sender['current_room']
    original_message = data['message']
    sender_nickname = sender['nickname']
    sender_lang = sender['language']
    
    print(f"메시지 전송: {sender_nickname} ({sender_lang}) -> {original_message}")
    
    # 같은 방의 모든 사용자에게 번역된 메시지 전송
    for sid in room_users.get(room_id, set()):
        if sid in users:
            target_user = users[sid]
            target_lang = target_user['language']
            
            if sid == request.sid:
                # 발신자에게는 원본 메시지
                translated_message = original_message
                print(f"  발신자에게: {translated_message}")
            else:
                # 대상 언어가 발신자 언어와 같으면 번역 skip
                if sender_lang == target_lang:
                    translated_message = original_message
                else:
                    translated_message = translate_text(original_message, target_lang)
                print(f"  {target_user['nickname']}에게 ({target_lang}): {translated_message}")
            
            emit('receive_message', {
                'nickname': sender_nickname,
                'message': translated_message,
                'original_language': LANGUAGE_NAMES.get(sender_lang, sender_lang),
                'is_own_message': (sid == request.sid)
            }, room=sid)

# 에러 핸들러 추가
@app.errorhandler(500)
def internal_error(error):
    print(f"내부 서버 오류: {error}")
    return redirect('/login?error=server_error')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"서버 시작: 포트 {port}")
    print(f"Google OAuth 설정됨: {google is not None}")
    socketio.run(app, debug=False, host='0.0.0.0', port=port)