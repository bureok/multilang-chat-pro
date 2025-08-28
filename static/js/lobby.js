// static/js/lobby.js
(() => {
    const socket = io();
  
    let connected = false;
    let currentUser = {};
  
    let pendingRoomId = null;
    let pendingRoomPassword = '';
    let selectedLanguage = null;
  
    function $(id) { return document.getElementById(id); }
  
    document.addEventListener('DOMContentLoaded', () => {
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
          pendingRoomPassword = enteredPass;
          showLanguageModal();
        } else {
          socket.emit('join_room_request', {
            room_id: pendingRoomId,
            password: enteredPass
          });
        }
      });
  
      $('cancelLanguageBtn')?.addEventListener('click', () => {
        $('languageModal').style.display = 'none';
        pendingRoomId = null;
        pendingRoomPassword = '';
        selectedLanguage = null;
      });
  
      $('confirmLanguageBtn')?.addEventListener('click', () => {
        if (!selectedLanguage) return;
        socket.emit('set_language', { language: selectedLanguage });
      });
  
      document.querySelectorAll('.language-option').forEach(option => {
        option.addEventListener('click', () => {
          document.querySelectorAll('.language-option').forEach(opt => opt.classList.remove('selected'));
          option.classList.add('selected');
          selectedLanguage = option.dataset.language; // english|korean|japanese
          $('confirmLanguageBtn').disabled = false;
        });
      });
    });
  
    socket.on('connect', () => {
      connected = true;
      loadRooms();
    });
  
    socket.on('connected', (data) => {
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
      showLanguageModal();
    });
  
    // ★ 언어 설정되면 코드 저장해 둔다 (ko|en|ja)
    socket.on('language_set', (data) => {
      if (!data?.success) {
        alert('Language setting failed: ' + (data?.message || 'Unknown error'));
        return;
      }
      currentUser.language = data.language;
      sessionStorage.setItem('userLanguageCode', data.language); // <-- 브리지
      $('languageModal').style.display = 'none';
  
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
      if (!roomId) return;
  
      // ★ 리다이렉트 전에 비밀번호/언어 코드를 세션스토리지에 저장
      sessionStorage.setItem('autoJoinRoomId', roomId);
      if (pendingRoomPassword) {
        sessionStorage.setItem('roomPassword', pendingRoomPassword);
      } else {
        sessionStorage.removeItem('roomPassword');
      }
      if (currentUser.language) {
        sessionStorage.setItem('userLanguageCode', currentUser.language);
      }
  
      window.location.href = `/chat/${roomId}`;
    });
  
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
  
      socket.emit('create_room', { title, password, max_users: maxUsers });
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
              </div>`;
  
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
  