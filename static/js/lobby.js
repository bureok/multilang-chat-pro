// static/js/lobby.js
(() => {
    const socket = io();
  
    // 서버가 'connect' 시에 'connected' 이벤트로 사용자 정보를 내려줌
    // (app.py의 on_connect 핸들러에서 emit)
    let connected = false;
    let currentUser = {}; // { language: 'ko' | 'en' | 'ja', ... } 형태로 채워질 예정
  
    // 방/언어 선택 상태
    let pendingRoomId = null;
    let pendingRoomPassword = '';
    let selectedLanguage = null;
  
    // ---------- DOM 헬퍼 ----------
    function $(id) { return document.getElementById(id); }
  
    // ---------- 초기 바인딩 ----------
    document.addEventListener('DOMContentLoaded', () => {
      // 버튼 이벤트 바인딩 (인라인 onclick 제거)
      $('refreshRoomsBtn')?.addEventListener('click', loadRooms);
      $('createRoomBtn')?.addEventListener('click', createRoom);
  
      $('cancelPasswordBtn')?.addEventListener('click', () => {
        $('passwordModal').style.display = 'none';
        $('modalPassword').value = '';
        pendingRoomId = null;
        pendingRoomPassword = '';
      });
  
      $('joinRoomBtn')?.addEventListener('click', () => {
        const enteredPass = $('modalPassword').value;
        if (!pendingRoomId) return;
  
        $('passwordModal').style.display = 'none';
        $('modalPassword').value = '';
  
        if (!currentUser.language) {
          // 먼저 언어 설정
          pendingRoomPassword = enteredPass;
          showLanguageModal();
        } else {
          // 바로 입장 시도
          socket.emit('join_room_request', {
            room_id: pendingRoomId,
            password: enteredPass
          });
        }
      });
  
      // 언어 선택 모달
      $('cancelLanguageBtn')?.addEventListener('click', () => {
        $('languageModal').style.display = 'none';
        // 언어 선택 취소 시, 대기중이던 조인 작업도 취소
        pendingRoomId = null;
        pendingRoomPassword = '';
        selectedLanguage = null;
      });
  
      $('confirmLanguageBtn')?.addEventListener('click', () => {
        if (!selectedLanguage) return;
        socket.emit('set_language', { language: selectedLanguage });
      });
  
      // 언어 옵션 클릭
      document.querySelectorAll('.language-option').forEach(option => {
        option.addEventListener('click', () => {
          document.querySelectorAll('.language-option').forEach(opt => opt.classList.remove('selected'));
          option.classList.add('selected');
          selectedLanguage = option.dataset.language; // "english" | "korean" | "japanese"
          $('confirmLanguageBtn').disabled = false;
        });
      });
    });
  
    // ---------- 소켓 이벤트 ----------
    socket.on('connect', () => {
      connected = true;
      // 로드 타이밍이 빨라도 방 목록을 먼저 보여주는 게 UX 좋음
      loadRooms();
    });
  
    socket.on('connected', (data) => {
      // 서버에서 내려준 현재 사용자 정보
      // 형태: { status: 'success', user: {...} } 로 오게 되어 있음
      if (data && data.user) {
        currentUser = data.user || {};
      }
    });
  
    socket.on('create_room_error', (err) => {
      alert(err?.message || 'Failed to create room');
    });
  
    socket.on('room_created', (data) => {
      if (!data || !data.room_id) {
        alert('Room created, but no room_id returned.');
        return;
      }
      pendingRoomId = data.room_id;
      pendingRoomPassword = $('roomPassword')?.value || '';
  
      if (!currentUser.language) {
        showLanguageModal();
      } else {
        socket.emit('join_room_request', {
          room_id: pendingRoomId,
          password: pendingRoomPassword
        });
      }
    });
  
    socket.on('language_required', () => {
      // 서버가 언어 필요하다고 알려줌
      showLanguageModal();
    });
  
    socket.on('language_set', (data) => {
      if (!data?.success) {
        alert('Language setting failed: ' + (data?.message || 'Unknown error'));
        return;
      }
      // 서버에 저장 완료 → 로컬 상태도 갱신
      currentUser.language = data.language;
      $('languageModal').style.display = 'none';
  
      // 대기 중이던 방 입장 진행
      if (pendingRoomId) {
        socket.emit('join_room_request', {
          room_id: pendingRoomId,
          password: pendingRoomPassword
        });
      }
    });
  
    socket.on('join_room_error', (data) => {
      alert('Failed to join room: ' + (data?.message || 'Unknown error'));
      pendingRoomId = null;
      pendingRoomPassword = '';
    });
  
    socket.on('room_joined', (data) => {
      if (!data?.success) return;
      const roomId = data.room_info?.id || pendingRoomId;
      if (roomId) {
        // 채팅 페이지로 이동
        window.location.href = `/chat/${roomId}`;
      }
    });
  
    // ---------- 기능 함수 ----------
    function createRoom() {
      const title = $('roomTitle')?.value.trim();
      const password = $('roomPassword')?.value || '';
      const maxUsers = $('maxUsers')?.value || '50';
  
      if (!title) {
        alert('Please enter a room title.');
        $('roomTitle')?.focus();
        return;
      }
      if (password && password.length < 3) {
        alert('Password must be at least 3 characters, or leave it empty for a public room.');
        $('roomPassword')?.focus();
        return;
      }
  
      socket.emit('create_room', {
        title,
        password,
        max_users: maxUsers
      });
    }
  
    function loadRooms() {
      fetch('/api/rooms', { credentials: 'same-origin' })
        .then(res => res.json())
        .then(rooms => {
          const list = $('roomList');
          if (!list) return;
  
          list.innerHTML = '';
  
          if (!rooms || rooms.length === 0) {
            list.innerHTML = `
              <div class="empty-state">
                <div class="empty-state-icon">💬</div>
                <p>No chat rooms available.</p>
              </div>`;
            return;
          }
  
          rooms.forEach(room => {
            const item = document.createElement('div');
            item.className = 'room-item';
            item.dataset.roomId = room.id;
            item.dataset.hasPassword = String(room.has_password);
  
            item.innerHTML = `
              <div class="room-title">${room.title}</div>
              <div class="room-info">
                <span class="room-password">${room.has_password ? '🔒 Private' : 'Public'}</span>
                <span class="room-users">${room.user_count}/${room.max_users} users</span>
              </div>
            `;
  
            item.addEventListener('click', () => {
              pendingRoomId = room.id;
              pendingRoomPassword = '';
  
              if (room.has_password) {
                $('passwordModal').style.display = 'block';
              } else {
                if (!currentUser.language) {
                  showLanguageModal();
                } else {
                  socket.emit('join_room_request', { room_id: room.id });
                }
              }
            });
  
            list.appendChild(item);
          });
        })
        .catch(err => {
          console.error(err);
          alert('Failed to load rooms.');
        });
    }
  
    function showLanguageModal() {
      selectedLanguage = null;
      document.querySelectorAll('.language-option').forEach(opt => opt.classList.remove('selected'));
      $('confirmLanguageBtn').disabled = true;
      $('languageModal').style.display = 'block';
    }
  })();
  