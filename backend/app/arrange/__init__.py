"""곡 읽기 · 트랙끼리 맞추기.

생성기 · 추천이 저마다 자기 트랙만 보던 것을, 곡 전체를 한 번 읽은 결과(read_song)를 같이 쓰게 한다.
악기 추천(suggest) · 하이햇 자리 · 멜로디가 이 위에서 돌아간다 (docs/roadmap.md v0.3 "곡 읽기 · 트랙끼리 맞추기").
"""

from app.arrange.read import SongMap, TrackProfile, read_song

__all__ = ["SongMap", "TrackProfile", "read_song"]
