from flask import session, request, redirect, url_for
from authlib.integrations.flask_client import OAuth
import requests
import os

class AuthManager:
    def __init__(self, app):
        self.app = app
        self.google = None
        self._setup_oauth()
    
    def _setup_oauth(self):
        """Google OAuth 설정"""
        app = self.app
        app.config['GOOGLE_CLIENT_ID'] = os.environ.get('GOOGLE_CLIENT_ID')
        app.config['GOOGLE_CLIENT_SECRET'] = os.environ.get('GOOGLE_CLIENT_SECRET')
        
        print(f"GOOGLE_CLIENT_ID: {'설정됨' if app.config['GOOGLE_CLIENT_ID'] else '설정되지 않음'}")
        print(f"GOOGLE_CLIENT_SECRET: {'설정됨' if app.config['GOOGLE_CLIENT_SECRET'] else '설정되지 않음'}")
        
        if not app.config['GOOGLE_CLIENT_ID'] or not app.config['GOOGLE_CLIENT_SECRET']:
            print("경고: Google OAuth 환경 변수가 설정되지 않았습니다!")
            return
        
        try:
            oauth = OAuth(app)
            self.google = oauth.register(
                name='google',
                client_id=app.config['GOOGLE_CLIENT_ID'],
                client_secret=app.config['GOOGLE_CLIENT_SECRET'],
                access_token_url='https://oauth2.googleapis.com/token',
                authorize_url='https://accounts.google.com/o/oauth2/auth',
                api_base_url='https://www.googleapis.com/oauth2/v2/',
                client_kwargs={
                    'scope': 'email profile'
                }
            )
            print("Google OAuth 설정 완료")
        except Exception as e:
            print(f"Google OAuth 설정 오류: {e}")
    
    def google_login(self):
        """Google 로그인 리다이렉트 - 언어 정보 제거"""
        if not self.google:
            print("Google OAuth가 설정되지 않았습니다!")
            return redirect('/login?error=oauth_not_configured')
        
        try:
            redirect_uri = url_for('google_callback', _external=True)
            print(f"Google OAuth 리다이렉트 URI: {redirect_uri}")
            return self.google.authorize_redirect(redirect_uri)
        except Exception as e:
            print(f"Google OAuth 리다이렉트 오류: {e}")
            import traceback
            print(traceback.format_exc())
            return redirect('/login?error=oauth_redirect_failed')
    
    def google_callback(self):
        """Google OAuth 콜백 처리 - 언어 정보 처리 제거"""
        if not self.google:
            print("Google OAuth가 설정되지 않았습니다!")
            return redirect('/login?error=oauth_not_configured')
        
        try:
            print("Google OAuth 콜백 시작")
            print(f"Request args: {request.args}")
            
            if 'code' not in request.args:
                print("Authorization code가 없습니다!")
                error = request.args.get('error', 'unknown_error')
                print(f"OAuth error: {error}")
                return redirect(f'/login?error=no_authorization_code&oauth_error={error}')
            
            token = self.google.authorize_access_token()
            print(f"토큰 받음: {token is not None}")
            
            if token:
                access_token = token.get('access_token')
                if access_token:
                    try:
                        userinfo_response = requests.get(
                            'https://www.googleapis.com/oauth2/v2/userinfo',
                            headers={'Authorization': f'Bearer {access_token}'}
                        )
                        
                        if userinfo_response.status_code == 200:
                            user_info = userinfo_response.json()
                            print(f"Google API에서 가져온 사용자 정보: {user_info}")
                            
                            # 언어 정보 제거 - 기본값만 설정
                            session['user'] = {
                                'id': user_info['id'],
                                'email': user_info['email'],
                                'name': user_info['name'],
                                'picture': user_info.get('picture', ''),
                                # language 필드 제거
                            }
                            print(f"세션 저장 완료: {session['user']['name']}")
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
    
    def is_authenticated(self):
        """인증 확인"""
        return 'user' in session
    
    def logout(self):
        """로그아웃"""
        session.clear()
        return redirect('/login')