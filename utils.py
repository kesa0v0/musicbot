
import yt_dlp as youtube_dl

def get_related_videos(video_id, max_results=5):
    """
    주어진 유튜브 영상 ID에 대해 관련 추천 영상을 반환합니다. (yt-dlp 믹스 사용)
    반환값: [{ 'title': str, 'id': str, 'webpage_url': str } ...]
    """
    ydl_opts = {
        'quiet': True,
        'extract_flat': True,  # Just get the video metadata
        'noplaylist': False,   # We need to process the playlist
    }
    
    # YouTube Mix URL. RD stands for Radio/Mix.
    mix_url = f"https://www.youtube.com/watch?v={video_id}&list=RD{video_id}"
    
    with youtube_dl.YoutubeDL(ydl_opts) as ydl:
        try:
            # Extract info from the mix playlist
            playlist_info = ydl.extract_info(mix_url, download=False)
            
            # Get the list of videos in the playlist
            entries = playlist_info.get('entries', [])
            
            # The first video in a mix is usually the original one. We filter it out.
            related = [
                entry for entry in entries 
                if entry and entry.get('id') and entry.get('id') != video_id
            ]
            
            # Return up to max_results
            return related[:max_results]
            
        except Exception as e:
            print(f"[utils.py] Failed to get YouTube mix playlist: {e}")
            return []
