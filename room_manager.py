import uuid
import hashlib
import eventlet
from threading import Lock

class RoomManager:
    def __init__(self):
        self.chat_rooms = {}  # room_id: room_info
        self.room_users = {}  # room_id: {user_session_ids}
        self.pending_room_cleanup = {}  # room_id -> eventlet timer
        self.lock = Lock()  # 동시성 제어
    
    def hash_password(self, password):
        """비밀번호 해시화 - 수정된 버전"""
        if not password or password.strip() == '':
            return None
        # salt 추가로 보안 강화
        salt = "globalchat_salt_2024"
        return hashlib.sha256((password + salt).encode()).hexdigest()
    
    def verify_password(self, password, hashed_password):
        """비밀번호 검증 - 수정된 버전"""
        if hashed_password is None:
            # 저장된 해시가 None이면 비밀번호가 없는 방
            return not password or password.strip() == ''
        
        if not password:
            return False
            
        input_hash = self.hash_password(password)
        return input_hash == hashed_password
    
    def create_room(self, title, password, max_users, created_by):
        """새 채팅방 생성"""
        with self.lock:
            room_id = str(uuid.uuid4())
            hashed_password = self.hash_password(password)
            
            self.chat_rooms[room_id] = {
                'id': room_id,
                'title': title,
                'password': hashed_password,
                'created_by': created_by,
                'created_at': str(uuid.uuid4()),
                'max_users': int(max_users)
            }
            
            self.room_users[room_id] = set()
            
            print(f"방 생성 완료: {room_id} - {title}")
            print(f"비밀번호 설정: {'있음' if hashed_password else '없음'}")
            
            return room_id
    
    def join_room(self, room_id, user_session_id, password=None):
        """방 입장 시도"""
        with self.lock:
            if room_id not in self.chat_rooms:
                return False, 'Room does not exist'
            
            room_info = self.chat_rooms[room_id]
            
            # 비밀번호 확인 - 수정된 로직
            if not self.verify_password(password, room_info['password']):
                print(f"비밀번호 불일치: 입력='{password}', 저장된 해시='{room_info['password']}'")
                return False, 'Incorrect password'
            
            # 최대 사용자 수 확인
            if len(self.room_users.get(room_id, set())) >= room_info['max_users']:
                return False, 'Room is full'
            
            # 방 입장 처리
            if room_id not in self.room_users:
                self.room_users[room_id] = set()
            
            self.room_users[room_id].add(user_session_id)
            
            # 누군가 들어왔으니 삭제 예약 취소
            self.cancel_room_cleanup(room_id)
            
            print(f"사용자 입장 성공: {user_session_id} -> {room_id}")
            print(f"현재 방 인원: {len(self.room_users[room_id])}")
            
            return True, 'Success'
    
    def leave_room(self, room_id, user_session_id):
        """방 퇴장 처리"""
        with self.lock:
            if room_id not in self.room_users:
                return
            
            # 사용자 제거 - 중복 제거 방지
            if user_session_id in self.room_users[room_id]:
                self.room_users[room_id].remove(user_session_id)
                print(f"사용자 퇴장: {user_session_id} <- {room_id}")
                print(f"남은 인원: {len(self.room_users[room_id])}")
            
            # 방이 비어있으면 삭제 예약
            if len(self.room_users[room_id]) == 0:
                self.schedule_room_cleanup(room_id, delay=6)
    
    def get_room_users(self, room_id):
        """방의 사용자 목록 반환 - 정리된 버전"""
        if room_id not in self.room_users:
            return set()
        return self.room_users[room_id].copy()  # 복사본 반환으로 동시성 이슈 방지
    
    def get_rooms_list(self):
        """활성 채팅방 목록 반환"""
        with self.lock:
            rooms_list = []
            for room_id, room_info in self.chat_rooms.items():
                user_count = len(self.room_users.get(room_id, set()))
                rooms_list.append({
                    'id': room_id,
                    'title': room_info['title'],
                    'has_password': bool(room_info['password']),
                    'user_count': user_count,
                    'max_users': room_info.get('max_users', 50),
                    'created_by': room_info['created_by']
                })
            return rooms_list
    
    def room_exists(self, room_id):
        """방 존재 여부 확인"""
        return room_id in self.chat_rooms
    
    def get_room_info(self, room_id):
        """방 정보 반환"""
        return self.chat_rooms.get(room_id)
    
    def cancel_room_cleanup(self, room_id):
        """해당 방의 삭제 예약이 있으면 취소"""
        timer = self.pending_room_cleanup.pop(room_id, None)
        if timer:
            try:
                timer.cancel()
                print(f"방 삭제 예약 취소: {room_id}")
            except Exception:
                pass
    
    def cleanup_room_if_still_empty(self, room_id):
        """유예 시간 후에도 방이 여전히 비었으면 실제 삭제"""
        with self.lock:
            try:
                if room_id in self.room_users and len(self.room_users[room_id]) == 0:
                    title = self.chat_rooms.get(room_id, {}).get('title', '')
                    self.chat_rooms.pop(room_id, None)
                    self.room_users.pop(room_id, None)
                    print(f"방 삭제됨(유예 만료): {room_id} - {title}")
                else:
                    print(f"방 삭제 취소(재입장 감지): {room_id}")
            finally:
                self.pending_room_cleanup.pop(room_id, None)
    
    def schedule_room_cleanup(self, room_id, delay=59):
        """빈 방을 delay초 뒤 삭제 예약"""
        self.cancel_room_cleanup(room_id)  # 중복 예약 방지
        t = eventlet.spawn_after(delay, self.cleanup_room_if_still_empty, room_id)
        self.pending_room_cleanup[room_id] = t
        print(f"빈 방 감지 → {room_id} {self.chat_rooms.get(room_id, {}).get('title','')} : {delay}초 후 삭제 예약")