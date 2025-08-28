import uuid
from threading import Lock

class UserManager:
    def __init__(self):
        self.users = {}  # session_id: user_info
        self.lock = Lock()  # 동시성 제어
    
    def add_user(self, session_id, google_info):
        """새 사용자 추가 - 언어 정보는 나중에 설정"""
        with self.lock:
            user_id = str(uuid.uuid4())
            self.users[session_id] = {
                'user_id': user_id,
                'google_info': google_info,
                'nickname': google_info['name'],
                'language': None,  # 초기에는 None, 방 입장 시 설정
                'current_room': None
            }
            print(f'사용자 연결됨: {google_info["name"]} ({session_id})')
            return self.users[session_id]
    
    def remove_user(self, session_id):
        """사용자 제거 - 유령 방지를 위한 안전한 제거"""
        with self.lock:
            user = self.users.pop(session_id, None)
            if user:
                print(f'사용자 연결 해제됨: {user["nickname"]} ({session_id})')
                return user
            else:
                print(f'존재하지 않는 사용자 제거 시도: {session_id}')
                return None
    
    def get_user(self, session_id):
        """사용자 정보 반환"""
        return self.users.get(session_id)
    
    def set_user_language(self, session_id, language_code):
        """사용자 언어 설정"""
        with self.lock:
            if session_id in self.users:
                self.users[session_id]['language'] = language_code
                print(f"사용자 언어 설정: {session_id} -> {language_code}")
                return True
            return False
    
    def set_user_room(self, session_id, room_id):
        """사용자의 현재 방 설정"""
        with self.lock:
            if session_id in self.users:
                self.users[session_id]['current_room'] = room_id
                return True
            return False
    
    def get_room_user_list(self, room_user_ids):
        """방의 사용자 목록을 정리된 형태로 반환 - 중복 및 유령 제거"""
        user_list = []
        seen_users = set()  # 중복 방지
        
        with self.lock:
            for session_id in room_user_ids:
                if session_id in self.users:
                    user = self.users[session_id]
                    user_key = (user['nickname'], user['google_info']['id'])
                    
                    # 중복 사용자 체크
                    if user_key not in seen_users:
                        seen_users.add(user_key)
                        user_list.append({
                            'nickname': user['nickname'],
                            'language': user['language'] or 'en',  # 기본값 설정
                            'picture': user['google_info'].get('picture', ''),
                            'session_id': session_id  # 디버깅용
                        })
                else:
                    # 유령 사용자 감지
                    print(f"유령 사용자 감지: {session_id}")
        
        print(f"정리된 사용자 목록: {len(user_list)}명")
        return user_list
    
    def is_user_exists(self, session_id):
        """사용자 존재 여부 확인"""
        return session_id in self.users
    
    def get_user_nickname_safe(self, session_id):
        """안전한 사용자 닉네임 반환 - 유령 방지"""
        user = self.users.get(session_id)
        if user and user.get('nickname'):
            return user['nickname']
        return None  # None 반환으로 유령 메시지 방지
    
    def clean_ghost_users(self, active_sessions):
        """유령 사용자 정리 - 주기적으로 호출"""
        with self.lock:
            ghost_sessions = []
            for session_id in list(self.users.keys()):
                if session_id not in active_sessions:
                    ghost_sessions.append(session_id)
            
            for ghost_id in ghost_sessions:
                user = self.users.pop(ghost_id, None)
                if user:
                    print(f"유령 사용자 정리: {user['nickname']} ({ghost_id})")
            
            return len(ghost_sessions)