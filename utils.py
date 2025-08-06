
from googleapiclient.discovery import build
import os

YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)

def get_related_videos(video_id, max_results=5):
    """
    주어진 유튜브 영상 ID에 대해 관련 추천 영상을 반환합니다.
    반환값: [{ 'title': str, 'videoId': str } ...]
    """
    response = youtube.search().list(
        part='snippet',
        related_to_video_id=video_id,
        type='video',
        max_results=max_results
    ).execute()
    return [
        {
            'title': item['snippet']['title'],
            'videoId': item['id']['videoId']
        }
        for item in response.get('items', [])
    ]
