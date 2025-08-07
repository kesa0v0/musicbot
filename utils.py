import yt_dlp as youtube_dl
import os
import logging

logger = logging.getLogger(__name__)

def get_related_videos(video_id, max_results=5):
    try:
        # Using yt-dlp as the primary method for related videos
        ydl_opts = {
            'quiet': True,
            'extract_flat': True,
            'source_address': '0.0.0.0'  # Force IPv4 to potentially fix SSL errors
        }
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            mix_url = f"https://www.youtube.com/watch?v={video_id}&list=RD{video_id}"
            playlist_info = ydl.extract_info(mix_url, download=False)
            entries = playlist_info.get('entries', [])
            # Filter out the original video and limit results
            return [entry for entry in entries if entry and entry.get('id') and entry.get('id') != video_id][:max_results]

    except Exception as e:
        logger.error(f"[utils] Failed to get related videos: {e}")
        return []
