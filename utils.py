
import yt_dlp as youtube_dl

def get_related_videos(video_id, max_results=5):
    """
    주어진 유튜브 영상 ID에 대해 관련 추천 영상을 반환합니다. (yt-dlp 사용)
    반환값: [{ 'title': str, 'id': str, 'webpage_url': str } ...]
    """
    ydl_opts = {
        'quiet': True,
        'extract_flat': True, # 플레이리스트나 채널의 모든 동영상을 가져오지 않고 목록만 가져옴
        'force_generic_extractor': True,
    }
    # yt-dlp는 "ytsearch:" 접두사를 사용하여 검색을 수행하고, 
    # "ytsearch1:"와 같이 숫자를 붙이면 해당 개수만큼 결과를 가져옵니다.
    # 관련 동영상을 직접 가져오는 기능은 없으므로, 원본 영상 제목으로 검색하여 유사한 영상을 찾습니다.
    # 더 나은 방법은 원본 영상의 채널에서 다른 영상을 가져오는 것일 수 있습니다.
    # 여기서는 단순화를 위해 검색을 사용합니다.
    
    # 먼저 원본 영상의 정보를 가져와 제목을 얻습니다.
    with youtube_dl.YoutubeDL({'quiet': True}) as ydl:
        try:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            search_query = info.get('title', video_id)
        except Exception:
            # 정보 추출 실패 시 video_id를 검색어로 사용
            search_query = video_id

    # 얻은 제목으로 유튜브 검색
    with youtube_dl.YoutubeDL(ydl_opts) as ydl:
        try:
            # `ytsearch{n}:`은 n개의 검색 결과를 반환합니다.
            search_result = ydl.extract_info(f"ytsearch{max_results}:{search_query}", download=False)
            # 검색 결과에서 원본 영상은 제외합니다.
            related = [
                entry for entry in search_result.get('entries', []) 
                if entry.get('id') and entry.get('id') != video_id
            ]
            return related
        except Exception as e:
            print(f"[utils.py] yt-dlp search failed: {e}")
            return []
