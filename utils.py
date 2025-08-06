
from googleapiclient.discovery import build
import os

# 환경변수 또는 직접 입력으로 API 키를 관리하세요.
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')

def get_related_videos(video_id, max_results=5):
    """
    주어진 유튜브 영상 ID에 대해 관련 추천 영상을 반환합니다.
    반환값: [{ 'title': str, 'videoId': str } ...]
    """
    youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
    response = youtube.search().list(
        part='snippet',
        relatedToVideoId=video_id,
        type='video',
        maxResults=max_results,
        q=''  # 검색어를 비워두면 관련 영상만 가져옵니다.
    ).execute()
    return [
        {
            'title': item['snippet']['title'],
            'videoId': item['id']['videoId']
        }
        for item in response.get('items', [])
    ]
