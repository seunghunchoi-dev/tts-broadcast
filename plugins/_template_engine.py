"""새 TTS 엔진 템플릿.

사용법:
 1) 이 파일을 복사해 이름에서 '_' 를 뺍니다 (예: my_engine.py). '_' 로 시작하는 파일은 로드되지 않습니다.
 2) synthesize() 에서 text 를 WAV 파일(out_path)로 저장하도록 구현합니다.
 3) config.json 의 engines 에 프로필을 추가하고 active_engine 을 바꿉니다.
      "my_profile": {"type": "my_engine", "options": {"model": "models/xxx", "speed": 1.0}}
 폐쇄망 환경이므로 인터넷 접속이 필요한 라이브러리/API 는 사용하지 마세요.
"""
from pathlib import Path

from tts_broadcast.engines import EngineError, TTSEngine, register_engine


@register_engine("my_engine")
class MyEngine(TTSEngine):

    def __init__(self, options=None, base_dir=None):
        super().__init__(options, base_dir)
        # 모델 로딩 등 무거운 초기화는 여기서 한 번만 수행
        # self.model = load_model(self.resolve(self.options["model"]))

    def synthesize(self, text: str, out_path: Path) -> None:
        # wav_bytes = self.model.tts(text, speed=self.options.get("speed", 1.0))
        # out_path.write_bytes(wav_bytes)
        raise EngineError("MyEngine.synthesize 를 구현하세요")

    def list_voices(self) -> list[str]:
        return []

    def close(self) -> None:
        pass
