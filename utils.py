import yt_dlp as youtube_dl
import os

def get_related_videos(video_id, max_results=5):
    try:
        YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
        if not YOUTUBE_API_KEY:
            print("[utils] YOUTUBE_API_KEY is not set.", flush=True)
            return []
        
        # Removed googleapiclient.discovery related code as per user's request to use only yt-dlp
        # youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
        # 
        # response = youtube.search().list(
        #     part='snippet',
        #     relatedToVideoId=video_id,
        #     type='video',
        #     maxResults=max_results
        # ).execute()
        # 
        # return [
        #     {'title': item['snippet']['title'], 'id': item['id']['videoId']}
        #     for item in response.get('items', [])
        # ]
        
        # Using yt-dlp as the primary method for related videos
        with youtube_dl.YoutubeDL({'quiet': True, 'extract_flat': True}) as ydl:
            mix_url = f"https://www.youtube.com/watch?v={video_id}&list=RD{video_id}"
            playlist_info = ydl.extract_info(mix_url, download=False)
            entries = playlist_info.get('entries', [])
            # Filter out the original video and limit results
            return [entry for entry in entries if entry and entry.get('id') and entry.get('id') != video_id][:max_results]

    except Exception as e:
        print(f"[utils] Failed to get related videos: {e}", flush=True)
        return []
