from googletrans import Translator
import time
import random

class TranslatorManager:
    def __init__(self):
        self.translator = Translator()
        self.language_codes = {
            'korean': 'ko',
            'english': 'en', 
            'japanese': 'ja'
        }
        
        self.language_names = {
            'ko': '한국어',
            'en': 'English',
            'ja': '日本語'
        }
    
    def detect_language(self, text):
        """텍스트 언어 감지"""
        try:
            detected = self.translator.detect(text)
            return detected.lang
        except Exception as e:
            print(f"언어 감지 오류: {e}")
            return 'en'  # 기본값
    
    def translate_text(self, text, source_lang, target_lang, retry_count=3):
        """
        텍스트 번역 - 개선된 버전
        source_lang: 발신자 언어 (명시적으로 지정)
        target_lang: 목표 언어
        """
        # 같은 언어면 번역하지 않음
        if source_lang == target_lang:
            return text
            
        # 빈 텍스트 처리
        if not text or text.strip() == '':
            return text
            
        print(f"번역 시도: '{text}' ({source_lang} -> {target_lang})")
        
        for attempt in range(retry_count):
            try:
                # 소스 언어를 명시적으로 지정하여 혼용 번역 방지
                result = self.translator.translate(
                    text, 
                    src=source_lang,  # 소스 언어 명시
                    dest=target_lang
                )
                
                translated = result.text
                
                # 번역 결과 검증
                if self._is_valid_translation(text, translated, source_lang, target_lang):
                    print(f"번역 성공: '{translated}'")
                    return translated
                else:
                    print(f"번역 품질 문제 감지, 재시도 중... (시도 {attempt + 1}/{retry_count})")
                    
            except Exception as e:
                print(f"번역 오류 (시도 {attempt + 1}/{retry_count}): {e}")
                if attempt < retry_count - 1:
                    # 재시도 전 잠시 대기 (API 제한 방지)
                    time.sleep(0.5 + random.uniform(0, 0.5))
                    continue
        
        # 모든 시도 실패 시 원본 텍스트 반환
        print(f"번역 실패, 원본 텍스트 반환: '{text}'")
        return text
    
    def _is_valid_translation(self, original, translated, source_lang, target_lang):
        """번역 결과 검증 - 혼용 언어 탐지"""
        if not translated:
            return False
            
        # 원본과 동일하면 번역이 안된 것으로 간주 (다른 언어인 경우)
        if original.strip() == translated.strip() and source_lang != target_lang:
            return False
        
        # 혼용 언어 탐지를 위한 간단한 검증
        try:
            detected_lang = self.detect_language(translated)
            
            # 번역된 텍스트의 언어가 목표 언어와 유사하거나 관련이 있는지 확인
            if target_lang == 'ko':
                # 한국어로 번역했는데 영어나 일본어가 많이 섞여있으면 문제
                if self._has_mixed_languages(translated, ['en', 'ja']):
                    return False
            elif target_lang == 'en':
                # 영어로 번역했는데 한국어나 일본어가 많이 섞여있으면 문제  
                if self._has_mixed_languages(translated, ['ko', 'ja']):
                    return False
            elif target_lang == 'ja':
                # 일본어로 번역했는데 한국어나 영어가 많이 섞여있으면 문제
                if self._has_mixed_languages(translated, ['ko', 'en']):
                    return False
                    
        except Exception:
            # 언어 검증 실패 시에도 번역 결과는 사용
            pass
            
        return True
    
    def _has_mixed_languages(self, text, unwanted_langs):
        """텍스트에 원치 않는 언어가 혼용되어 있는지 검사"""
        try:
            # 간단한 문자 기반 검증
            korean_chars = sum(1 for c in text if ord(c) >= 0xAC00 and ord(c) <= 0xD7AF)
            japanese_chars = sum(1 for c in text if (ord(c) >= 0x3040 and ord(c) <= 0x309F) or 
                                (ord(c) >= 0x30A0 and ord(c) <= 0x30FF))
            english_chars = sum(1 for c in text if c.isalpha() and ord(c) < 128)
            
            total_chars = len([c for c in text if c.isalpha() or (ord(c) >= 0x3040)])
            
            if total_chars == 0:
                return False
            
            # 원치 않는 언어의 비율이 30% 이상이면 혼용으로 판단
            for lang in unwanted_langs:
                if lang == 'ko' and korean_chars / max(total_chars, 1) > 0.3:
                    return True
                elif lang == 'ja' and japanese_chars / max(total_chars, 1) > 0.3:
                    return True  
                elif lang == 'en' and english_chars / max(total_chars, 1) > 0.3:
                    return True
                    
        except Exception:
            pass
            
        return False
    
    def get_language_name(self, code):
        """언어 코드를 언어 이름으로 변환"""
        return self.language_names.get(code, code)
    
    def get_language_code(self, name):
        """언어 이름을 코드로 변환"""
        return self.language_codes.get(name.lower(), 'en')